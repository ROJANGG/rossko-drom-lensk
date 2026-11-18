"""Closed manufacturer and visually reviewed LYNX source06 scope."""
import hashlib,json,re
from urllib.parse import urlparse
SCOPE_SHA256='d697a87e9d014d472f601eda8c0ecad451bc0ccbf4b71633364611c71fda3ea3'
SCOPE_COUNT=12
META={
 'Ремни ГРМ':('Ремень ГРМ','новый','Двигатель','Ремни, цепи, элементы ГРМ'),
 'Прокладки ГБЦ':('Прокладка ГБЦ','новая','Двигатель','Прокладки и ремкомплекты'),
 'Радиаторы охлаждения':('Радиатор охлаждения','новый','Система охлаждения',None),
}
def load_reviewed_lynx(path):
 m=json.loads(path.read_text(encoding='utf-8'));rs=m['items']
 keys=[r['brand'].casefold()+'|'+r['article'].casefold() for r in rs]
 digest=hashlib.sha256('\n'.join(sorted(keys)).encode()).hexdigest()
 if len(rs)!=SCOPE_COUNT or len(set(keys))!=SCOPE_COUNT or digest!=SCOPE_SHA256 or m['scope_sha256']!=digest:raise ValueError('Unexpected exact LYNX source06 scope')
 images=set()
 for r in rs:
  if (r['brand']!='LYNXauto' or r['category'] not in META or not r.get('exact_sku_verified')
      or not re.fullmatch('[A-Z0-9]+',r['oem']) or not r.get('OEM_make') or not r.get('fitment')
      or r.get('photo_review')!='ACTUAL_EXACT_PRODUCT_PHOTO_VERIFIED'
      or not re.fullmatch('[a-f0-9]{64}',r['photo_sha256']) or r['photo_sha256'] in images
      or min(r['photo_dimensions'])<200):raise ValueError('Incomplete LYNX evidence')
  for n in ('manufacturer_page','fitment_page','photo_url'):
   u=urlparse(r[n])
   if u.scheme!='https' or u.hostname!='ecatalogue.lynxauto.jp':raise ValueError('Foreign source host')
  if urlparse(r['manufacturer_page']).path!='/'+r['article']+'.html':raise ValueError('Product page SKU mismatch')
  images.add(r['photo_sha256'])
 return rs
def lynx_sku(ad,approved,key):
 for group,(prefix,ending,part,engine) in META.items():
  m=re.fullmatch(re.escape(prefix)+r' LYNXauto ([A-Za-z0-9.+/\-]+) '+ending,ad.findtext('Title',''))
  if not m:continue
  k=key('LYNXauto',m[1])
  if (ad.findtext('Brand')!='LYNXauto' or ad.findtext('SparePartType')!=part
      or ad.findtext('EngineSparePartType')!=engine or approved.get(k)!=group):raise ValueError('Unreviewed LYNX SKU or category')
  return k,group
 raise ValueError('Unrecognized exact LYNX source06 title')
