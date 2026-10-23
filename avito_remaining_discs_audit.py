"""Read-only audit of unlisted brake discs against the current live Avito feed.

Only read fresh Irkutsk ROSSKO stock; never publish without independent OEM
evidence and manual image/article review. Private supplier data is stored in
short-lived GitHub Actions artifacts, not committed to the repository.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageOps

from avito_feed import stable_id
from avito_irkutsk import load_fresh_price, select_rows
from avito_photo_50 import photo_candidates
from avito_photo_check import retrieve_image
from update_prices import (get_cell, load_config, normalize_key,
                           read_header_map, read_photo_map, text)

ROOT = Path(__file__).resolve().parent
FIELDS = (
    "brand", "article", "avito_id", "supplier_price_rub", "avito_price_rub",
    "irkutsk_stock", "delivery_days", "photo_url", "photo_status",
    "photo_width", "photo_height", "image_sha256", "supplier_nomenclature",
    "photo_path_matches_nomenclature", "supplier_oem_unverified",
    "verified_original_oem", "original_oem_source", "publication_status",
)


def current_ids(xml_path: Path) -> set[str]:
    root = ET.parse(xml_path).getroot()
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Wrong public Avito XML version")
    ids = [(ad.findtext("Id") or "").strip() for ad in root.findall("Ad")]
    if len(ids) < 145 or "" in ids or len(set(ids)) != len(ids):
        raise ValueError("Public Avito feed is smaller than 145 or has duplicate IDs")
    return set(ids)


def collect_candidates(workbook, config, photos, published):
    ws = workbook.active
    products = select_rows(ws, config)
    grouped = photo_candidates(products, photos)
    remaining = []
    for item in grouped["Тормозные диски"]:
        ident = stable_id("Тормозные диски", item["Бренд"], item["Артикул"])
        if ident not in published:
            remaining.append(item)
    headers = read_header_map(ws)
    wanted = {(normalize_key(x["Бренд"]), normalize_key(x["Артикул"]))
              for x in remaining}
    source = {}
    if wanted:
        for row in ws.iter_rows(min_row=2):
            k = (normalize_key(text(get_cell(row, headers, "Бренд"))),
                 normalize_key(text(get_cell(row, headers, "Артикул"))))
            if k in wanted and k not in source:
                source[k] = {
                    "price": text(get_cell(row, headers, "Цена, руб.")),
                    "nomenclature": text(get_cell(row, headers, "Номенклатура")),
                    "oem": text(get_cell(row, headers, "OEМ Номер")),
                }
    return remaining, source, len(grouped["Тормозные диски"])


def check_one(item):
    photo, status, w, h, digest = retrieve_image(item["Фото для проверки"])
    # A transient connection error is not evidence that the image is invalid.
    if status in {"ReadTimeout", "ConnectTimeout", "ConnectionError", "Timeout"}:
        photo, status, w, h, digest = retrieve_image(item["Фото для проверки"])
    return photo, status, w, h, digest


def run(preview: Path, output: Path):
    cfg = load_config(ROOT / "config.json")
    published = current_ids(preview)
    photos = read_photo_map(ROOT / text(cfg.get("drom", {}).get("photo_map_path") or "input/photos.csv"))
    if not photos:
        raise ValueError("Empty ROSSKO image source mapping")
    workbook = load_fresh_price(cfg, ROOT, 2)
    try:
        candidates, source, all_photo_linked = collect_candidates(workbook, cfg, photos, published)
    finally:
        workbook.close()
    if len({stable_id("Тормозные диски", x["Бренд"], x["Артикул"]) for x in candidates}) != len(candidates):
        raise ValueError("Duplicate candidate identity")
    if not candidates:
        raise RuntimeError("No new in-stock Irkutsk brake discs with supplier photo links")

    with ThreadPoolExecutor(max_workers=6) as pool:
        images = list(pool.map(check_one, candidates))
    hashes = defaultdict(set)
    for item, (_, status, _, _, digest) in zip(candidates, images):
        if digest:
            hashes[digest].add((normalize_key(item["Бренд"]), normalize_key(item["Артикул"])))

    output.mkdir(parents=True, exist_ok=True)
    rows = []
    tiles = []
    for item, (pic, status, w, h, digest) in zip(candidates, images):
        brand, article = item["Бренд"], item["Артикул"]
        k = normalize_key(brand), normalize_key(article)
        entry = source.get(k, {})
        nom = entry.get("nomenclature", "")
        path_match = bool(nom and ("/" + nom.casefold() + "/") in
                          item["Фото для проверки"].casefold())
        if digest and len(hashes[digest]) > 1:
            status = "duplicate_photo_needs_review"
        # Technical photo access is not proof of exact SKU or OEM matching.
        state = ("PHOTO_READY_OEM_UNVERIFIED"
                 if status == "available_unverified" and path_match
                 else "PHOTO_NEEDS_REVIEW")
        rows.append({
            "brand": brand,
            "article": article,
            "avito_id": stable_id("Тормозные диски", brand, article),
            "supplier_price_rub": entry.get("price", ""),
            "avito_price_rub": item["Цена Авито"],
            "irkutsk_stock": item["Остаток РОССКО"],
            "delivery_days": item["Срок поставки"],
            "photo_url": item["Фото для проверки"],
            "photo_status": status,
            "photo_width": w,
            "photo_height": h,
            "image_sha256": digest,
            "supplier_nomenclature": nom,
            "photo_path_matches_nomenclature": "yes" if path_match else "no",
            "supplier_oem_unverified": entry.get("oem", ""),
            "verified_original_oem": "",
            "original_oem_source": "",
            "publication_status": state,
        })
        if pic is not None:
            tiles.append((brand, article, pic))

    with (output / "remaining_discs_review.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, delimiter=";", fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    with (output / "new_sku_ids.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(("brand", "article", "avito_id"))
        for row in rows:
            w.writerow((row["brand"], row["article"], row["avito_id"]))

    # Contact sheets allow article-by-article visual review, not approval.
    for start in range(0, len(tiles), 40):
        chunk = tiles[start:start+40]
        cw, ch, cols = 260, 270, 5
        image = Image.new("RGB", (cols*cw, ((len(chunk)+cols-1)//cols)*ch), "#f8fafc")
        draw = ImageDraw.Draw(image)
        for i, (brand, article, photo) in enumerate(chunk):
            x, y = (i%cols)*cw, (i//cols)*ch
            thumb = ImageOps.contain(photo, (240, 225))
            image.paste(thumb, (x+(cw-thumb.width)//2, y+(225-thumb.height)//2))
            draw.text((x+7,y+232), f"{start+i+1}. {brand} {article}"[:36], fill="#111827")
        image.save(output / f"contact_sheet_{start//40+1:02d}.jpg", quality=85)

    summary = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "public_feed_ids_preserved": len(published),
        "all_irkutsk_discs_with_links_before_live_id_exclusion": all_photo_linked,
        "unlisted_irkutsk_discs_with_photo_links": len(rows),
        "downloadable_images": len(tiles),
        "exact_photo_nomenclature_path": sum(r["photo_path_matches_nomenclature"] == "yes" for r in rows),
        "photo_status": dict(Counter(r["photo_status"] for r in rows)),
        "brand_counts": dict(Counter(r["brand"] for r in rows)),
        "supplier_oem_fields_nonblank_unverified": sum(bool(r["supplier_oem_unverified"]) for r in rows),
        "verified_original_oem": 0,
        "published": 0,
        "state": "REVIEW_ONLY_NO_PUBLICATION",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("AVITO_REMAINING_DISCS_AUDIT", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-feed", required=True)
    parser.add_argument("--out", default="output/avito_remaining_discs_review")
    args = parser.parse_args()
    run(Path(args.public_feed), Path(args.out))
