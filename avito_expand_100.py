"""Prepare up to 100 NEW Avito candidate SKUs without touching the live XML.

Reads a fresh ROSSKO price for Irkutsk, excludes every original pilot SKU
(including temporarily out-of-stock ones), checks source JPEG/PNG/WEBP bytes
and outputs a private review artifact. Never invent an OEM or auto-publish.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from avito_feed import stable_id
from avito_irkutsk import load_fresh_price, load_sku_whitelist, select_rows
from avito_photo_50 import GROUPS, identity, photo_candidates, get_valid
from update_prices import load_config, normalize_key, read_photo_map, text

PER_CATEGORY = 50
TOTAL = 100
COLUMNS = (
    "Группа", "Бренд", "Артикул", "ID Авито", "Цена Авито ₽",
    "Остаток РОССКО", "Фото URL", "Применимость поставщика",
    "Номер детали OEM", "Источник подтверждения OEM",
    "Фото соответствует артикулу?", "Статус",
)


def new_candidates(products: list[dict], photos: dict[str, str],
                   excluded: set[str]) -> dict[str, list[dict]]:
    """Never reuse any of the original 50 brand/article identities or URLs."""
    candidates = photo_candidates(products, photos)
    old_urls = {url for key, url in photos.items() if key in excluded and url}
    result = {}
    for group in GROUPS:
        result[group] = [
            row for row in candidates[group]
            if "|".join(identity(row)) not in excluded
            and row["Фото для проверки"] not in old_urls
        ]
    return result


def prepare_selection(groups: dict[str, list[dict]], photo_validator=get_valid) -> dict:
    selected_ids: set[tuple[str, str]] = set()
    image_digests: set[str] = set()
    result = {}
    for group in GROUPS:
        result[group] = photo_validator(groups[group], PER_CATEGORY, selected_ids, image_digests)
    # Aim for a balanced 50/50 split, but fill from another category if
    # its source catalogue has fewer than fifty acceptable images.
    deficit = TOTAL - sum(len(x) for x in result.values())
    if deficit:
        for group in GROUPS:
            remaining = [p for p in groups[group] if identity(p) not in selected_ids]
            additional = photo_validator(remaining, deficit, selected_ids, image_digests)
            result[group].extend(additional)
            deficit -= len(additional)
            if deficit <= 0:
                break
    return result


def review_records(selected: dict, excluded: set[str]) -> list[dict]:
    rows = []
    identities = set()
    for group in GROUPS:
        for product, _photo, _w, _h in selected.get(group, []):
            key = "|".join(identity(product))
            if key in excluded or key in identities:
                raise ValueError("Duplicate or previously published SKU in expansion: " + key)
            identities.add(key)
            rows.append({
                "Группа": group,
                "Бренд": product["Бренд"],
                "Артикул": product["Артикул"],
                "ID Авито": stable_id(group, product["Бренд"], product["Артикул"]),
                "Цена Авито ₽": product["Цена Авито"],
                "Остаток РОССКО": product["Остаток РОССКО"],
                "Фото URL": product["Фото для проверки"],
                "Применимость поставщика": product.get("Применимость", ""),
                "Номер детали OEM": "",  # Original OEM must be independently verified.
                "Источник подтверждения OEM": "",
                "Фото соответствует артикулу?": "",
                "Статус": "Кандидат — подтвердить OEM и соответствие фото; НЕ ПУБЛИКОВАТЬ",
            })
    if len(rows) > TOTAL or len({r["ID Авито"] for r in rows}) != len(rows):
        raise ValueError("Candidate count or permanent IDs invalid")
    return rows


def write_review(selected: dict, excluded: set[str], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    records = review_records(selected, excluded)
    report = out / "AVITO_EXTRA_100_REVIEW_NOT_FOR_UPLOAD.csv"
    with report.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, delimiter=";", fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    flattened = [(grp, prod, pic) for grp in GROUPS
                 for prod, pic, _w, _h in selected.get(grp, [])]
    if flattened:
        tile_w, tile_h, cols = 260, 270, 5
        grid = Image.new("RGB", (cols * tile_w, ((len(flattened) + cols - 1) // cols) * tile_h), "#f8fafc")
        draw = ImageDraw.Draw(grid)
        for index, (group, row, photo) in enumerate(flattened):
            x, y = (index % cols) * tile_w, (index // cols) * tile_h
            thumb = ImageOps.contain(photo, (235, 220))
            grid.paste(thumb, (x + (tile_w - thumb.width)//2, y + (225 - thumb.height)//2))
            draw.text((x + 6, y + 226), (row["Бренд"] + " " + row["Артикул"])[:35], fill="#111827")
            draw.text((x + 6, y + 245), group[:25], fill="#333333")
        grid.save(out / "AVITO_EXTRA_100_PHOTO_REVIEW.jpg", quality=82)

    counts = {group: len(selected.get(group, [])) for group in GROUPS}
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "fresh Rossko Irkutsk XLSX, quantity > 0, delivery zero",
        "requested_extra": TOTAL,
        "photo_technically_valid": len(records),
        "counts_by_group": counts,
        "excluded_original_pilot_skus": len(excluded),
        "verified_oem_for_new": 0,
        "ready_for_avito_publication": 0,
        "need_human_approval": "exact image/article match, sourced original OEM",
        "state": "REVIEW_ONLY_NEVER_AUTO_PUBLISH",
    }
    (out / "summary.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("AVITO_EXTRA_100_CANDIDATES", json.dumps(metadata, ensure_ascii=False), flush=True)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--existing", default="input/avito_pilot_articles.csv")
    parser.add_argument("--out", default="output/avito_extra_100_review")
    args = parser.parse_args()
    cfg_path = Path(args.config).resolve()
    base = cfg_path.parent
    config = load_config(cfg_path)
    excluded = load_sku_whitelist(base / args.existing)
    if len(excluded) != 50:
        raise ValueError("Unexpected original pilot manifest, refusing to choose extra SKUs")
    photos = read_photo_map(base / text(config.get("drom", {}).get("photo_map_path") or "input/photos.csv"))
    if not photos:
        raise ValueError("No supplier picture mapping available")
    book = load_fresh_price(config, base, 2)
    try:
        products = select_rows(book.active, config)
    finally:
        book.close()
    groups = new_candidates(products, photos, excluded)
    print("NEW_CANDIDATES_WITH_IMAGE_URL", {g: len(groups[g]) for g in GROUPS}, flush=True)
    selected = prepare_selection(groups)
    write_review(selected, excluded, base / args.out)


if __name__ == "__main__":
    main()
