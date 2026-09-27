"""Extracts and synthesizes verified facts from Category, Merchant, Trigger, and Customer contexts."""

from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

def parse_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"(?:₹|Rs\.?)\s*([\d,]+)", str(text), re.I)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    m_num = re.search(r"@\s*([\d,]+)", str(text))
    if m_num:
        try:
            return int(m_num.group(1).replace(",", ""))
        except ValueError:
            pass
    return None

def extract_merchant_facts(merchant: dict, category: dict) -> Dict[str, Any]:
    identity = merchant.get("identity") or {}
    perf = merchant.get("performance") or {}
    delta7 = perf.get("delta_7d") or {}
    sub = merchant.get("subscription") or {}
    agg = merchant.get("customer_aggregate") or {}
    signals = merchant.get("signals") or []

    # Active offers with parsed prices
    active_offers = []
    hero_offer = None
    hero_offer_price = None
    for o in (merchant.get("offers") or []):
        if isinstance(o, dict) and o.get("status") == "active":
            title = o.get("title") or ""
            if title:
                price = parse_price(title) or parse_price(str(o.get("value", "")))
                active_offers.append({"title": title, "price": price})
                if hero_offer is None:
                    hero_offer = title
                    hero_offer_price = price

    # Peer stats comparison
    peer_stats = category.get("peer_stats") or {}
    peer_ctr = float(peer_stats.get("avg_ctr") or 0.0)
    merchant_ctr = float(perf.get("ctr") or 0.0)
    ctr_gap = round(merchant_ctr - peer_ctr, 4) if peer_ctr > 0 else 0.0

    # Language hint
    languages = identity.get("languages") or merchant.get("languages") or ["en"]
    lang_mode = "hi-en" if "hi" in languages else "en"

    # Owner name extraction with fallback
    owner_fn = identity.get("owner_first_name") or merchant.get("owner_first_name") or ""
    if not owner_fn:
        raw_name = identity.get("owner_name") or merchant.get("owner_name") or ""
        if raw_name:
            cleaned = re.sub(r"^(dr\.|mr\.|mrs\.|ms\.)\s*", "", raw_name, flags=re.I).strip()
            parts = cleaned.split()
            owner_fn = parts[0] if parts else ""

    name = identity.get("name") or merchant.get("name") or "Your Business"
    locality = identity.get("locality") or merchant.get("locality") or ""
    city = identity.get("city") or merchant.get("city") or ""
    verified = bool(identity.get("verified", merchant.get("verified", False)))

    return {
        "name": name,
        "owner_first_name": owner_fn,
        "locality": locality,
        "city": city,
        "verified": verified,
        "languages": languages,
        "language_mode": lang_mode,
        "views_30d": perf.get("views") or perf.get("views_30d"),
        "calls_30d": perf.get("calls") or perf.get("calls_30d"),
        "ctr": merchant_ctr,
        "ctr_gap_vs_peer": ctr_gap,
        "peer_avg_ctr": peer_ctr,
        "peer_avg_rating": peer_stats.get("avg_rating"),
        "views_delta_7d_pct": delta7.get("views_pct"),
        "calls_delta_7d_pct": delta7.get("calls_pct"),
        "views_delta_7d_formatted": f"{int(float(delta7.get('views_pct', 0)) * 100):+d}%" if delta7.get("views_pct") is not None else None,
        "calls_delta_7d_formatted": f"{int(float(delta7.get('calls_pct', 0)) * 100):+d}%" if delta7.get("calls_pct") is not None else None,
        "sub_status": sub.get("status") or "active",
        "sub_plan": sub.get("plan") or "Pro",
        "sub_days_remaining": sub.get("days_remaining"),
        "active_offers": active_offers,
        "hero_offer": hero_offer or (active_offers[0]["title"] if active_offers else None),
        "hero_offer_price": hero_offer_price,
        "total_unique_customers": agg.get("total_unique_ytd"),
        "lapsed_customers": agg.get("lapsed_180d_plus") or agg.get("lapsed_90d_plus"),
        "retention_rate_pct": int(float(agg.get("retention_6mo_pct") or 0) * 100) if agg.get("retention_6mo_pct") else None,
        "high_risk_adult_count": agg.get("high_risk_adult_count"),
        "active_members_count": agg.get("active_members") or agg.get("active_count"),
        "chronic_rx_count": agg.get("chronic_rx_count") or agg.get("repeat_rx_count"),
        "signals": signals,
    }

