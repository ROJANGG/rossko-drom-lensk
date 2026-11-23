import json,pathlib,requests,threading,concurrent.futures,time,hashlib,io,base64,collections
from datetime import datetime,timezone
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
from PIL import Image,ImageDraw
from avito_reviewed_febest_cvj import parse_source,canon,text
B=pathlib.Path('review/febest-manufacturer');B.mkdir(parents=True,exist_ok=True);D=B/'manufacturer';D.mkdir(exist_ok=True)
items=[r for r in json.loads(pathlib.Path('input/avito_source25_20261123.json').read_text())['items'] if r['brand']=='Febest'];quotes={r['article']:r for r in json.loads(pathlib.Path('review/source25-api-report.json').read_text())['results']};local=threading.local()
def fetch(s,url,**kwargs):
 r=s.request('POST' if 'data' in kwargs else 'GET',url,timeout=(4,7),**kwargs);r.raise_for_status()
 if len(r.content)>8_000_000:raise ValueError('Oversize manufacturer response')
 return r

def review(row):
 r={k:row[k] for k in ['brand','article','category','supplier_nomenclature']};r.update(source_checked_at_utc=datetime.now(timezone.utc).isoformat(),source_status='NOT_CONFIRMED')
 if not quotes[r['article']].get('avito_retail_rub'):r['source_status']='NOT_RUN_API_GATE_BLOCKED';return r
 try:
  if not hasattr(local,'csrf'):
   local.session=requests.Session();first=fetch(local.session,'https://febest.de/en/catalog');page=BeautifulSoup(first.content,'html.parser');local.csrf=page.select_one('form#mainform input[name=_csrf]')['value']
  a=r['article'];split=5 if a.startswith(('0117P','0217P','0317P','0417P','0517P')) else 4;code=a[:split]+'-'+a[split:]
  search=fetch(local.session,'https://febest.de/en/catalog',data={'_csrf':local.csrf,'main_form':'1','subgroup':'0','model':'','code':code,'name':'','oem':''});s=BeautifulSoup(search.content,'html.parser');token=s.select_one('form#mainform input[name=_csrf]')
  if token:local.csrf=token['value']
  links={urljoin(search.url,n['href']) for n in s.select('a[href]') if '/en/details/' in n['href'] and canon(text(n))==canon(a)}
  if len(links)!=1:raise ValueError('Exact catalog product link not found')
  url=next(iter(links));page=fetch(local.session,url);facts=parse_source(a,url,page.content);r.update(facts,manufacturer_page=url,manufacturer_page_sha256=hashlib.sha256(page.content).hexdigest(),source_status='MANUFACTURER_FACTS_VERIFIED',photo_status='NOT_CONFIRMED');(D/(a+'.html')).write_bytes(page.content)
  raw=fetch(local.session,r['photo_url']).content;im=Image.open(io.BytesIO(raw));im.load()
  if min(im.size)<200 or im.format not in ('JPEG','PNG'):raise ValueError('Photo dimensions or format')
  (D/(a+'-original.image')).write_bytes(raw);im.convert('RGB').save(D/(a+'-contact.jpg'));r.update(photo_status='DOWNLOADED_AWAITING_VISUAL_REVIEW',photo_sha256=hashlib.sha256(raw).hexdigest(),photo_dimensions=list(im.size),photo_format=im.format)
 except Exception as e:r['source_error_class']=type(e).__name__
 time.sleep(.15);return r
rows=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
 for i,r in enumerate(ex.map(review,items),1):
  rows.append(r)
  if i%10==0:(B/'sources-partial.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print('FEBEST_SOURCE_PROGRESS',i,flush=True)
(B/'sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');prepared=[r for r in rows if r['source_status']=='MANUFACTURER_FACTS_VERIFIED' and r.get('photo_status')=='DOWNLOADED_AWAITING_VISUAL_REVIEW'];print('SOURCE25_FEBEST_PRIMARY_REVIEW',json.dumps({'items':rows,'ready_for_visual_review':len(prepared)},ensure_ascii=False),flush=True)
for start in range(0,len(prepared),20):
 part=prepared[start:start+20];canvas=Image.new('RGB',(1200,240*((len(part)+4)//5)),'white');draw=ImageDraw.Draw(canvas)
 for i,r in enumerate(part):
  im=Image.open(D/(r['article']+'-contact.jpg'));im.thumbnail((230,205));x=i%5*240;y=i//5*240;canvas.paste(im,(x,y+30));draw.text((x+3,y+3),r['article'],fill='black')
 buf=io.BytesIO();canvas.save(buf,format='JPEG',quality=72);print('CONTACT_SOURCE25_FEBEST_PAGE',json.dumps({'page':start//20+1,'articles':[r['article'] for r in part],'image_base64':base64.b64encode(buf.getvalue()).decode()}),flush=True)

