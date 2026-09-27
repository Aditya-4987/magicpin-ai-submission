#!/usr/bin/env python3
"""
Vera-Omni: Submission Builder
Generates submission.jsonl (30 test pairs) using Vera-Omni LLM Composer or Deterministic Fallbacks.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vera_engine.composer import compose_message  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_submission")


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Build submission.jsonl for Vera-Omni.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use deterministic zero-defect templates instead of LLM inference.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "submission.jsonl"),
        help="Target output file path (default: submission.jsonl)",
    )
    args = parser.parse_args()

    expanded_dir = ROOT / "expanded"
    pairs_path = expanded_dir / "test_pairs.json"
    if not pairs_path.exists():
        logger.error(f"Test pairs not found at {pairs_path}.")
        return 1

    pairs_data = load_json(pairs_path)
    pairs = pairs_data.get("pairs", [])
    logger.info(f"Loaded {len(pairs)} test pairs from {pairs_path.name}")

    # Load categories
    categories = {}
    for cat_file in (expanded_dir / "categories").glob("*.json"):
        cat_data = load_json(cat_file)
        categories[cat_data["slug"]] = cat_data

    out_lines = []
    success_count = 0

    for idx, p in enumerate(pairs, 1):
        test_id = p.get("test_id")
        tid = p.get("trigger_id")
        mid = p.get("merchant_id")
        cid = p.get("customer_id")

        tr_path = expanded_dir / "triggers" / f"{tid}.json"
        m_path = expanded_dir / "merchants" / f"{mid}.json"

        if not tr_path.exists() or not m_path.exists():
            logger.warning(f"[{test_id}] Missing trigger {tid} or merchant {mid}. Skipping.")
            continue

        trigger = load_json(tr_path)
        merchant = load_json(m_path)
        slug = merchant.get("category_slug")
        category = categories.get(slug, {})

        customer = None
        if cid:
            cp = expanded_dir / "customers" / f"{cid}.json"
            if cp.exists():
                customer = load_json(cp)

        logger.info(f"[{idx}/{len(pairs)}] Composing {test_id} ({slug} / {trigger.get('kind')})")

        result = compose_message(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            use_llm=not args.no_llm,
        )
        if not args.no_llm:
            import time
            time.sleep(1.0)

        entry = {
            "test_id": test_id,
            "body": result.get("body", "").strip(),
            "cta": result.get("cta", "binary_yes_no"),
            "send_as": result.get("send_as", "vera"),
            "suppression_key": result.get("suppression_key", ""),
            "rationale": result.get("rationale", ""),
        }

        out_lines.append(json.dumps(entry, ensure_ascii=False))
        success_count += 1

    out_path = Path(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + ("\n" if out_lines else ""))

    logger.info(f"Successfully generated {success_count} submission entries -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
