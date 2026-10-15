"""Evidence report linking the 50 pilot photos to ROSSKO's own article cards.

Evidence from a supplier webpage is not independent OEM compatibility verification,
not permission to use images, and not proof of physical stock at pickup.
"""
from __future__ import annotations

import csv
import html
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from avito_irkutsk import load_fresh_price, load_sku_whitelist, select_rows
from update_prices import get_cell, load_config, normalize_key, read_header_map, read_photo_map, text
from update_photos_rossko import (
    PriceRow, card_url, clean_image_url, extract_image_candidates, get_thread_session
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output/avito_catalog_verification"
HEADERS = (
    "Бренд", "Артикул", "Категория", "Код номенклатуры РОССКО",
    "Карточка поставщика", "Фото из проекта", "Проверка изображения в карточке",
    "Применимость в прайсе", "Внешняя проверка применимости", "Права на фотографию",
    "Физическое состояние и выдача",
)

def get_matches(records):
    result = {}
    for record in records:
        key, brand, article, nom, src, fit, group = record
        row = PriceRow(brand=brand, article=article, nomenclature=nom)
        page = card_url(row)
        if not nom:
            return key, (page, "missing_supplier_nomenclature")
        try:
            resp = get_thread_session().get(page, timeout=(8, 18), allow_redirects=True)
            if resp.status_code != 200:
                return key, (page, f"supplier_page_http_{resp.status_code}")
            matches = set(clean_image_url(v) for v in extract_image_candidates(resp.text, row))
            photo = clean_image_url(src)
            if photo in matches:
                status = "exact_image_present_on_supplier_card"
            elif any(v.rsplit("/",1)[0] == photo.rsplit("/",1)[0] for v in matches):
                status = "same_nomenclature_photo_folder"
            elif matches:
                status = "card_has_other_photos_check_manually"
            else:
                status = "no_matching_photos_on_card"
            return key, (page, status)
        except Exception as ex:
            return key, (page, "supplier_page_error_"+type(ex).__name__)

def main():
    cfg = load_config(ROOT/"config.json")
    sku_whitelist = load_sku_whitelist(ROOT/"input/avito_pilot_articles.csv")
    if len(sku_whitelist) != 50:
        raise ValueError("Expected 50 SKU pairs")
    photos = read_photo_map(ROOT / cfg.get("drom", {}).get("photo_map_path", "input/photos.csv"))
    wb=load_fresh_price(cfg,ROOT,2)
    try:
        accepted=select_rows(wb.active,cfg)
        accept_keys={normalize_key(x["Бренд"])+"|"+normalize_key(x["Артикул"]):x for x in accepted}
        headers=read_header_map(wb.active)
        found={}
        for row in wb.active.iter_rows(min_row=2):
            brand=text(get_cell(row,headers,"Бренд"))
            article=text(get_cell(row,headers,"Артикул"))
            k=normalize_key(brand)+"|"+normalize_key(article)
            if k in sku_whitelist and k in accept_keys and k not in found:
                nom=text(get_cell(row,headers,"Номенклатура"))
                desc=accept_keys[k]
                found[k]=(k,brand,article,nom,photos.get(k,""),
                          desc.get("Применимость",""),desc["Группа"])
    finally:
        wb.close()
    if set(found)!=sku_whitelist:
        raise RuntimeError("Fresh Irkutsk stock does not contain all 50 pinned SKUs: "
                            +repr(sorted(sku_whitelist-set(found))))
    tasks=list(found.values())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=dict(pool.map(lambda t:get_matches([t]),tasks))
    OUT.mkdir(parents=True,exist_ok=True)
    count={}
    with (OUT/"photo_article_catalog_audit.csv").open("w",newline="",encoding="utf-8-sig") as out:
        writer=csv.writer(out,delimiter=";")
        writer.writerow(HEADERS)
        for k,brand,article,nom,src,fit,group in tasks:
            page, status=results[k]
            count[status]=count.get(status,0)+1
            writer.writerow([brand,article,group,nom,page,src,status,fit,
                             "не подтверждена независимо","не подтверждены",
                             "требует подтверждения продавца"])
    print("CATALOG_AUDIT_50",count,flush=True)

if __name__=="__main__":
    main()
