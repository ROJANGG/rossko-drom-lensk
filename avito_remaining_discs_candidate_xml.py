"""Build a REVIEW-ONLY Avito XML candidate without editing the live feed.

Only NGN discs with verified exact-SKU manufacturer OEM evidence and working
article-aligned source photos are eligible. Supplier stock is the current
audit snapshot from the SAME GitHub Actions run. No publication or Git push.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_xml_v3_diagnostic import build_xml
from avito_remaining_discs_oem_research import ORIGINAL_MAKES
from update_prices import normalize_key

GROUP = "Тормозные диски"
FIELDS = ("brand", "article", "avito_id", "chosen_original_oem",
          "original_maker", "manufacturer_source", "avito_price_rub",
          "irkutsk_stock", "photo_url", "status")


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=";"))


def eligible_by_article(stock_rows, oem_rows, live_ids, reserved_skus):
    """Only evidence-backed current-stock SKUs. Never reuse a reserved ID."""
    oems = defaultdict(list)
    for proof in oem_rows:
        if proof["source_status"] != "NGN_EXACT_SKU_MANUFACTURER_SOURCE":
            continue
        brand = normalize_key(proof["brand"])
        article = normalize_key(proof["article"])
        maker = proof["maker"].strip().upper()
        oem = proof["verified_oem_candidate"].strip().upper()
        source = proof["manufacturer_exact_sku_page"].strip()
        if brand != "ngn" or not re.fullmatch(r"36[0-9]{4}", article):
            continue
        if maker not in ORIGINAL_MAKES:
            continue
        if source != f"https://ngn-parts.com/36-{article[2:]}.html":
            continue
        if not re.fullmatch(r"[A-Z0-9]{6,24}", oem) or not re.search(r"[0-9]", oem):
            continue
        oems[(brand, article)].append((maker, oem, source))

    admitted = []
    audit = []
    seen = set()
    for row in stock_rows:
        brand = normalize_key(row["brand"])
        article = normalize_key(row["article"])
        key = (brand, article)
        if key in seen:
            raise ValueError("Repeated stock SKU: " + repr(key))
        seen.add(key)
        ident = stable_id(GROUP, row["brand"], row["article"])
        reason = ""
        if ident in live_ids or key in reserved_skus:
            reason = "OLD_OR_RESERVED_SKU"
        elif brand != "ngn" or not re.fullmatch(r"36[0-9]{4}", article):
            reason = "NOT_NGN_WITH_EXACT_SKU_EVIDENCE"
        elif row["photo_status"] != "available_unverified":
            reason = "NO_USABLE_PRODUCT_PHOTO"
        elif row["photo_path_matches_nomenclature"] != "yes":
            reason = "PHOTO_NOMENCLATURE_MISMATCH"
        elif not oems[key]:
            reason = "MISSING_ORIGINAL_MANUFACTURER_OEM"
        elif not row["image_sha256"] or len(row["image_sha256"]) != 64:
            reason = "MISSING_IMAGE_CHECKSUM"
        elif not row["photo_url"].startswith("https://imgs.rossko.ru/"):
            reason = "UNTRUSTED_SUPPLIER_PHOTO_URL"
        elif not row["irkutsk_stock"].isdigit() or int(row["irkutsk_stock"]) <= 0:
            reason = "OUT_OF_STOCK"
        elif not row["avito_price_rub"].isdigit() or int(row["avito_price_rub"]) <= 0:
            reason = "INVALID_PRICE"
        elif row["delivery_days"] != "0":
            reason = "NOT_IMMEDIATE_IRKUTSK_STOCK"
        if reason:
            audit.append({"brand":row["brand"], "article":row["article"],
                          "avito_id":ident, "chosen_original_oem":"",
                          "original_maker":"", "manufacturer_source":"",
                          "avito_price_rub":row["avito_price_rub"],
                          "irkutsk_stock":row["irkutsk_stock"],
                          "photo_url":row["photo_url"], "status":reason})
            continue
        # Only use an original-vehicle-maker number from the exact NGN SKU page.
        # Choosing the first source-ordered OEM is a deterministic draft choice,
        # not fitment approval; complete source evidence remains in the CSV.
        maker, oem, source = oems[key][0]
        approved = {"Группа":GROUP, "Бренд":row["brand"], "Артикул":row["article"],
                    "Цена ₽":row["avito_price_rub"], "Остаток":row["irkutsk_stock"],
                    "Фото URL":row["photo_url"]}
        admitted.append((approved, oem))
        audit.append({"brand":row["brand"], "article":row["article"],
                      "avito_id":ident, "chosen_original_oem":oem,
                      "original_maker":maker, "manufacturer_source":source,
                      "avito_price_rub":row["avito_price_rub"],
                      "irkutsk_stock":row["irkutsk_stock"],
                      "photo_url":row["photo_url"],
                      "status":"XML_DRAFT_OEM_FITMENT_AND_CDN_REVIEW_REQUIRED"})
    return admitted, audit


def build_review_xml(live_bytes: bytes, stock_rows, oem_rows, reserved_skus):
    root = ET.fromstring(live_bytes)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Invalid prior Avito feed")
    live_ids = [x.findtext("Id") for x in root.findall("Ad")]
    if len(live_ids) < 140:
        raise ValueError("Unexpected feed shrink below 140 listings")
    if any(not x for x in live_ids) or len(set(live_ids)) != len(live_ids):
        raise ValueError("Duplicate or missing existing Avito ID")
    selected, audit = eligible_by_article(stock_rows, oem_rows, set(live_ids), reserved_skus)
    # No point generating a ready-looking feed when nothing is sourced.
    if not selected:
        raise RuntimeError("No new evidence-backed items to stage")
    rows = [row for row, _ in selected]
    oems = {normalize_key(row["Бренд"])+"|"+normalize_key(row["Артикул"]):oem
            for row,oem in selected}
    additions = ET.fromstring(build_xml(rows, verified_extra_oems=oems))
    ids = set(live_ids)
    for ad in additions.findall("Ad"):
        ident=ad.findtext("Id")
        if ident in ids or not ident:
            raise ValueError("Duplicate or missing new listing ID")
        ids.add(ident)
        root.append(ad)
    if len(root.findall("Ad")) != len(live_ids) + len(selected):
        raise ValueError("XML candidate count mismatch")
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), audit, len(live_ids), len(selected)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--public-feed", required=True)
    parser.add_argument("--stock-review", required=True)
    parser.add_argument("--oem-review", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pilot-pins", default="input/avito_pilot_articles.csv")
    parser.add_argument("--extra-pins", default="input/avito_extra_100_pinned_REVIEW.csv")
    args=parser.parse_args()
    reserved = set()
    for path in (args.pilot_pins, args.extra_pins):
        for row in read_csv(Path(path)):
            reserved.add((normalize_key(row["brand"]), normalize_key(row["article"])))
    if len(reserved) != 150:
        raise ValueError("Unexpected original 150 reserved SKUs")
    result,audit,existing,new=build_review_xml(
        Path(args.public_feed).read_bytes(), read_csv(Path(args.stock_review)),
        read_csv(Path(args.oem_review)), reserved
    )
    out=Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out/"AVITO_ADDITIONS_REVIEW_NOT_LIVE.xml").write_bytes(result)
    with (out/"addition_decisions.csv").open("w", encoding="utf-8-sig", newline="") as fp:
        writer=csv.DictWriter(fp, delimiter=";", fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(audit)
    summary={"checked_at":datetime.now(timezone.utc).isoformat(),
             "existing_live_ads_unchanged":existing,
             "new_evidence_backed_ngn_drafts":new,
             "candidate_xml_ads":existing+new,
             "not_ready_due_to":dict(Counter(x["status"] for x in audit
                                              if x["status"] != "XML_DRAFT_OEM_FITMENT_AND_CDN_REVIEW_REQUIRED")),
             "photos":"supplier URLs only; mirror to trusted CDN before any live release",
             "oem":"exact manufacturer cross candidate; compatibility/manual check outstanding",
             "publication":"NEVER - REVIEW XML IS NOT LIVE"}
    (out/"addition_summary.json").write_text(json.dumps(summary, ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_ADDITIONS_REVIEW",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