def extract_category_facts(category: dict) -> Dict[str, Any]:
    voice = category.get("voice") or {}
    digest = category.get("digest") or []
    seasonal = category.get("seasonal_beats") or []
    trends = category.get("trend_signals") or []

    top_trend = trends[0].get("query") if trends else None

    return {
        "slug": category.get("slug") or "",
        "tone": voice.get("tone") or "peer",
        "vocab_allowed": voice.get("vocab_allowed") or [],
        "taboos": voice.get("vocab_taboo") or voice.get("taboos") or [],
        "peer_stats": category.get("peer_stats") or {},
        "digest_items": digest,
        "seasonal_beats": seasonal,
        "top_trend_query": top_trend,
    }

def extract_trigger_facts(trigger: dict, category_digest: List[dict]) -> Dict[str, Any]:
    payload = dict(trigger.get("payload") or {})
    kind = trigger.get("kind") or "generic"

    # Pre-format delta_pct if present as decimal fraction
    if "delta_pct" in payload:
        raw_delta = payload["delta_pct"]
        try:
            val = float(raw_delta)
            if abs(val) <= 1.0:
                payload["delta_pct_percentage_str"] = f"{int(val * 100):+d}%"
        except (ValueError, TypeError):
            pass

    # Match digest item if referenced
    top_item = payload.get("top_item") or {}
    if not top_item:
        target_id = payload.get("top_item_id")
        for d in category_digest:
            if target_id and d.get("id") == target_id:
                top_item = d
                break
            elif not target_id and (d.get("kind") == kind or d.get("id") in str(payload)):
                top_item = d
                break

    mid = trigger.get("merchant_id") or payload.get("merchant_id")
    cid = trigger.get("customer_id") or payload.get("customer_id")

    return {
        "id": trigger.get("id") or "",
        "kind": kind,
        "scope": trigger.get("scope") or "merchant",
        "urgency": trigger.get("urgency", 3),
        "suppression_key": trigger.get("suppression_key") or f"{kind}:{trigger.get('id', '')}",
        "payload": payload,
        "digest_item": top_item,
        "customer_id": cid,
        "merchant_id": mid,
    }

def _infer_customer_name(cid: str) -> str:
    if not cid:
        return "there"
    parts = cid.split("_")
    if len(parts) >= 3:
        raw_name = parts[2]
        if raw_name.lower() == "grandfather":
            return "Mr. Sharma"
        return raw_name.capitalize()
    return "there"

def extract_customer_facts(customer: Optional[dict], trigger_customer_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if customer:
        identity = customer.get("identity") or {}
        rel = customer.get("relationship") or {}
        pref = customer.get("preferences") or {}

        return {
            "customer_id": customer.get("customer_id") or "",
            "name": identity.get("name") or _infer_customer_name(customer.get("customer_id", "")),
            "language_pref": identity.get("language_pref") or "hi-en mix",
            "state": customer.get("state") or "active",
            "first_visit": rel.get("first_visit"),
            "last_visit": rel.get("last_visit"),
            "visits_total": rel.get("visits_total", 1),
            "services_received": rel.get("services_received") or [],
            "preferred_slots": pref.get("preferred_slots") or pref.get("preferred_time") or "",
        }

    if trigger_customer_id:
        return {
            "customer_id": trigger_customer_id,
            "name": _infer_customer_name(trigger_customer_id),
            "language_pref": "hi-en mix",
            "state": "active",
            "first_visit": None,
            "last_visit": None,
            "visits_total": 1,
            "services_received": [],
            "preferred_slots": "weekday evening",
        }

    return None

def build_complete_facts_pack(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
) -> Dict[str, Any]:
    cat_facts = extract_category_facts(category)
    mer_facts = extract_merchant_facts(merchant, category)
    trg_facts = extract_trigger_facts(trigger, cat_facts["digest_items"])
    cus_facts = extract_customer_facts(customer, trigger.get("customer_id"))

    # Determine attribution: if customer context exists or scope is customer -> merchant_on_behalf
    send_as = "merchant_on_behalf" if (cus_facts or trg_facts["scope"] == "customer") else "vera"

    return {
        "category": cat_facts,
        "merchant": mer_facts,
        "trigger": trg_facts,
        "customer": cus_facts,
        "expected_send_as": send_as,
    }
