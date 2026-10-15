"""Validate proposed Rossko photo URLs for a review-only Avito pilot.

No photo is automatically approved for publication. Results are transient
GitHub Actions artifacts; never commit downloaded photos or supplier data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

MAX_BYTES = 6_000_000
ALLOWED_HOSTS = {"imgs.rossko.ru"}
HEADERS = {"User-Agent": "rossko-avito-photo-validator/1.0"}
OUT_FIELDS = ("Группа", "Бренд", "Артикул", "Фото для проверки", "photo_status",
              "width", "height", "sha256", "manual_review_required")


def approved_url(url: str) -> bool:
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return False
    return (u.scheme == "https" and u.hostname in ALLOWED_HOSTS
            and u.port in (None, 443) and u.username is None and u.password is None)


def retrieve_image(url: str):
    if not approved_url(url):
        return None, "blocked_url", "", "", ""
    try:
        with requests.get(url, stream=True, timeout=(8, 15), headers=HEADERS,
                          allow_redirects=False) as response:
            if response.status_code != 200:
                return None, f"http_{response.status_code}", "", "", ""
            # ROSSKO can serve image bytes with a non-image Content-Type.
            # Pillow must decode and validate the actual bytes instead.
            raw = bytearray()
            for block in response.iter_content(chunk_size=65536):
                raw.extend(block)
                if len(raw) > MAX_BYTES:
                    return None, "image_too_large", "", "", ""
        digest = hashlib.sha256(raw).hexdigest()
        pic = Image.open(io.BytesIO(raw))
        pic.load()
        if (pic.format or "").upper() not in {"JPEG", "PNG", "WEBP"}:
            return None, "unexpected_image_format", str(pic.width), str(pic.height), ""
        if pic.width < 180 or pic.height < 180:
            return None, "too_small", str(pic.width), str(pic.height), ""
        return pic.convert("RGB"), "available_unverified", str(pic.width), str(pic.height), digest
    except (requests.RequestException, UnidentifiedImageError, OSError, ValueError) as exc:
        return None, type(exc).__name__, "", "", ""


def scan(csv_path: Path, out_dir: Path):
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        required = {"Группа", "Бренд", "Артикул", "Фото для проверки"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("Missing required review CSV columns")
        items = list(reader)
    out_dir.mkdir(parents=True, exist_ok=True)
    urls = sorted({r["Фото для проверки"].strip() for r in items if r["Фото для проверки"].strip()})

    def check(url):
        if not approved_url(url):
            return url, (None, "blocked_url", "", "", "")
        return url, retrieve_image(url)

    with ThreadPoolExecutor(max_workers=3) as pool:
        found = dict(pool.map(check, urls))

    digest_to_articles = {}
    for entry in items:
        url = entry["Фото для проверки"].strip()
        result = found.get(url)
        if result and result[4]:
            digest_to_articles.setdefault(result[4], set()).add(
                (entry["Бренд"], entry["Артикул"]))

    report = []
    tiles = []
    for row in items:
        url = row["Фото для проверки"].strip()
        pic, status, width, height, digest = found.get(url, (None, "no_photo", "", "", ""))
        if digest and len(digest_to_articles.get(digest, [])) > 1:
            status = "duplicate_image_review"
        record = {k: row.get(k, "") for k in OUT_FIELDS}
        record.update({"photo_status": status, "width": width, "height": height,
                       "sha256": digest, "manual_review_required": "yes"})
        report.append(record)
        if pic is not None:
            label = f"{row['Группа']} | {row['Бренд']} | {row['Артикул']}"
            tiles.append((label, pic, status))

    with (out_dir / "photo_validation.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(report)
    if tiles:
        tw, th, cols = 260, 290, 4
        count_rows = (len(tiles) + cols - 1) // cols
        board = Image.new("RGB", (tw * cols, th * count_rows), "#F3F4F6")
        drawer = ImageDraw.Draw(board)
        for idx, (label, photo, status) in enumerate(tiles):
            x, y = (idx % cols) * tw, (idx // cols) * th
            thumb = ImageOps.contain(photo, (240, 235))
            board.paste(thumb, (x + (tw - thumb.width)//2, y + (245 - thumb.height)//2))
            drawer.text((x+8, y+249), label[:37], fill="#111827")
            drawer.text((x+8, y+266), status[:38], fill="#6B7280")
        board.save(out_dir / "contact_sheet.jpg", quality=85)
    counts = {}
    for r in report:
        counts[r["photo_status"]] = counts.get(r["photo_status"], 0)+1
    print(f"REVIEW_ONLY: {len(report)} items, {len(tiles)} downloaded photos; photo statuses {counts}")
    print("All photos remain UNVERIFIED for article match and usage rights.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--out", default="output/avito_photo_review")
    args = p.parse_args()
    scan(Path(args.csv), Path(args.out))


if __name__ == "__main__":
    main()
