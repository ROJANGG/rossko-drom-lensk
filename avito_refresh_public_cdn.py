"""Refresh only this repository's public Avito XML after a validated commit."""
import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

PATH = '/gh/ROJANGG/rossko-drom-lensk@avito-irkutsk-feed/AVITO_PILOT_4_PREVIEW_NOT_LIVE.xml'
CDN = 'https://cdn.jsdelivr.net' + PATH
PURGE = 'https://purge.jsdelivr.net' + PATH


def fetch(url):
    if url not in (CDN, PURGE):
        raise ValueError('Unexpected CDN endpoint')
    with urllib.request.urlopen(url, timeout=20) as response:
        data = response.read(8_000_001)
    if len(data) > 8_000_000:
        raise ValueError('Oversize CDN response')
    return data


def refresh(expected, *, getter=fetch, sleeper=time.sleep):
    root = ET.fromstring(expected)
    count = len(root.findall('Ad'))
    if root.tag != 'Ads' or root.get('formatVersion') != '3' or not 150 <= count <= 300:
        raise ValueError('Unexpected validated Avito XML')
    digest = hashlib.sha256(expected).hexdigest()
    result = json.loads(getter(PURGE))
    if result.get('status') not in ('finished', 'pending', 'processing'):
        raise ValueError('CDN refresh request not accepted')
    for attempt in range(5):
        if hashlib.sha256(getter(CDN)).hexdigest() == digest:
            return {'ads': count, 'sha256': digest, 'cdn_exact_bytes_verified': True}
        if attempt < 4:
            sleeper(2 * (attempt + 1))
    raise ValueError('CDN still serves different XML bytes after refresh')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xml', type=Path, required=True)
    args = parser.parse_args()
    print('AVITO_PUBLIC_CDN_REFRESH', json.dumps(refresh(args.xml.read_bytes())))
