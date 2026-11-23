import json,pathlib,requests,concurrent.futures,hashlib,re,io,time,base64
from datetime import datetime,timezone
from urllib.parse import urljoin,urlparse,parse_qs
from bs4 import BeautifulSoup
from PIL import Image,ImageDraw
B=pathlib.Path('review/lynx26');B.mkdir(parents=True,exist_ok=True);D=B/'manufacturer';D.mkdir(exist_ok=True);items=json.loads(pathlib.Path('input/avito_source26_20261123.json').read_text())['items'];quotes={r['article']:r for r in json.loads(pathlib.Path('review/source26-api-report.json').read_text())['results']};canon=lambda x:re.sub('[^A-Z0-9]','',str(x).upper());text=lambda n:' '.join(n.get_text(' ',strip=True).split())
def get(url):
 if urlparse(url).scheme!='https' or urlparse(url).hostname!='ecatalogue.lynxauto.jp':raise ValueError('Non-primary manufacturer URL')
 r=requests.get(url,timeout=(4,7));r.raise_for_status()
 if len(r.content)>8000000:raise ValueError('Oversize response')
 return r.content

def review(row):
 r={k:row[k] for k in ['brand','article','category','supplier_nomenclature']};a=r['article'];url='https://ecatalogue.lynxauto.jp/'+a+'.html';r.update(manufacturer_page=url,source_checked_at_utc=datetime.now(timezone.utc).isoformat(),source_status='NOT_CONFIRMED')
 if not quotes[a].get('avito_retail_rub'):r['source_status']='NOT_RUN_API_GATE_BLOCKED';return r
 try:
  raw=get(url);s=BeautifulSoup(raw,'html.parser');mpn=s.select('[itemprop=mpn]');h=s.select_one('h1');title=text(h) if h else '';r['product_title']=title
  if len(mpn)!=1 or canon(text(mpn[0]))!=canon(a):raise ValueError('Exact MPN missing')
  patterns={'Ремни приводные':r'ремень|drive belt','Ремни ГРМ':r'ремень.*грм|грм.*ремень|timing belt','Прокладки ГБЦ':r'прокладк.*(гбц|головк)|cylinder head gasket'}
  if not re.search(patterns[r['category']],title,re.I) or (r['category']=='Ремни приводные' and re.search('грм|timing',title,re.I)):raise ValueError('Category mismatch')
  refs=[]
  for tr in s.select('table.pcard-oeno-bottom tr'):
   td=tr.find_all('td',recursive=False)
   if len(td)>=2 and text(td[0]) and text(td[1]):refs.append([text(td[0]).upper(),text(td[1])])
  links=[urljoin(url,n['data-link']) for n in s.select('.pcard-list-mark-item[data-link]')];chosen=None
  for link in links:
   make=parse_qs(urlparse(link).query).get('mark',[''])[0]
   ref=next((x for x in refs if canon(x[0])==canon(make)),None)
   if ref:chosen=(link,make,ref);break
  if chosen is None:raise ValueError('Same-make manufacturer OEM and applicability absent')
  link,make,ref=chosen;fit=get(link);f=BeautifulSoup(fit,'html.parser');fr=[]
  for tr in f.select('tr'):
   td=tr.find_all('td',recursive=False)
   if len(td)>=2 and text(td[0])!='Model range':fr.append([text(c) for c in td])
  if not fr:raise ValueError('Empty applicability table')
  im=s.select_one('.pcard-images a.lightbox[href]')
  if im is None:raise ValueError('Photo binding absent')
  r.update(manufacturer_MPN=text(mpn[0]),exact_sku_verified=True,manufacturer_page_sha256=hashlib.sha256(raw).hexdigest(),OEM_make=ref[0],OEM_raw=ref[1],oem=canon(ref[1]),original_OE_rows=refs,fitment_page=link,fitment_page_sha256=hashlib.sha256(fit).hexdigest(),fitment_rows=fr[:5],fitment='; '.join(make+' '+', '.join(c for c in row if c) for row in fr[:3]),photo_url=urljoin(url,im['href']),source_status='MANUFACTURER_FACTS_VERIFIED',photo_status='NOT_CONFIRMED');(D/(a+'.html')).write_bytes(raw);(D/(a+'-fitment.html')).write_bytes(fit)
  photo=get(r['photo_url']);pic=Image.open(io.BytesIO(photo));pic.load()
  if min(pic.size)<200 or pic.format not in ('JPEG','PNG'):raise ValueError('Image dimensions or format')
  (D/(a+'-original.image')).write_bytes(photo);pic.convert('RGB').save(D/(a+'-contact.jpg'));r.update(photo_sha256=hashlib.sha256(photo).hexdigest(),photo_dimensions=list(pic.size),photo_format=pic.format,photo_status='DOWNLOADED_AWAITING_VISUAL_REVIEW')
 except Exception as e:r['source_error_class']=type(e).__name__
 time.sleep(.15);return r
rows=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
 for i,r in enumerate(ex.map(review,items),1):
  rows.append(r)
  if i%10==0:(B/'partial.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print('SOURCE26_PROGRESS',i,flush=True)
(B/'sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');prepared=[r for r in rows if r['source_status']=='MANUFACTURER_FACTS_VERIFIED' and r.get('photo_status')=='DOWNLOADED_AWAITING_VISUAL_REVIEW'];print('SOURCE26_PRIMARY_REVIEW',json.dumps({'items':rows,'ready':len(prepared)},ensure_ascii=False),flush=True)
for start in range(0,len(prepared),20):
 part=prepared[start:start+20];canvas=Image.new('RGB',(1200,240*((len(part)+4)//5)),'white');draw=ImageDraw.Draw(canvas)
 for i,r in enumerate(part):
  im=Image.open(D/(r['article']+'-contact.jpg'));im.thumbnail((230,205));x=i%5*240;y=i//5*240;canvas.paste(im,(x,y+30));draw.text((x+3,y+3),r['article'],fill='black')
 buf=io.BytesIO();canvas.save(buf,format='JPEG',quality=72);print('CONTACT_SOURCE26_PAGE',json.dumps({'page':start//20+1,'articles':[r['article'] for r in part],'image_base64':base64.b64encode(buf.getvalue()).decode()}),flush=True)
