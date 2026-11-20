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


class CDNPurgeThrottled(ValueError):
    def __init__(self, seconds):
        self.retry_after_seconds=max(0,int(seconds or 0))
        super().__init__('CDN purge throttled; retry after '+str(self.retry_after_seconds)+' seconds')

def refresh(expected, *, getter=fetch, sleeper=time.sleep):
    root=ET.fromstring(expected);count=len(root.findall('Ad'))
    if root.tag!='Ads' or root.get('formatVersion')!='3' or not 150<=count<=947:raise ValueError('Unexpected validated Avito XML')
    digest=hashlib.sha256(expected).hexdigest()
    def result():return {'ads':count,'sha256':digest,'cdn_exact_bytes_verified':True}
    if hashlib.sha256(getter(CDN)).hexdigest()==digest:return result()
    response=json.loads(getter(PURGE))
    if response.get('status') not in ('finished','pending','processing'):raise ValueError('CDN refresh request not accepted')
    statuses=response.get('paths',{})
    if any(isinstance(v,dict) and v.get('throttled') for v in statuses.values()):
        raise CDNPurgeThrottled(max(v.get('throttlingReset',0) for v in statuses.values() if isinstance(v,dict) and v.get('throttled')))
    for attempt in range(12):
        if hashlib.sha256(getter(CDN)).hexdigest()==digest:return result()
        if attempt<11:sleeper(10)
    raise ValueError('CDN still serves different XML bytes after refresh')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xml', type=Path, required=True)
    args = parser.parse_args()
    print('AVITO_PUBLIC_CDN_REFRESH', json.dumps(refresh(args.xml.read_bytes())))


