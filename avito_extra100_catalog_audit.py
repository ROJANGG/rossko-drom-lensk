"""Read-only independent cross-check of 100 new Avito candidates.

Confirms fresh Irkutsk availability and cross-references source photo URLs
against supplier item pages. Does not invent OEMs, approve images, or publish.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from avito_catalog_audit import get_matches
from avito_irkutsk import load_fresh_price, load_sku_whitelist, select_rows
from avito_feed import stable_id
from update_prices import get_cell, load_config, normalize_key, read_header_map, read_photo_map, text

ROOT = Path(__file__).resolve().parent
PINNED = ROOT / "input/avito_extra_100_pinned_REVIEW.csv"
OUT = ROOT / "output/avito_extra100_catalog_audit"
FIELDS = (
    "brand", "article", "group", "avito_id", "fresh_irkutsk_stock",
    "current_sell_price_rub", "supplier_page", "supplier_photo_url",
    "supplier_nomenclature", "photo_path_matches_nomenclature",
    "supplier_card_photo_status", "raw_supplier_OEM_not_verified",
    "verified_original_OEM", "verified_OEM_source",
    "condition_risk", "image_moderation_risk", "publication_status",
)

def classify_condition(brand, article):
    # Per manufacturer: Motorherz RB = remanufactured, not NEW.
    if normalize_key(brand) == "motorherz" and article.upper().endswith("RB"):
        return "RESTORED_NOT_NEW"
    return "NOT_INDEPENDENTLY_VERIFIED"

def image_risk(brand, article):
    if normalize_key(brand) == "marshall" and article.upper() in {"M2000532", "M2000583"}:
        return "TECHNICAL_DRAWING_ON_CONTACT_SHEET"
    if normalize_key(brand) in {"marshall", "ngn", "ctr"}:
        return "BRANDING_OR_TEXT_VISIBLE_REVIEW_AVITO_POLICY"
    return "MANUAL_PRODUCT_IMAGE_REVIEW_REQUIRED"

def analyze_record(item, card_result):
    key, brand, article, nomenclature, image, fitment, group, product = item
    page, status = card_result
    path_match = bool(nomenclature and ("/" + nomenclature.casefold() + "/") in image.casefold())
    matched = bool(path_match and status in {"exact_image_present_on_supplier_card", "same_nomenclature_photo_folder"})
    condition = classify_condition(brand, article)
    publication = "NEEDS_DOCUMENTED_ORIGINAL_OEM"
    if not product:
        publication = "NOT_IN_FRESH_IRKUTSK_STOCK"
    elif condition == "RESTORED_NOT_NEW":
        publication = "BLOCKED_RESTORED_NOT_NEW"
    elif not matched:
        publication = "CHECK_PHOTO_SUPPLIER_ARTICLE_LINK"
    return {
        "brand": brand, "article": article, "group": group,
        "avito_id": stable_id(group, brand, article),
        "fresh_irkutsk_stock": product["Остаток РОССКО"] if product else 0,
        "current_sell_price_rub": product["Цена Авито"] if product else "",
        "supplier_page": page, "supplier_photo_url": image,
        "supplier_nomenclature": nomenclature,
        "photo_path_matches_nomenclature": "yes" if path_match else "no",
        "supplier_card_photo_status": status,
        "raw_supplier_OEM_not_verified": "",
        "verified_original_OEM": "", "verified_OEM_source": "",
        "condition_risk": condition,
        "image_moderation_risk": image_risk(brand, article),
        "publication_status": publication,
    }

def main():
    pinned = load_sku_whitelist(PINNED)
    original = load_sku_whitelist(ROOT / "input/avito_pilot_articles.csv")
    if len(pinned) != 100 or pinned & original:
        raise RuntimeError("Expansion manifest must have 100 new non-pilot articles")
    cfg = load_config(ROOT / "config.json")
    photos = read_photo_map(ROOT / text(cfg.get("drom", {}).get("photo_map_path") or "input/photos.csv"))
    book = load_fresh_price(cfg, ROOT, 2)
    try:
        available = {normalize_key(p["Бренд"]) + "|" + normalize_key(p["Артикул"]):p for p in select_rows(book.active,cfg)}
        h = read_header_map(book.active)
        scan = {}
        for row in book.active.iter_rows(min_row=2):
            brand = text(get_cell(row,h,"Бренд"))
            article = text(get_cell(row,h,"Артикул"))
            key = normalize_key(brand)+"|"+normalize_key(article)
            if key in pinned and key not in scan:
                prod=available.get(key)
                group=prod["Группа"] if prod else ""
                # If temporarily sold out, infer group from source description ONLY for ID continuity.
                if not group:
                    from avito_irkutsk import category
                    group=category(text(get_cell(row,h,"Описание"))) or ""
                nomenclature=text(get_cell(row,h,"Номенклатура"))
                image=photos.get(key,"")
                fitment=text(get_cell(row,h,"Применимость"))
                scan[key]=(key,brand,article,nomenclature,image,fitment,group,prod)
    finally:
        book.close()
    if set(scan)!=pinned:
        raise RuntimeError("Selected articles absent from supplier file: "+str(sorted(pinned-set(scan))[:10]))
    tasks=list(scan.values())
    # Supplier page verification in an isolated, bounded parallel read-only audit.
    with ThreadPoolExecutor(max_workers=8) as pool:
        checks=list(pool.map(lambda t:get_matches(t[:7]),tasks))
    output = [analyze_record(t,check[1]) for t,check in zip(tasks,checks)]
    if len(output)!=100 or len({r["avito_id"] for r in output})!=100:
        raise RuntimeError("Unexpected ID count in 100 SKU audit")
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/"AVITO_EXTRA100_SUPPLIER_AUDIT.csv").open("w",encoding="utf-8-sig",newline="") as fh:
        writer=csv.DictWriter(fh,delimiter=";",fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    summary={
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "pinned_new_skus":len(output),
        "freshly_available":sum(bool(t[7]) for t in tasks),
        "photo_card_status_counts":dict(Counter(r["supplier_card_photo_status"] for r in output)),
        "publication_status_counts":dict(Counter(r["publication_status"] for r in output)),
        "photos_with_matching_supplier_nomenclature_path":sum(r["photo_path_matches_nomenclature"]=="yes" for r in output),
        "verified_original_oem":0,
        "published":0,
        "state":"AUDIT_ONLY_NO_PUBLICATION",
    }
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_EXTRA100_SUPPLIER_AUDIT",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
