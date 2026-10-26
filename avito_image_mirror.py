"""Mirror supplier-approved images to stable public JPEG links for Avito.

ROSKKO image URLs require browser-like request headers; third-party scrapers
may receive non-image content. Decode source bytes with PIL and host a small
set of public JPEGs in the isolated Avito branch. Never commit a supplier
price list, private user data or a broken image.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from PIL import ImageOps

from avito_feed import stable_id
from avito_expand_canary import approved_canary_ids
from avito_next_five_preflight import approved_next_five_ids
from avito_second_five_preflight import approved_second_five_ids
from avito_third_ten_preflight import approved_third_ten_ids
from avito_fourth_eleven_preflight import approved_fourth_eleven_ids
from avito_bulk66_preflight import approved_bulk_ids
from avito_ngn53_preflight import approved_ngn53_ids
from avito_photo_check import approved_url, retrieve_image
from avito_xml_v3_diagnostic import TEST_SKUS

REPO = "ROJANGG/rossko-drom-lensk"
IMAGE_BRANCH = "avito-irkutsk-feed"
REMOTE_BASE = f"https://raw.githubusercontent.com/{REPO}/{IMAGE_BRANCH}/avito-images"
# Avito failed to reach the raw.githubusercontent.com IP for GD0123 on
# 2026-10-20. Use the independently tested jsDelivr HTTPS CDN for this
# particular JPEG without changing any other ad or its permanent Id.
CDN_BASE = f"https://cdn.jsdelivr.net/gh/{REPO}@{IMAGE_BRANCH}/avito-images"
PHOTO_CDN_PILOT_IDS = approved_ngn53_ids() | {stable_id("Тормозные диски", "CTR", "GD0123")} | approved_second_five_ids() | approved_third_ten_ids() | approved_fourth_eleven_ids() | approved_bulk_ids()


def public_photo_url(sku: str, filename: str) -> str:
    if sku not in pilot_ids() | approved_next_five_ids() | approved_second_five_ids() | approved_third_ten_ids() | approved_fourth_eleven_ids() | approved_bulk_ids() | approved_ngn53_ids() | {
        stable_id("Тормозные диски", "CTR", "GD0037"),
        stable_id("Тормозные диски", "CTR", "GD0053"),
    }:
        raise ValueError("Unexpected Avito image ID: " + sku)
    host = CDN_BASE if sku in PHOTO_CDN_PILOT_IDS else REMOTE_BASE
    return f"{host}/{filename}"

# A feed may legitimately shrink when local Rossko stock disappears. Do not
# mirror surprise new IDs or a drastically incomplete supplier snapshot.
MIN_ACTIVE_PILOT = 40


def pilot_ids() -> set[str]:
    return {
        stable_id(group, brand, article)
        for group, pairs in TEST_SKUS.items()
        for brand, article in pairs
    }


def render_jpeg(image) -> bytes:
    im = ImageOps.exif_transpose(image).convert("RGB")
    # Preserve enough detail to distinguish the exact spare part.
    if max(im.size) > 1600:
        im.thumbnail((1600, 1600))
    output = io.BytesIO()
    im.save(output, format="JPEG", quality=88, optimize=True)
    encoded = output.getvalue()
    if not encoded.startswith(b"\xff\xd8\xff") or len(encoded) > 6_000_000:
        raise ValueError("Converted photo is not a suitable JPEG")
    return encoded


def image_urls_for_pilot(xml_bytes: bytes, *, extra_ids: set[str] | None = None) -> dict[str, str]:
    root = ET.fromstring(xml_bytes)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Expected Avito XML v3")
    items = {}
    for node in root.findall("Ad"):
        sku = (node.findtext("Id") or "").strip()
        imgs = node.find("Images")
        el = imgs.find("Image") if imgs is not None else None
        url = el.get("url", "") if el is not None else ""
        if sku in items or not sku or not approved_url(url):
            raise ValueError(f"Invalid supplier image or repeated SKU: {sku}")
        items[sku] = url
    from avito_feed import stable_id
    from avito_expand_canary import CANARY
    permitted_extra = {stable_id("Тормозные диски", "CTR", article) for _, article in CANARY} | approved_next_five_ids() | approved_second_five_ids() | approved_third_ten_ids() | approved_fourth_eleven_ids() | approved_bulk_ids() | approved_ngn53_ids()
    if not (extra_ids or set()) <= permitted_extra:
        raise ValueError("Unexpected additional Avito ID")
    allowed = pilot_ids() | (extra_ids or set())
    if not set(items) <= allowed or len(items) < MIN_ACTIVE_PILOT:
        raise ValueError(
            f"Refusing to mirror unexpected or too many missing IDs: {set(items)^allowed}"
        )
    return items


def write_mirrors_and_rewrite(xml_bytes: bytes, photo_dir: Path, *, extra_ids: set[str] | None = None) -> tuple[bytes, dict]:
    source_urls = image_urls_for_pilot(xml_bytes, extra_ids=extra_ids)
    # Fail-closed: stage everything in memory; write only after all
    # currently available SKU images have been decoded and checked.
    def download_and_render(entry):
        sku, url = entry
        last_status = "no_attempt"
        for attempt in range(3):
            pic, status, _w, _h, _digest = retrieve_image(url)
            if status == "available_unverified" and pic is not None:
                image_bytes = render_jpeg(pic)
                fingerprint = hashlib.sha256(image_bytes).hexdigest()[:12]
                fname = f"{sku}-{fingerprint}.jpg"
                return sku, {"filename":fname,"bytes":image_bytes,
                             "url":public_photo_url(sku,fname)}
            last_status = status
            if attempt < 2:
                time.sleep(1 + attempt * 2)
        # Never publish missing or unverified photos, including for old listings.
        raise ValueError(f"Could not download source image for {sku} after 3 attempts: {last_status}")
    # Supplier intermittently times out on serial requests. Parallelism is bounded
    # and still stages ALL photos before writing any new public file.
    with ThreadPoolExecutor(max_workers=5) as pool:
        staging = dict(pool.map(download_and_render, source_urls.items()))
    photo_dir.mkdir(parents=True, exist_ok=True)
    for item in staging.values():
        target = photo_dir / item["filename"]
        if target.exists() and target.read_bytes() != item["bytes"]:
            raise ValueError("Digest name collision in mirrored supplier image")
        target.write_bytes(item["bytes"])
    root = ET.fromstring(xml_bytes)
    for ad in root.findall("Ad"):
        sku = ad.findtext("Id")
        im = ad.find("./Images/Image")
        im.set("url", staging[sku]["url"])
    ET.indent(root, space="  ")
    output = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    manifest = {sku: {"url":row["url"], "source":source_urls[sku]} for sku,row in staging.items()}
    if len(manifest) != len(source_urls):
        raise ValueError("Unexpected pilot manifest count")
    return output, manifest


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--candidate", required=True)
    p.add_argument("--image-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--manifest", default="")
    p.add_argument("--approved-new", default="")
    p.add_argument("--approved-next-five", action="store_true")
    p.add_argument("--approved-second-five", action="store_true")
    p.add_argument("--approved-third-ten", action="store_true")
    p.add_argument("--approved-fourth-eleven", action="store_true")
    p.add_argument("--approved-bulk66", action="store_true")
    p.add_argument("--approved-ngn53", action="store_true")
    a=p.parse_args()
    content, manifest=write_mirrors_and_rewrite(
        Path(a.candidate).read_bytes(),Path(a.image_dir),
        extra_ids=(approved_canary_ids(Path(a.approved_new)) if a.approved_new else set())
        | (approved_next_five_ids() if a.approved_next_five else set())
        | (approved_second_five_ids() if a.approved_second_five else set())
        | (approved_third_ten_ids() if a.approved_third_ten else set())
        | (approved_fourth_eleven_ids() if a.approved_fourth_eleven else set())
        | (approved_bulk_ids() if a.approved_bulk66 else set())
        | (approved_ngn53_ids() if a.approved_ngn53 else set()))
    target=Path(a.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(content)
    if a.manifest:
        path=Path(a.manifest)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_PHOTOS_MIRRORED",len(manifest),"with unique JPEG URLs",flush=True)


if __name__=="__main__":
    main()
