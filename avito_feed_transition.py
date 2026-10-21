"""Fail-closed validation of successive Avito pilot XML feed generations.

No Avito API calls or publication. Used before publishing a replacement XML
snapshot. It detects unexpected extra IDs, sudden prices, large removals, and
all-zero feeds. The upstream generator must use a *fresh* Rossko price list.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_expand_canary import approved_canary_ids
from avito_next_five_preflight import approved_next_five_ids
from avito_second_five_preflight import approved_second_five_ids
from avito_third_ten_preflight import approved_third_ten_ids
from avito_fourth_eleven_preflight import approved_fourth_eleven_ids
from avito_xml_v3_diagnostic import TEST_SKUS


def expected_pilot_ids() -> set[str]:
    return {
        stable_id(group, brand, article)
        for group, items in TEST_SKUS.items()
        for brand, article in items
    }


def parse_feed(xml_bytes: bytes) -> dict[str, int]:
    root = ET.fromstring(xml_bytes)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Not an Avito XML v3 feed")
    result = {}
    for ad in root.findall("Ad"):
        sku = (ad.findtext("Id") or "").strip()
        price = (ad.findtext("Price") or "").strip()
        if not sku or sku in result:
            raise ValueError("Missing or duplicate Avito listing ID")
        if not price.isdigit() or int(price) <= 0:
            raise ValueError("Invalid Avito item price for " + sku)
        if not ad.find("Images") is not None:
            raise ValueError("Missing images for " + sku)
        if not (ad.findtext("OEM") or "").strip():
            raise ValueError("Missing verified OEM for " + sku)
        result[sku] = int(price)
    return result


def analyze_transition(previous: bytes | None, proposed: bytes, *,
                       allow_initial_pilot: bool = False,
                       max_removed: int = 2,
                       max_jump_pct: int = 40,
                       approved_extra_ids: set[str] | None = None) -> dict:
    from avito_feed import stable_id
    from avito_expand_canary import CANARY
    permitted_extra = {stable_id("Тормозные диски", "CTR", article) for _, article in CANARY} | approved_next_five_ids() | approved_second_five_ids() | approved_third_ten_ids() | approved_fourth_eleven_ids()
    if not (approved_extra_ids or set()) <= permitted_extra:
        raise ValueError("Unexpected additional Avito ID outside fixed catalog")
    expected = expected_pilot_ids() | (approved_extra_ids or set())
    newer = parse_feed(proposed)
    if not newer:
        raise ValueError("Refuse empty feed: Avito might retain stale offers or remove all")
    if not set(newer) <= expected:
        raise ValueError("Unexpected new listing ID outside approved 50+2+5 catalog")
    if previous is None:
        if not allow_initial_pilot:
            raise ValueError("Initial publication must be explicitly enabled")
        if len(newer) != len(expected):
            raise ValueError("Initial pilot must contain all documented pilot items")
        return {
            "added": len(newer), "removed": 0, "repriced": 0,
            "current_ads": len(newer), "initial": True,
            "ids": sorted(newer),
        }
    older = parse_feed(previous)
    if not set(older) <= expected:
        raise ValueError("Previous feed controlled an unexpected ID")
    removed = set(older) - set(newer)
    added = set(newer) - set(older)
    # Newly approved SKUs and returning original pilot SKUs are separate.
    # A source restock must not block a safe two-product expansion.
    newly_approved = added & (approved_extra_ids or set())
    returning_pilot = added & expected_pilot_ids()
    new_cap = 11 if approved_fourth_eleven_ids() & (approved_extra_ids or set()) else (10 if approved_third_ten_ids() & (approved_extra_ids or set()) else (5 if (approved_next_five_ids() | approved_second_five_ids()) & (approved_extra_ids or set()) else 2))
    if len(newly_approved) > new_cap or len(returning_pilot) > 2:
        raise ValueError("Unexpected addition of too many new or returning SKUs")
    # Genuine local sell-outs are permitted in small batches; a sudden large
    # shrinkage could mean a wrong warehouse, broken input or missing CSV rows.
    if len(removed) > max_removed:
        raise ValueError(f"Unexpected removal of {len(removed)} SKUs, needs manual review")
    repriced = 0
    for sku in set(newer) & set(older):
        old_price, new_price = older[sku], newer[sku]
        pct = abs(new_price - old_price) * 100 / old_price
        if pct > max_jump_pct:
            raise ValueError(f"Price moved {pct:.1f}% for {sku}: review before updating")
        repriced += old_price != new_price
    return {
        "added": len(added), "removed": len(removed), "repriced": repriced,
        "current_ads": len(newer), "initial": False,
        "removed_ids": sorted(removed),
        "added_ids": sorted(added),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", required=True)
    p.add_argument("--previous", help="Required except for explicit first-time dry run")
    p.add_argument("--allow-initial-pilot", action="store_true")
    p.add_argument("--report", default="")
    p.add_argument("--approved-new", default="")
    p.add_argument("--approved-next-five", action="store_true")
    p.add_argument("--approved-second-five", action="store_true")
    p.add_argument("--approved-third-ten", action="store_true")
    p.add_argument("--approved-fourth-eleven", action="store_true")
    args = p.parse_args()
    result = analyze_transition(
        Path(args.previous).read_bytes() if args.previous else None,
        Path(args.candidate).read_bytes(),
        allow_initial_pilot=args.allow_initial_pilot,
        approved_extra_ids=(approved_canary_ids(Path(args.approved_new)) if args.approved_new else set())
        | (approved_next_five_ids() if args.approved_next_five else set())
        | (approved_second_five_ids() if args.approved_second_five else set())
        | (approved_third_ten_ids() if args.approved_third_ten else set())
        | (approved_fourth_eleven_ids() if args.approved_fourth_eleven else set()),
    )
    print("AVITO_FEED_TRANSITION_REVIEW", json.dumps(result, ensure_ascii=False), flush=True)
    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
