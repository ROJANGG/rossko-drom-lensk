"""Read-only manufacturer OEM research for unlisted Irkutsk brake discs.

NGN product pages are matched to exact SKU and manufacturer-labeled analogs.
Found numbers are review candidates, NOT automatic permission to publish.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ORIGINAL_MAKES = {
    "ACURA", "AUDI", "BMW", "BYD", "CHANGAN", "CHERY", "CHEVROLET",
    "CHRYSLER", "CITROEN", "DAEWOO", "DAIHATSU", "DODGE", "FAW",
    "FIAT", "FORD", "GEELY", "GREAT WALL", "HAVAL", "HONDA", "HYUNDAI",
    "INFINITI", "ISUZU", "JAC", "JEEP", "KIA", "LADA", "LAND ROVER",
    "LEXUS", "LIFAN", "MAZDA", "MERCEDES-BENZ", "MITSUBISHI",
    "NISSAN", "OPEL", "PEUGEOT", "PORSCHE", "RENAULT", "SEAT",
    "SKODA", "SUBARU", "SUZUKI", "TOYOTA", "VOLKSWAGEN", "VOLVO",
    "VW", "SAIC", "GAC", "HONGQI", "BAIC", "DATSUN", "TESLA",
}
FIELDS = ("brand", "article", "maker", "verified_oem_candidate",
          "manufacturer_exact_sku_page", "source_status", "needs_manual_review")


def parse_exact_ngn_oems(html, article):
    if not re.fullmatch(r"36[0-9]{4}", article):
        raise ValueError("Invalid NGN brake-disc SKU")
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    expected = f"36-{article[2:]}"
    if not heading or not re.search(r"\\bNGN\\s+" + re.escape(expected) + r"\\b",
                                     heading.get_text(" ", strip=True), re.I):
        return []
    tokens = list(soup.stripped_strings)
    result = []
    seen = set()
    for i, raw in enumerate(tokens):
        if raw.strip().upper() not in ORIGINAL_MAKES or i == 0:
            continue
        number = tokens[i-1].strip().upper()
        canonical = re.sub(r"[\\s.\\-/]+", "", number)
        if not re.fullmatch(r"[A-Z0-9]{6,24}", canonical) or not re.search(r"[0-9]", canonical):
            continue
        if canonical in seen or canonical == article:
            continue
        seen.add(canonical)
        result.append((raw.strip().upper(), canonical))
    return result


def research(record):
    brand, article = record["brand"], record["article"].upper().strip()
    if brand.casefold() != "ngn":
        return [dict(brand=brand, article=article, maker="", verified_oem_candidate="",
                     manufacturer_exact_sku_page="", source_status="NEEDS_MANUFACTURER_SOURCE",
                     needs_manual_review="yes")]
    if not re.fullmatch(r"36[0-9]{4}", article):
        return [dict(brand=brand, article=article, maker="", verified_oem_candidate="",
                     manufacturer_exact_sku_page="", source_status="INVALID_SKU",
                     needs_manual_review="yes")]
    url = f"https://ngn-parts.com/{article[:2]}-{article[2:]}.html"
    try:
        response = requests.get(url, timeout=(8,20), headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        evidence = parse_exact_ngn_oems(response.text, article)
        if not evidence:
            status = "NO_VERIFIABLE_ORIGINAL_OEM_ON_EXACT_PAGE"
            return [dict(brand=brand, article=article, maker="", verified_oem_candidate="",
                         manufacturer_exact_sku_page=url, source_status=status,
                         needs_manual_review="yes")]
        return [dict(brand=brand, article=article, maker=maker,
                     verified_oem_candidate=oem, manufacturer_exact_sku_page=url,
                     source_status="NGN_EXACT_SKU_MANUFACTURER_SOURCE",
                     needs_manual_review="yes") for maker,oem in evidence]
    except requests.RequestException as exc:
        return [dict(brand=brand, article=article, maker="", verified_oem_candidate="",
                     manufacturer_exact_sku_page=url, source_status="SOURCE_ERROR_"+type(exc).__name__,
                     needs_manual_review="yes")]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    args=ap.parse_args()
    with open(args.candidates, encoding="utf-8-sig",newline="") as f:
        candidates = list(csv.DictReader(f, delimiter=";"))
    if not candidates:
        raise ValueError("Empty candidate file")
    with ThreadPoolExecutor(max_workers=6) as pool:
        groups=list(pool.map(research,candidates))
    records=[row for group in groups for row in group]
    out=Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out/"manufacturer_oem_candidates_REVIEW.csv").open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f, fieldnames=FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(records)
    success={r["article"] for r in records if r["source_status"]=="NGN_EXACT_SKU_MANUFACTURER_SOURCE"}
    errors={r["article"] for r in records if r["source_status"].startswith("SOURCE_ERROR")}
    summary={
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "sku_total":len(candidates),
        "ngn_skus":sum(r["brand"].casefold()=="ngn" for r in candidates),
        "ngn_skus_with_manufacturer_oem_candidates":len(success),
        "cross_reference_rows":sum(r["source_status"]=="NGN_EXACT_SKU_MANUFACTURER_SOURCE" for r in records),
        "manufacturer_source_errors":len(errors),
        "other_brands_needing_sources":sum(r["brand"].casefold()!="ngn" for r in candidates),
        "published":0,
        "state":"MANUFACTURER_OEM_CANDIDATES_REVIEW_ONLY",
    }
    (out/"manufacturer_oem_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print("AVITO_REMAINING_OEM_RESEARCH",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
