"""Closed source-reviewed SUFIX scope; no API calls or publication."""
import hashlib,json,re
from urllib.parse import urlparse
SCOPE_SHA256='0804b224f1d9df8a85ce42bb95e300cb57944fb68ee16ce6023e25b2b98e3fb6'
SCOPE_COUNT=29
CATEGORY='Ремни приводные'
def load_reviewed_sufix_belts(path):
    m=json.loads(path.read_text(encoding='utf-8'));rs=m['items']
    keys=[r['brand'].casefold()+'|'+r['article'].casefold() for r in rs]
    digest=hashlib.sha256('\n'.join(sorted(keys)).encode()).hexdigest()
    if len(rs)!=SCOPE_COUNT or len(set(keys))!=SCOPE_COUNT or digest!=SCOPE_SHA256 or m['scope_sha256']!=digest:raise ValueError('Unexpected reviewed SUFIX scope')
    photos=set()
    for r in rs:
        if (r['brand']!='SUFIX' or r['category']!=CATEGORY or not re.fullmatch(r'FB\d+',r['article'])
                or not r.get('exact_sku_verified') or not re.fullmatch('[A-Z0-9]+',r['oem'])
                or not r.get('OEM_make') or not r.get('fitment_rows') or not r.get('fitment')
                or r.get('photo_review')!='ACTUAL_EXACT_PRODUCT_PHOTO_VERIFIED'
                or not re.fullmatch('[a-f0-9]{64}',r['photo_sha256']) or r['photo_sha256'] in photos
                or min(r['photo_dimensions'])<200):raise ValueError('Incomplete exact SUFIX evidence')
        for name in ('manufacturer_page','photo_url'):
            u=urlparse(r[name])
            if u.scheme!='https' or u.hostname!='sufix.pro':raise ValueError('Foreign SUFIX evidence host')
        if urlparse(r['manufacturer_page']).path!='/FB-'+r['article'][2:]+'.html':raise ValueError('SUFIX source SKU mismatch')
        photos.add(r['photo_sha256'])
    return rs
def sufix_belt_sku(ad,approved,key):
    m=re.fullmatch(r'Ремень приводной SUFIX (FB\d+) новый',ad.findtext('Title',''))
    if not m or ad.findtext('Brand')!='SUFIX' or ad.findtext('SparePartType')!='Двигатель' or ad.findtext('EngineSparePartType')!='Приводные ремни, натяжители':raise ValueError('Unrecognized reviewed SUFIX title/classification')
    k=key('SUFIX',m[1])
    if approved.get(k)!=CATEGORY:raise ValueError('Unreviewed SUFIX SKU')
    return k,CATEGORY
