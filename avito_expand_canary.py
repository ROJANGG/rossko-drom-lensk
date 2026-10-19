"""Append exactly two sourced CTR discs to the existing 50-SKU Avito XML.

Uses a NEW HTTPS ROSSKO stock snapshot; never copies prices from review files.
Fail closed on missing OEM evidence, wrong photo nomenclature, duplicate IDs,
missing pilot rows or unexpected product category. No upload occurs here.
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
from update_prices import get_cell, load_config, normalize_key, read_header_map, read_photo_map, text

CANARY = {("ctr", "gd0037"), ("ctr", "gd0053")}
GROUP = "Тормозные диски"


def key(brand, article):
    return normalize_key(brand), normalize_key(article)


def read_canary(csv_path: Path, evidence_path: Path):
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        if not {"brand", "article"} <= set(reader.fieldnames or []):
            raise ValueError("Canary manifest missing brand/article")
        rows = list(reader)
    actual = [key(r["brand"], r["article"]) for r in rows]
    if len(rows) != 2 or set(actual) != CANARY or len(set(actual)) != 2:
        raise ValueError("Canary manifest must be EXACTLY the 2 approved CTR SKUs")
    found = {}
    with evidence_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        if not {"brand", "article", "proposed_original_oem", "source", "verification_status"} <= set(reader.fieldnames or []):
            raise ValueError("Missing OEM manufacturer evidence CSV fields")
        for r in reader:
            k = key(r["brand"], r["article"])
            if k not in CANARY:
                continue
            code = text(r["proposed_original_oem"]).upper().replace("-", "")
            source = text(r["source"])
            if k in found or not re.fullmatch(r"[A-Z0-9]{5,32}", code):
                raise ValueError("Invalid/duplicated source OEM evidence")
            if source != f"https://ctr.co.ru/catalog/{r['article'].upper()}":
                raise ValueError("OEM evidence is not from exact manufacturer's SKU page")
            if r["verification_status"] != "MANUFACTURER_OEM_CATALOG_REVIEW":
                raise ValueError("Unexpected OEM evidence provenance status")
            found[k] = code
    if set(found) != CANARY:
        raise ValueError("Canary cannot proceed without both documented OEMs")
    return found


def extend_xml(pilot_xml: bytes, approved: dict, products: list[dict],
               photos: dict[str, str], nomenclatures: dict, *, require_two: bool = False) -> tuple[bytes, dict]:
    root = ET.fromstring(pilot_xml)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Not a valid pilot XML v3")
    previous_ids = [node.findtext("Id") for node in root.findall("Ad")]
    if len(previous_ids) < 40 or len(set(previous_ids)) != len(previous_ids):
        raise ValueError("Missing or repeated base pilot IDs")
    all_products = {key(p["Бренд"], p["Артикул"]):p for p in products}
    extras = []
    missing = []
    for part_key in sorted(CANARY):
        p = all_products.get(part_key)
        if p is None:
            missing.append("|".join(part_key))
            continue
        if p["Группа"] != GROUP or int(p["Остаток РОССКО"]) <= 0 or int(p["Цена Авито"]) <= 0:
            raise ValueError("Incorrect category, price or stock for extra CTR SKU")
        lookup = "|".join(part_key)
        nom = nomenclatures.get(part_key, "")
        link = photos.get(lookup, "")
        if not nom or not approved_url(link) or ("/" + nom.casefold() + "/") not in link.casefold():
            raise ValueError("Unverified supplier nomenclature/photo for " + lookup)
        extras.append({
            "Группа": GROUP, "Бренд": p["Бренд"], "Артикул": p["Артикул"],
            "Цена ₽": p["Цена Авито"], "Остаток": p["Остаток РОССКО"],
            "Фото URL": link, "Применимость РОССКО": "",
        })
    if require_two and len(extras) != 2:
        raise ValueError("Initial canary rollout requires both locally available SKUs")
    override = {"|".join(k):v for k,v in approved.items()}
    added = ET.fromstring(build_xml(extras, verified_extra_oems=override)) if extras else ET.Element("Ads")
    ids = set(previous_ids)
    for ad in added.findall("Ad"):
        ident = ad.findtext("Id")
        if ident in ids:
            raise ValueError("Canary would duplicate an existing listing ID")
        ids.add(ident)
        root.append(ad)
    ET.indent(root, space="  ")
    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return out, {"base": len(previous_ids), "new_in_stock":len(extras), "missing_new":missing,
                 "total":len(root.findall("Ad")), "extra_ids":[ad.findtext("Id") for ad in added.findall("Ad")]}


def approved_canary_ids(approved_file: Path) -> set[str]:
    with approved_file.open(encoding="utf-8-sig", newline="") as handle:
        r=csv.DictReader(handle,delimiter=";")
        if not {"brand","article"} <= set(r.fieldnames or []):
            raise ValueError("Canary ID file missing fields")
        rows=list(r)
    if len(rows)!=2 or {key(x["brand"],x["article"]) for x in rows} != CANARY:
        raise ValueError("Unexpected extra canary IDs")
    return {stable_id(GROUP,r["brand"],r["article"]) for r in rows}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--pilot-xml", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--config", default="config.json")
    p.add_argument("--approved-new", default="input/avito_canary_2_new.csv")
    p.add_argument("--evidence", default="input/avito_ctr_33_oem_REVIEW.csv")
    p.add_argument("--require-two",action="store_true")
    args=p.parse_args()
    cfg_path=Path(args.config).resolve()
    base=cfg_path.parent
    config=load_config(cfg_path)
    if config.get("rossko",{}).get("price_source")!="url":
        raise ValueError("Canary production requires live Rossko HTTPS price")
    approved=read_canary(base/args.approved_new, base/args.evidence)
    photos=read_photo_map(base / text(config.get("drom",{}).get("photo_map_path") or "input/photos.csv"))
    book=load_fresh_price(config,base,2)
    try:
        products=select_rows(book.active,config)
        headers=read_header_map(book.active)
        codes={}
        for r in book.active.iter_rows(min_row=2):
            k=key(text(get_cell(r,headers,"Бренд")),text(get_cell(r,headers,"Артикул")))
            if k in CANARY and k not in codes:
                codes[k]=text(get_cell(r,headers,"Номенклатура"))
    finally:
        book.close()
    blob, audit=extend_xml(Path(args.pilot_xml).read_bytes(),approved,products,photos,codes,
                           require_two=args.require_two)
    dest=Path(args.out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes(blob)
    print("AVITO_2_SKU_CANARY",json.dumps({"generated_at_utc":datetime.now(timezone.utc).isoformat(),**audit},
                                            ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
