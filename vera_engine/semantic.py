"""Semantic compatibility firewall and domain adapter for cross-category triggers."""

from __future__ import annotations
from typing import Dict, Any, Tuple, Optional

CATEGORY_KEYWORDS = {
    "dentists": {"dental", "dentist", "teeth", "caries", "fluoride", "cleaning", "smile", "aligner", "radiograph", "dci", "jida", "oral", "tooth", "clinic"},
    "salons": {"salon", "hair", "haircut", "facial", "makeup", "bridal", "grooming", "spa", "balayage", "keratin", "skin", "beauty", "styling"},
    "restaurants": {"restaurant", "food", "dining", "thali", "cafe", "pizza", "swiggy", "zomato", "covers", "delivery", "order", "bogo", "dosa", "biryani", "kitchen"},
    "gyms": {"gym", "fitness", "workout", "yoga", "training", "trainer", "class", "members", "hiit", "weight", "exercise", "strength"},
    "pharmacies": {"pharmacy", "medicine", "medicos", "chemist", "rx", "refill", "dosage", "drug", "atorvastatin", "metformin", "tablets", "chronic", "recall", "pharma"},
}

TRIGGER_AFFINITIES = {
    "research_digest": "dentists",
    "compliance_dci_radiograph": "dentists",
    "cde_opportunity": "dentists",
    "bridal_followup": "salons",
    "wedding_package_followup": "salons",
    "ipl_match_today": "restaurants",
    "corporate_thali_planning": "restaurants",
    "kids_yoga_program_drafting": "gyms",
    "seasonal_acquisition_dip": "gyms",
    "supply_atorvastatin_recall": "pharmacies",
    "chronic_refill_due": "pharmacies",
    "summer_demand_shift": "pharmacies",
}

def check_compatibility(category_slug: str, trigger_kind: str, trigger_payload: dict) -> Tuple[bool, Optional[str]]:
    """
    Returns (is_compatible, adaptation_hint).
    """
    # Universal triggers that apply to all merchants
    universal_kinds = {
        "perf_spike", "perf_dip", "milestone_reached", "dormant_with_vera",
        "renewal_due", "winback_eligible", "curious_ask_due", "festival_upcoming",
        "appointment_tomorrow", "competitor_opened", "gbp_unverified",
    }
    if trigger_kind in universal_kinds:
        return True, None

    # Check payload category match if explicitly declared
    payload_cat = trigger_payload.get("category")
    if payload_cat and payload_cat != category_slug:
        return False, f"Trigger was created for {payload_cat}, adapt cleanly for {category_slug}."

    # Check known affinities
    for aff_key, target_cat in TRIGGER_AFFINITIES.items():
        if aff_key in trigger_kind and target_cat != category_slug:
            return False, f"Cross-domain trigger ({aff_key} -> {category_slug}). Reframe to {category_slug} domain."

    return True, None

def adapt_cross_domain_trigger(category_slug: str, trigger_data: dict, merchant_data: dict) -> dict:
    """
    Adapts a cross-domain trigger so the composed message is 100% appropriate for the merchant's business.
    """
    kind = trigger_data.get("kind", "")
    payload = dict(trigger_data.get("payload", {}))

    # Pharmacy recall sent to non-pharmacy -> reframe to category equipment / standards check
    if "atorvastatin" in str(payload) or "supply_alert" in kind:
        if category_slug != "pharmacies":
            payload["clean_topic"] = f"Quality & safety equipment audit for {category_slug}"

    # Kids yoga / thali planning sent to wrong category -> adapt to merchant's hero service
    if "corporate_thali" in str(payload) and category_slug != "restaurants":
        payload["adapted_offering"] = f"Special corporate group package for {merchant_data.get('name')}"

    if "kids_yoga" in str(payload) and category_slug not in ("gyms", "salons"):
        payload["adapted_offering"] = f"Seasonal service package for {merchant_data.get('name')}"

    # IPL match sent to non-restaurant -> focus on match day schedule / evening traffic
    if "ipl" in kind and category_slug != "restaurants":
        payload["focus"] = "pre-match evening booking rush and local traffic adjustment"

    adapted = dict(trigger_data)
    adapted["payload"] = payload
    return adapted
