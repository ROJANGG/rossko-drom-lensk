"""Read-only remaining-67 Avito supplier/OEM readiness audit.

Produces PRIVATE artifact only. Supplier's OEM column is raw candidate text,
not authenticated manufacturer OE evidence. NO publishing and NO unverified OEMs.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from avito_irkutsk import load_fresh_price, select_rows
from update_prices import get_cell, load_config, normalize_key, read_header_map, read_photo_map, text

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "input/avito_remaining_67_NOT_READY_FOR_UPLOAD.csv"
OUTPUT = ROOT / "output/avito_remaining67_supplier_audit"


def sku(brand, article):
    return normalize_key(brand) + "|" + normalize_key(article)


def read_manifest(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        if not {"brand", "article"} <= set(reader.fieldnames or []):
            raise ValueError("67-item manifest missing brand or article")
        records = list(reader)
    keys = [sku(r["brand"], r["article"]) for r in records]
    if len(records) != 67 or len(set(keys)) != 67 or any("|" == key or key.startswith("|") or key.endswith("|") for key in keys):
        raise ValueError("Require exactly 67 unique known supplier articles")
    return records


def raw_source_oem(row, headers):
    for col in ("OEМ Номер", "OEM Номер", "ОЕМ Номер", "OEM", "OEM-номер"):
        if col in headers:
            return text(get_cell(row, headers, col))
    return ""


def audit(records, product_map, source_map, photos):
    seen = set()
    out = []
    for rec in records:
        brand, article = rec["brand"], rec["article"]
        key = sku(brand, article)
        if key in seen:
            raise ValueError("Duplicate 67-article SKU")
        seen.add(key)
        p = product_map.get(key)
        raw = source_map.get(key, {})
        photo = photos.get(key, "")
        nom = raw.get("nomenclature", "")
        photo_matches = bool(nom and ("/" + nom.casefold() + "/") in photo.casefold())
        # Raw supplier candidates cannot replace documented original OEM.
        out.append({
            "brand":brand,
            "article":article,
            "category": p["Группа"] if p else "",
            "fresh_irkutsk_stock":p["Остаток РОССКО"] if p else 0,
            "fresh_avito_price_rub":p["Цена Авито"] if p else "",
            "supplier_raw_oem_candidate":raw.get("raw_oem", ""),
            "supplier_catalog_number":raw.get("catalog", ""),
            "supplier_nomenclature":nom,
            "photo_url":photo,
            "photo_source_nomenclature_match":"yes" if photo_matches else "no",
            "verified_manufacturer_oem":"",
            "oem_evidence_url":"",
            "approved_for_publication":"NO",
            "block_reason": "NOT_IN_FRESH_IRKUTSK_STOCK" if not p else (
                "PHOTO_NOMENCLATURE_MISMATCH" if not photo_matches else
                "MISSING_VERIFIED_OEM_EVIDENCE"
            )
        })
    return out


def main():
    records = read_manifest(INPUT)
    cfg = load_config(ROOT / "config.json")
    if cfg.get("rossko", {}).get("price_source") != "url":
        raise ValueError("Require fresh supplier URL, no stale local price fallback")
    book = load_fresh_price(cfg, ROOT, 2)
    try:
        headers = read_header_map(book.active)
        selected = select_rows(book.active, cfg)
        product_map = {sku(p["Бренд"],p["Артикул"]):p for p in selected}
        wanted = {sku(r["brand"],r["article"]) for r in records}
        source_map = {}
        for line in book.active.iter_rows(min_row=2):
            brand=text(get_cell(line,headers,"Бренд"))
            article=text(get_cell(line,headers,"Артикул"))
            key=sku(brand, article)
            if key in wanted and key not in source_map:
                source_map[key]={
                    "raw_oem":raw_source_oem(line,headers),
                    "catalog":text(get_cell(line,headers,"Каталожный номер")),
                    "nomenclature":text(get_cell(line,headers,"Номенклатура")),
                }
    finally:
        book.close()
    # A pinned SKU can disappear from a later supplier price. Report it as unavailable,
    # rather than crash or falsely declare it in stock. Never use stale data.
    missing_from_supplier = sorted(wanted - set(source_map))
    photos = read_photo_map(ROOT / text(cfg.get("drom", {}).get("photo_map_path") or "input/photos.csv"))
    rows = audit(records, product_map, source_map, photos)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT/"AVITO_REMAINING67_EVIDENCE_AUDIT.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer=csv.DictWriter(f, delimiter=";", fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(r["brand"] for r in rows)
    summary={
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "candidates":len(rows),
        "brands":dict(counts),
        "in_fresh_irkutsk_stock":sum(bool(r["fresh_irkutsk_stock"]) for r in rows),
        "absent_from_fresh_supplier_file":len(missing_from_supplier),
        "absent_articles":[r["article"] for r in records if sku(r["brand"],r["article"]) in missing_from_supplier],
        "raw_supplier_oem_nonempty":sum(bool(r["supplier_raw_oem_candidate"]) for r in rows),
        "photo_url_nonempty":sum(bool(r["photo_url"]) for r in rows),
        "photo_path_matches_supplier_nomenclature":sum(r["photo_source_nomenclature_match"]=="yes" for r in rows),
        "manufacturer_oem_evidence_in_manifest":0,
        "published":0,
        "state":"READ_ONLY_MISSING_VERIFIED_OEM_EVIDENCE",
    }
    (OUTPUT/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    print("AVITO_REMAINING67_SUPPLIER_AUDIT",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
