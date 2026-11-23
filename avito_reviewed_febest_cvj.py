"""Exact, closed Febest CV joint evidence; public manufacturer facts only."""
import re,json,hashlib
from urllib.parse import urlparse,urljoin
SCOPE_COUNT=22
SCOPE_SHA256='f64ea8c1b25fec58d5ffca5cb04eb8627a5eef9fdfa42be8b39ab4d7131b7dc4'
def canon(v):return re.sub('[^A-Z0-9]','',str(v).upper())
def text(n):return ' '.join(n.get_text(' ',strip=True).split())
def parse_source(article,url,raw):
 from bs4 import BeautifulSoup
 if urlparse(url).hostname!='febest.de' or not urlparse(url).path.startswith('/en/details/'):raise ValueError('Non-primary Febest product URL')
 s=BeautifulSoup(raw,'html.parser');node=s.select_one('.detPartCode');h=s.select_one('h1')
 mpn=text(node).split(':',1)[-1].strip() if node else ''
 if canon(mpn)!=canon(article):raise ValueError('Exact Febest MPN mismatch')
 title=text(h) if h else ''
 if not re.search(r'^(OUTER|INNER) (CV )?JOINT\b',title,re.I) or re.search(r'BOOT|GREASE|TRIPOD|HOUSING|CUP|DRIVE SHAFT',title,re.I):raise ValueError('Not a complete CV joint product')
 own=[]
 for tr in s.select('#detailsgrid_table tr'):
  td=tr.find_all('td',recursive=False)
  if len(td)>=3 and canon(text(td[0]))==canon(article):own.append(text(td[2]))
 if len(own)!=1:raise ValueError('Exact compatible OEM row missing')
 refs=[]
 for op in s.select('#oem_select option'):
  v=text(op)
  if op.get('value') in ('0','') or '#' in v or not re.fullmatch(r'[A-Za-z0-9 .*-]+',v):continue
  code=canon(v)
  if len(code)>=5 and code!=canon(article) and code in canon(own[0]):refs.append(v)
 if not refs:raise ValueError('No unambiguous component-compatible OEM reference')
 models=[text(n) for n in s.select('#model_list option') if n.get('value') and text(n)]
 if not models:raise ValueError('Manufacturer applicability absent')
 im=s.select_one('#foto img[src]');photo=urljoin(url,im['src']) if im else ''
 p=urlparse(photo)
 if p.scheme!='https' or p.hostname!='static.febest.de' or not p.path.startswith('/images/big/') or not re.search(r'_p\d+\.(jpg|png)$',p.path,re.I):raise ValueError('Exact Photo modal image absent')
 return {'manufacturer_MPN':mpn,'product_title':title,'oem':canon(refs[0]),'OEM_raw':refs[0],'OEM_make':'EXPLICIT_OEM_COMPATIBILITY_AS_LABELLED_BY_FEBEST','OEM_source_kind':'EXPLICIT_COMPATIBLE_OEM_TABLE_AND_SELECT_ON_EXACT_PRODUCT_PAGE','automaker_reference_rows':refs,'fitment_rows':models,'fitment':'; '.join(models[:3]),'photo_url':photo,'photo_kind':'PHOTO_MODAL_NOT_SCHEME_OR_3D','exact_sku_verified':True}
def validate_source(r,raw):
 actual=parse_source(r['article'],r['manufacturer_page'],raw)
 for k in ('manufacturer_MPN','product_title','oem','OEM_raw','fitment_rows','fitment','photo_url','photo_kind'):
  if actual[k]!=r[k]:raise ValueError('Febest primary source binding changed: '+k)
 return True
def load_reviewed_febest(path):
 d=json.loads(path.read_text());rs=d['items'];keys=[r['brand'].casefold()+'|'+r['article'].casefold() for r in rs];digest=hashlib.sha256('\n'.join(sorted(keys)).encode()).hexdigest()
 if len(rs)!=SCOPE_COUNT or len(set(keys))!=SCOPE_COUNT or digest!=SCOPE_SHA256 or d.get('scope_sha256')!=digest:raise ValueError('Unexpected exact Febest scope')
 photos=set()
 for r in rs:
  if (r['brand']!='Febest' or r['category']!='ШРУС' or not r.get('exact_sku_verified') or not re.fullmatch('[A-Z0-9]+',r['oem']) or canon(r['OEM_raw'])!=r['oem'] or r.get('OEM_source_kind')!='EXPLICIT_COMPATIBLE_OEM_TABLE_AND_SELECT_ON_EXACT_PRODUCT_PAGE' or '#' in r['OEM_raw'] or not r.get('fitment_rows') or not r.get('fitment') or r.get('photo_review')!='ACTUAL_EXACT_PRODUCT_PHOTO_VERIFIED' or not r.get('package_unit_verified') or r.get('primary_product_count_verified')!=1 or r.get('photo_kind')!='PHOTO_MODAL_NOT_SCHEME_OR_3D' or not re.fullmatch('[a-f0-9]{64}',r['photo_sha256']) or r['photo_sha256'] in photos or min(r['photo_dimensions'])<200):raise ValueError('Incomplete exact Febest CV joint evidence')
  if urlparse(r['manufacturer_page']).scheme!='https' or urlparse(r['photo_url']).scheme!='https' or not urlparse(r['photo_url']).path.startswith('/images/big/') or not re.search(r'_p\d+\.(jpg|png)$',urlparse(r['photo_url']).path,re.I) or canon(r['manufacturer_MPN'])!=canon(r['article']) or urlparse(r['manufacturer_page']).hostname!='febest.de' or urlparse(r['photo_url']).hostname!='static.febest.de':raise ValueError('Febest primary identity mismatch')
  photos.add(r['photo_sha256'])
 return rs
def febest_sku(ad,approved,key):
 m=re.fullmatch(r'ШРУС Febest ([A-Za-z0-9.+/\-]+) новый',ad.findtext('Title',''));k=key('Febest',m[1]) if m else None
 if not m or ad.findtext('Brand')!='Febest' or approved.get(k)!='ШРУС' or ad.findtext('SparePartType')!='Трансмиссия и привод' or ad.findtext('TransmissionSparePartType')!='Приводные валы, полуоси и ШРУСы' or ad.find('EngineSparePartType') is not None:raise ValueError('Unreviewed Febest CV joint or wrong type')
 return k,'ШРУС'

