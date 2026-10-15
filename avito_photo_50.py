"""Select up to 50 DISTINCT in-stock Irkutsk parts with technically valid Rossko photos.

No auto-publication and no rights or product-matching claims. Output only to
a transient GitHub Actions artifact, never GitHub Pages or tracked files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from avito_irkutsk import load_fresh_price, select_rows
from avito_photo_check import approved_url, retrieve_image
from update_prices import load_config, normalize_key, read_photo_map, text

GROUPS = ("Рулевые рейки", "Тормозные диски")
# Previous photo sheet showed a diagram rather than a product photo.
# Visual review of the first 50-item contact sheet (2026-10-15):
# pure technical drawings and one suspicious mismatched component image.
KNOWN_DIAGRAMS = {
    ("blitz", "bs0332"), ("blitz", "bs0478"),
    ("alliednippon", "adc3216v"),
    ("blitz", "bs0164"), ("blitz", "bs0202"), ("blitz", "bs0212"),
    ("blitz", "bs0355"), ("blitz", "bs0360"),
    ("krauf", "hnq5129gq"),
}
COLUMNS = (
    "Группа", "Бренд", "Артикул", "Описание РОССКО", "Цена Авито",
    "Остаток РОССКО", "Срок поставки", "Город", "Адрес выдачи",
    "Применимость", "Каталожный номер",
    "Фото для проверки", "photo_status", "width", "height",
    "brand", "article", "approved", "pickup_confirmed",
    "condition_confirmed", "photo_urls", "fitment", "oem_number",
    "Комментарий",
)


def identity(r):
    return normalize_key(r["Бренд"]), normalize_key(r["Артикул"])


def photo_candidates(products, photo_map):
    grouped = {key: [] for key in GROUPS}
    for row in products:
        key = identity(row)
        if key in KNOWN_DIAGRAMS:
            continue
        link = photo_map.get("|".join(key), "")
        if not approved_url(link):
            continue
        item = dict(row)
        item["Фото для проверки"] = link
        grouped[row["Группа"]].append(item)
    for group in GROUPS:
        grouped[group].sort(key=lambda r: (-r["Остаток РОССКО"], normalize_key(r["Бренд"]), normalize_key(r["Артикул"])))
    return grouped


def validate_batch(items):
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda r: retrieve_image(r["Фото для проверки"]), items))
    return list(zip(items, results))


def get_valid(items, target, selected_ids, used_image_hashes):
    selected = []
    seen_url = set()
    for pos in range(0, len(items), 16):
        chunk = items[pos:pos+16]
        for item, data in validate_batch(chunk):
            img, status, w, h, digest = data
            key = identity(item)
            if status != "available_unverified" or img is None or not digest:
                continue
            if key in selected_ids or digest in used_image_hashes:
                continue
            url = item["Фото для проверки"]
            if url in seen_url:
                continue
            seen_url.add(url)
            selected_ids.add(key)
            used_image_hashes.add(digest)
            selected.append((item, img, str(w), str(h)))
            if len(selected) >= target:
                return selected
    return selected


def write_review(items, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "avito_irkutsk_50_with_photos_review.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        for row, img, w, h in items:
            record = dict(row)
            record.update({
                "photo_status": "available_unverified",
                "width": w, "height": h,
                "brand": row["Бренд"],
                "article": row["Артикул"],
                "approved": "", "pickup_confirmed": "",
                "condition_confirmed": "",
                "photo_urls": row["Фото для проверки"],
                "fitment": "", "oem_number": "",
                "Комментарий": "Файл фото открыт; соответствие артикулу, право использования, применимость и выдача не подтверждены",
            })
            writer.writerow({k:record.get(k,"") for k in COLUMNS})

    # Contact sheet is for MANUAL verification, not advertising material.
    cell_w, cell_h, cols = 270, 278, 5
    nrows = (len(items)+cols-1)//cols
    sheet = Image.new("RGB", (cols*cell_w, nrows*cell_h), "#f8fafc")
    paint = ImageDraw.Draw(sheet)
    for i, (row, img, _w, _h) in enumerate(items):
        x, y = (i%cols)*cell_w, (i//cols)*cell_h
        thumb = ImageOps.contain(img, (248, 238))
        sheet.paste(thumb, (x+(cell_w-thumb.width)//2, y+(242-thumb.height)//2))
        paint.text((x+8, y+243), f"{i+1}. {row['Бренд']} {row['Артикул']}"[:36], fill="#111827")
        paint.text((x+8, y+261), row["Группа"][:25], fill="#475569")
    sheet.save(out_dir / "avito_50_photo_contact_sheet.jpg", quality=88)

    # Small, publicly untracked identity manifest only; not prices or stock.
    with (out_dir / "avito_50_skus.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp, delimiter=";")
        writer.writerow(["brand", "article"])
        writer.writerows((r["Бренд"], r["Артикул"]) for r, *_ in items)
    return out_csv


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--confirm-irkutsk-source", action="store_true")
    p.add_argument("--out", default="output/avito_photo_50")
    args=p.parse_args()
    if not args.confirm_irkutsk_source:
        p.error("Подтвердите, что прайс относится к Иркутску")
    config_path=Path(args.config).resolve()
    config=load_config(config_path)
    photo_path=config_path.parent/text(config.get("drom",{}).get("photo_map_path") or "input/photos.csv")
    photo_map=read_photo_map(photo_path)
    if not photo_map:
        raise ValueError("Не найден список фотографий РОССКО")
    wb=load_fresh_price(config, config_path.parent, 2)
    try:
        products=select_rows(wb.active, config)
    finally:
        wb.close()
    grouped=photo_candidates(products, photo_map)
    print("WITH_IMAGE_LINKS_PER_GROUP", {k:len(v) for k,v in grouped.items()},flush=True)
    ids=set()
    hashes=set()
    selected={}
    for group in GROUPS:
        selected[group]=get_valid(grouped[group],25,ids,hashes)
    # If one category has fewer than 25 verified photo links, fill from the other.
    selected_flat=selected[GROUPS[0]]+selected[GROUPS[1]]
    if len(selected_flat)<50:
        missing=50-len(selected_flat)
        for group in GROUPS:
            remaining=[p for p in grouped[group] if identity(p) not in ids]
            extra=get_valid(remaining,missing,ids,hashes)
            selected[group].extend(extra)
            missing-=len(extra)
            if not missing:
                break
        selected_flat=selected[GROUPS[0]]+selected[GROUPS[1]]

    if len(selected_flat)<50:
        raise RuntimeError(f"Найдены только {len(selected_flat)} проверенных фотографий из 50 — не создаю файл на 50")
    out=write_review(selected_flat,config_path.parent/args.out)
    print("SELECTED_VALID_PHOTO_50", {k:len(v) for k,v in selected.items()}, flush=True)
    print("REVIEW_FILE",out,flush=True)
    print("Photos successfully decoded, but image/article match and rights NOT APPROVED.",flush=True)


if __name__=="__main__":
    main()
