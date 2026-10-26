"""Append 53 PINNED OEM NGN brake discs using one fresh Irkutsk ROSSKO XLSX.

This is a fail-closed generator; publication happens ONLY in main's guarded
Avito workflow after mirroring images and transition validation.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_irkutsk import load_fresh_price, select_rows
from avito_photo_check import approved_url
from avito_xml_v3_diagnostic import build_xml
from avito_remaining_discs_oem_research import ORIGINAL_MAKES
from update_prices import (get_cell, load_config, normalize_key,
                           read_header_map, read_photo_map, text)

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "input/avito_ngn53_original_oem_pinned.csv"
CATEGORY = "Тормозные диски"
MIN_BASE_ADS = 140
EXPECTED = 53


def pinned_oem_evidence(path=MANIFEST):
    with Path(path).open(encoding="utf-8-sig", newline="") as fp:
        raw = list(csv.DictReader(fp, delimiter=";"))
    if len(raw) != EXPECTED:
        raise ValueError("Expected exactly 53 pinned original OEM SKUs")
    evidence = {}
    for record in raw:
        if set(record) != {"article", "original_oem", "original_maker"}:
            raise ValueError("Pinned original OEM evidence has unexpected columns")
        article = record["article"].strip().upper()
        oem = record["original_oem"].strip().upper()
        maker = record["original_maker"].strip().upper()
        if (not re.fullmatch(r"36[0-9]{4}", article)
            or not re.fullmatch(r"[A-Z0-9]{6,24}", oem)
            or maker not in ORIGINAL_MAKES
            or article in evidence or oem == article):
            raise ValueError("Invalid/duplicate manufacturer original OEM for " + article)
        evidence[article] = {"oem": oem, "maker": maker,
                             "source": f"https://ngn-parts.com/36-{article[2:]}.html"}
    return evidence


def assemble(previous, products, photo_map, nomenclatures, evidence, *, max_missing=2):
    root = ET.fromstring(previous)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Invalid Avito v3 baseline")
    old = root.findall("Ad")
    ids = {(ad.findtext("Id") or "").strip() for ad in old}
    if len(old) < MIN_BASE_ADS or "" in ids or len(ids) != len(old):
        raise ValueError("Prior catalog unexpectedly missing or duplicate IDs")

    allowed = {("ngn", a) for a in evidence}
    products_by_key = {(normalize_key(p["Бренд"]), normalize_key(p["Артикул"])):p
                       for p in products if
                       (normalize_key(p["Бренд"]), normalize_key(p["Артикул"])) in allowed}
    missing = sorted(allowed - set(products_by_key))
    if len(missing) > max_missing:
        raise ValueError("Too many new NGN disc SKUs out of Irkutsk stock " + str(missing))

    photos = {}
    additions = []
    map_oem = {}
    for brand, article in sorted(products_by_key):
        p = products_by_key[brand, article]
        avito_id = stable_id(CATEGORY, p["Бренд"], p["Артикул"])
        url = photo_map.get(brand+"|"+article, "")
        nomen = nomenclatures.get((brand, article), "")
        if avito_id in ids:
            raise ValueError("Already-existing Avito ID in NGN additions: " + avito_id)
        if (p["Группа"] != CATEGORY or int(p["Остаток РОССКО"]) <= 0
            or int(p["Цена Авито"]) <= 0 or p["Срок поставки"] != 0):
            raise ValueError("Invalid current stock/price/delivery: " + article)
        if not approved_url(url) or not nomen or "/"+nomen.casefold()+"/" not in url.casefold():
            raise ValueError("Wrong manufacturer photo nomenclature for " + article)
        additions.append({"Группа":CATEGORY, "Бренд":p["Бренд"], "Артикул":p["Артикул"],
                          "Цена ₽":p["Цена Авито"], "Остаток":p["Остаток РОССКО"],
                          "Фото URL":url})
        photos[article] = url
        map_oem[brand+"|"+article] = evidence[article]["oem"]

    generated = ET.fromstring(build_xml(additions, verified_extra_oems=map_oem))
    for ad in generated.findall("Ad"):
        item_id = (ad.findtext("Id") or "").strip()
        if not item_id or item_id in ids:
            raise ValueError("Duplicate or blank new Avito ID")
        ids.add(item_id)
        root.append(ad)
    if len(ids) != len(old)+len(additions):
        raise ValueError("NGN 53 XML count mismatch")
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), {
        "prior":len(old), "added":len(additions), "candidate_total":len(ids),
        "missing_local_stock":["|".join(k) for k in missing],
        "source_type":"fixed exact-SKU manufacturer original OEM catalog evidence",
        "added_ids":[a.findtext("Id") for a in generated.findall("Ad")],
        "source_photo_urls_by_article":photos,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-xml", required=True)
    ap.add_argument("--out", default="output/avito_ngn53_release")
    ap.add_argument("--allow-small-stock-removals", action="store_true")
    a=ap.parse_args()
    cfg=load_config(ROOT/"config.json")
    if cfg.get("rossko",{}).get("price_source") != "url":
        raise ValueError("Must use fresh ROSSKO HTTPS XLSX")
    evidence = pinned_oem_evidence()
    photo_map=read_photo_map(ROOT / text(cfg.get("drom",{}).get("photo_map_path") or "input/photos.csv"))
    book=load_fresh_price(cfg, ROOT, 2)
    try:
        available=select_rows(book.active,cfg)
        headers=read_header_map(book.active)
        nomenclatures={}
        for row in book.active.iter_rows(min_row=2):
            brand=normalize_key(text(get_cell(row,headers,"Бренд")))
            article=normalize_key(text(get_cell(row,headers,"Артикул")))
            if brand=="ngn" and article.upper() in evidence and (brand,article) not in nomenclatures:
                nomenclatures[brand,article]=text(get_cell(row,headers,"Номенклатура"))
    finally:
        book.close()
    xml, summary=assemble(Path(a.base_xml).read_bytes(),available,photo_map,nomenclatures,evidence,
                          max_missing=2 if a.allow_small_stock_removals else 0)
    out=ROOT/a.out
    out.mkdir(parents=True,exist_ok=True)
    dest=out/"AVITO_NGN53_LIVE_CANDIDATE.xml"
    dest.write_bytes(xml)
    # Never print private price / supplier source URLs in CI logs.
    summary.pop("source_photo_urls_by_article", None)
    summary.update(checked_utc=datetime.now(timezone.utc).isoformat(),
                   state="CONTROLLED_CANDIDATE_NOT_PUBLISHED")
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_NGN53_PREFLIGHT", json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
