#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find Rossko public product photos and write input/photos.csv.

The Drom exporter already reads input/photos.csv with columns:
brand;article;photo_url

This script uses the Rossko price list and the "Номенклатура" column to open
public Rossko card pages and extract direct imgs.rossko.ru links.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional
from urllib.parse import quote, unquote

import requests
from openpyxl import load_workbook

from update_prices import download_price_if_needed, load_config, normalize_key, text

REQUIRED_HEADERS = ["Номенклатура", "Бренд", "Артикул"]

# Rossko pages may contain both absolute URLs and protocol-relative URLs:
# https://imgs.rossko.ru/15/5A/NSII0012963910/1.jpg
# //imgs.rossko.ru/15/5A/NSII0012963910/1.jpg
DIRECT_IMG_RE = re.compile(
    r"(?:(?:https?:)?//)imgs\.rossko\.ru/[^\"'<>\s)]+?\.jpg",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PriceRow:
    brand: str
    article: str
    nomenclature: str

    @property
    def key(self) -> str:
        return f"{normalize_key(self.brand)}|{normalize_key(self.article)}"


def slugify(value: str) -> str:
    """Build the visible part of Rossko card URL."""
    raw = text(value).casefold()
    raw = re.sub(r"[^0-9a-zа-яё]+", "-", raw, flags=re.IGNORECASE)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return quote(raw)


def card_url(row: PriceRow) -> str:
    slug = "-".join(
        part for part in [slugify(row.brand), slugify(row.article), slugify(row.nomenclature)] if part
    )
    return f"https://rossko.ru/card/{slug}/"


def read_header_map(ws) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for col_idx, cell in enumerate(ws[1], start=1):
        name = text(cell.value)
        if name:
            result[name] = col_idx
    return result


def get_cell(row, header_map: Dict[str, int], header: str):
    idx = header_map.get(header)
    if not idx:
        return None
    return row[idx - 1].value


def iter_price_rows(path: Path) -> Iterable[PriceRow]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    header_map = read_header_map(ws)
    missing = [h for h in REQUIRED_HEADERS if h not in header_map]
    if missing:
        raise ValueError("В прайсе Росско не найдены колонки: " + ", ".join(missing))

    seen: set[str] = set()
    for row in ws.iter_rows(min_row=2):
        item = PriceRow(
            brand=text(get_cell(row, header_map, "Бренд")),
            article=text(get_cell(row, header_map, "Артикул")),
            nomenclature=text(get_cell(row, header_map, "Номенклатура")),
        )
        if not item.brand or not item.article or not item.nomenclature:
            continue
        if item.key in seen:
            continue
        seen.add(item.key)
        yield item


def load_existing_photos(path: Path) -> Dict[str, tuple[str, str, str]]:
    """Return key -> (brand, article, photo_url). Keeps manual rows."""
    result: Dict[str, tuple[str, str, str]] = {}
    if not path.exists():
        return result

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        for raw in reader:
            brand = text(raw.get("brand") or raw.get("Бренд"))
            article = text(raw.get("article") or raw.get("Артикул"))
            photo_url = text(raw.get("photo_url") or raw.get("Фотография") or raw.get("url"))
            if brand and article and photo_url:
                result[f"{normalize_key(brand)}|{normalize_key(article)}"] = (brand, article, photo_url)
    return result


def save_photos(path: Path, photos: Dict[str, tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(photos.values(), key=lambda x: (normalize_key(x[0]), normalize_key(x[1])))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["brand", "article", "photo_url"])
        writer.writerows(rows)


def decode_html(html: str) -> str:
    # Rossko pages may contain raw URLs, escaped URLs, protocol-relative URLs,
    # or percent-encoded nested image URLs.
    decoded = html.replace("\\/", "/")
    for _ in range(5):
        new_value = unquote(decoded)
        if new_value == decoded:
            break
        decoded = new_value
    return decoded


def clean_image_url(url: str) -> str:
    cleaned = text(url).replace("&amp;", "&").split("?")[0]
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    return cleaned


def image_exists(session: requests.Session, url: str, timeout: int) -> bool:
    try:
        response = session.get(
            url,
            timeout=timeout,
            stream=True,
            allow_redirects=True,
            headers={"Range": "bytes=0-1024", "Referer": "https://rossko.ru/"},
        )
        response.close()
    except requests.RequestException:
        return False
    if response.status_code not in (200, 206):
        return False
    content_type = response.headers.get("content-type", "").lower()
    return (not content_type) or content_type.startswith("image/")


def normalize_to_main_image(session: requests.Session, found_url: str, timeout: int, verify: bool) -> Optional[str]:
    cleaned = clean_image_url(found_url)
    base = re.sub(r"/\d+\.jpg$", "/", cleaned, flags=re.IGNORECASE)

    # Drom should receive the original Rossko image. Prefer 1.jpg, but test nearby
    # numbers because some cards expose another image first.
    candidates = [f"{base}{num}.jpg" for num in (1, 2, 3, 4, 5, 6, 7, 8, 9)]
    if cleaned not in candidates:
        candidates.insert(0, cleaned)

    for candidate in candidates:
        if not verify or image_exists(session, candidate, timeout):
            return candidate
    return None


def extract_image_candidates(html: str, row: PriceRow) -> list[str]:
    html = decode_html(html)
    nomenclature_key = f"/{row.nomenclature}/".casefold()
    matches: list[str] = []

    for match in DIRECT_IMG_RE.findall(html):
        clean = clean_image_url(match)
        if nomenclature_key in clean.casefold() and clean not in matches:
            matches.append(clean)

    return matches


def find_photo_url(session: requests.Session, row: PriceRow, timeout: int, verify_image: bool) -> Optional[str]:
    url = card_url(row)
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"HTTP ERROR: {row.brand} {row.article} {url} -> {exc}")
        return None
    if response.status_code >= 400:
        print(f"HTTP {response.status_code}: {row.brand} {row.article} {url}")
        return None

    for match in extract_image_candidates(response.text, row):
        normalized = normalize_to_main_image(session, match, timeout, verify_image)
        if normalized:
            return normalized
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update input/photos.csv from public Rossko cards")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--limit", type=int, default=50, help="How many new products to scan. 0 = scan all")
    parser.add_argument("--start", type=int, default=0, help="Skip first N products from price before scanning")
    parser.add_argument("--sleep", type=float, default=0.25, help="Pause between Rossko card requests")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    parser.add_argument("--force", action="store_true", help="Re-check products that already have photos")
    parser.add_argument("--no-verify-image", action="store_true", help="Do not make extra request to verify image URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    base_dir = config_path.resolve().parent
    config = load_config(config_path)

    price_path = download_price_if_needed(config, base_dir)
    photo_map_path = base_dir / text(config.get("drom", {}).get("photo_map_path") or "input/photos.csv")
    photos = load_existing_photos(photo_map_path)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    })

    scanned = 0
    found = 0
    skipped_existing = 0
    processed_after_start = 0
    verify_image = not args.no_verify_image

    for idx, row in enumerate(iter_price_rows(price_path)):
        if idx < args.start:
            continue
        processed_after_start += 1
        if not args.force and row.key in photos:
            skipped_existing += 1
            continue
        if args.limit and scanned >= args.limit:
            break

        scanned += 1
        photo_url = find_photo_url(session, row, args.timeout, verify_image)
        if photo_url:
            photos[row.key] = (row.brand, row.article, photo_url)
            found += 1
            print(f"FOUND {found}/{scanned}: {row.brand} {row.article} -> {photo_url}")
        else:
            print(f"MISS {scanned}: {row.brand} {row.article} {row.nomenclature}")

        if args.sleep > 0:
            time.sleep(args.sleep)

    save_photos(photo_map_path, photos)
    print("----")
    print(f"photos.csv: {photo_map_path}")
    print(f"existing skipped: {skipped_existing}")
    print(f"scanned: {scanned}")
    print(f"found: {found}")
    print(f"total photos in file: {len(photos)}")
    if processed_after_start == 0:
        print("В прайсе не найдено строк для обработки после --start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
