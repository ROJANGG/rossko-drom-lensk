"""Check 51-53 newly published NGN JPEGs on jsDelivr BEFORE changing Avito XML.

Runs after committing images-only to the isolated feed branch. If CDN is
unavailable, fail closed and leave the currently published XML unchanged.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

from avito_ngn53_preflight import approved_ngn53_ids

EXPECTED_PREFIX = ("https://cdn.jsdelivr.net/gh/ROJANGG/"
                   "rossko-drom-lensk@avito-irkutsk-feed/avito-images/")


def select_new_images(manifest: dict, directory: Path):
    approved = approved_ngn53_ids()
    actual = set(manifest) & approved
    if not 51 <= len(actual) <= 53:
        raise ValueError(f"Expected 51-53 active NGN disc JPEGs, got {len(actual)}")
    if not actual <= set(manifest):
        raise ValueError("NGN source photo missing from manifest")
    valid = {}
    for listing_id in sorted(actual):
        url = manifest[listing_id].get("url", "")
        if not url.startswith(EXPECTED_PREFIX) or urlsplit(url).hostname != "cdn.jsdelivr.net":
            raise ValueError("Untrusted CDN URL for " + listing_id)
        fname = url.rsplit("/", 1)[-1]
        match = re.fullmatch(re.escape(listing_id) + r"-([0-9a-f]{12})\.jpg", fname)
        if not match:
            raise ValueError("Wrong immutable NGN photo filename " + fname)
        path = directory / fname
        if not path.is_file() or path.stat().st_size < 1500:
            raise ValueError("Mirrored NGN image is missing or empty: " + fname)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest()[:12] != match.group(1):
            raise ValueError("Local NGN JPEG content hash differs from filename")
        with Image.open(io.BytesIO(raw)) as picture:
            picture.verify()
        valid[listing_id] = (url, raw)
    return valid


def probe_one(item):
    sku, (url, raw) = item
    expected = hashlib.sha256(raw).digest()
    err = "unattempted"
    for attempt in range(5):
        try:
            response = requests.get(url, timeout=(8, 22), allow_redirects=False)
            if response.status_code == 200:
                blob = response.content
                if response.headers.get("content-type","").split(";")[0] not in (
                    "image/jpeg", "image/jpg", "application/octet-stream"):
                    err = "invalid_public_mime"
                elif hashlib.sha256(blob).digest() != expected:
                    err = "public_content_checksum_mismatch"
                else:
                    with Image.open(io.BytesIO(blob)) as picture:
                        picture.verify()
                    return sku, "OK"
            else:
                err = f"http_{response.status_code}"
        except (requests.RequestException, OSError, ValueError) as exc:
            err = type(exc).__name__
        if attempt < 4:
            time.sleep(3 + attempt * 3)
    return sku, err


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--image-dir",required=True)
    parser.add_argument("--report",required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    chosen=select_new_images(data,Path(args.image_dir))
    with ThreadPoolExecutor(max_workers=8) as pool:
        checks=dict(pool.map(probe_one,chosen.items()))
    errors={k:s for k,s in checks.items() if s!="OK"}
    report={"checked":len(checks),"passed":len(checks)-len(errors),
            "failed_ids":sorted(errors), "issues":errors,
            "state":"PASS" if not errors else "BLOCK_XML_PUBLICATION"}
    target=Path(args.report)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("NGN53_PUBLIC_CDN_CHECK",json.dumps(report),flush=True)
    if errors:
        raise RuntimeError("New NGN CDN photo links are not fully accessible")


if __name__=="__main__":
    main()
