"""Closed source-reviewed SUFIX scope; no API calls or publication."""
import hashlib,json,re
from urllib.parse import urlparse
SCOPE_SHA256='e1264f9083172b381c0cf2416b670a892f5bb9d6b865601ff547431aaf0f300d'
SCOPE_COUNT=125
CATEGORY='Ремни приводные'
META={'Ремни приводные':('Ремень приводной','Приводные ремни, натяжители'),'Ремни ГРМ':('Ремень ГРМ','Ремни, цепи, элементы ГРМ'),'Радиаторы охлаждения':('Радиатор охлаждения',None),'Радиаторы кондиционера':('Радиатор кондиционера',None)}
def load_reviewed_sufix_belts(path):
    m=json.loads(path.read_text(encoding='utf-8'));rs=m['items']
    keys=[r['brand'].casefold()+'|'+r['article'].casefold() for r in rs]
    digest=hashlib.sha256('\n'.join(sorted(keys)).encode()).hexdigest()
    if len(rs)!=SCOPE_COUNT or len(set(keys))!=SCOPE_COUNT or digest!=SCOPE_SHA256 or m['scope_sha256']!=digest:raise ValueError('Unexpected reviewed SUFIX scope')
    photos=set()
    for r in rs:
        if (r['brand']!='SUFIX' or r['category'] not in META or not re.fullmatch({'Радиаторы охлаждения':r'XG\d+','Радиаторы кондиционера':r'XC\d+'}.get(r['category'],r'FB\d+'),r['article'])
                or not r.get('exact_sku_verified') or not re.fullmatch('[A-Z0-9]+',r['oem'])
                or not r.get('OEM_make') or not r.get('fitment_rows') or not r.get('fitment')
                or r.get('photo_review')!='ACTUAL_EXACT_PRODUCT_PHOTO_VERIFIED'
                or not re.fullmatch('[a-f0-9]{64}',r['photo_sha256']) or r['photo_sha256'] in photos
                or min(r['photo_dimensions'])<200):raise ValueError('Incomplete exact SUFIX evidence')
        for name in ('manufacturer_page','photo_url'):
            u=urlparse(r[name])
            if u.scheme!='https' or u.hostname!='sufix.pro':raise ValueError('Foreign SUFIX evidence host')
        if urlparse(r['manufacturer_page']).path!='/'+r['article'][:2]+'-'+r['article'][2:]+'.html':raise ValueError('SUFIX source SKU mismatch')
        photos.add(r['photo_sha256'])
    return rs
def sufix_belt_sku(ad,approved,key):
    for category,(prefix,engine) in META.items():
        pattern={'Радиаторы охлаждения':r'XG\d+','Радиаторы кондиционера':r'XC\d+'}.get(category,r'FB\d+')
        m=re.fullmatch(re.escape(prefix)+r' SUFIX ('+pattern+r') новый',ad.findtext('Title',''))
        if not m:continue
        k=key('SUFIX',m[1])
        if ad.findtext('Brand')!='SUFIX' or ad.findtext('SparePartType')!=('Система охлаждения' if engine is None else 'Двигатель') or ad.findtext('EngineSparePartType')!=engine or approved.get(k)!=category:raise ValueError('Unreviewed SUFIX SKU/category')
        return k,category
    raise ValueError('Unrecognized exact SUFIX belt title')
