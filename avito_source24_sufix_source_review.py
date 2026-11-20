"""Bounded first-party source research, independent of publication eligibility."""
import concurrent.futures,hashlib,io,json,pathlib,re,time
from datetime import datetime,timezone
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup
from PIL import Image,ImageDraw

B=pathlib.Path('review/source24-manufacturer');B.mkdir(parents=True,exist_ok=True);D=B/'manufacturer';D.mkdir(exist_ok=True)
items=json.loads(pathlib.Path('input/avito_source24_20261120.json').read_text())['items']
quotes={r['article']:r for r in json.loads(pathlib.Path('review/source24-api-report.json').read_text())['results']}
MAKES=set('ACURA|ALFA ROMEO|AUDI|BMW|BRILLIANCE|BYD|CADILLAC|CHANGAN|CHERY|CHEVROLET|CHRYSLER|CITROEN|CITROËN|DAEWOO|DAIHATSU|DATSUN|DODGE|FIAT|FORD|GEELY|GM|GREAT WALL|HAVAL|HONDA|HYUNDAI|INFINITI|ISUZU|JAGUAR|JEEP|KIA|LADA|LAND ROVER|LEXUS|LINCOLN|MAZDA|MERCEDES BENZ|MERCEDES-BENZ|MINI|MITSUBISHI|NISSAN|OPEL|PEUGEOT|PORSCHE|PROTON|RENAULT|SAAB|SEAT|SKODA|SMART|SSANGYONG|SUBARU|SUZUKI|TATA|TOYOTA|VAUXHALL|VOLKSWAGEN|VOLVO|VAG|VAZ|GAZ|UAZ|ZAZ'.split('|'))
MAKES.update({'GENERALMOTORS','HYUNDAIKIA'})
def maker_key(v):return re.sub(r'[\s./&_-]+','',str(v).upper())
MAKER_KEYS={maker_key(x) for x in MAKES}
OEM_GROUP_MAKES={'GENERALMOTORS':('CHEVROLET','DAEWOO','OPEL','CADILLAC','GM'),'GM':('CHEVROLET','DAEWOO','OPEL','CADILLAC','GM'),'HYUNDAIKIA':('HYUNDAI','KIA'),'VAG':('VOLKSWAGEN','AUDI','SEAT','SKODA','VAG')}
def canon(v):return re.sub('[^A-Z0-9]','',str(v).upper())
def txt(n):return ' '.join(n.get_text(' ',strip=True).split())
def get(url):
    r=requests.get(url,timeout=(4,7));r.raise_for_status()
    if len(r.content)>8_000_000:raise ValueError('Oversize source response')
    return r.content
def review(row):
    a=row['article'];r={k:row[k] for k in ('brand','article','category','supplier_nomenclature')}
    r.update(source_checked_at_utc=datetime.now(timezone.utc).isoformat(),source_status='NOT_CONFIRMED')
    if not quotes[r['article']].get('avito_retail_rub'):
        r['source_status']='NOT_RUN_API_GATE_BLOCKED';return r
    try:
        if not re.fullmatch(r'ST\d+',a):raise ValueError('Unsupported exact manufacturer article format')
        model='ST-'+a[2:];url='https://sufix.pro/'+model+'.html';r['manufacturer_page']=url
        p=D/(a+'.html')
        raw=p.read_bytes() if p.exists() else get(url)
        if not p.exists():p.write_bytes(raw)
        r['page_captured_at_utc']=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat()
        r['manufacturer_page_sha256']=hashlib.sha256(raw).hexdigest();s=BeautifulSoup(raw,'html.parser')
        label=s.select_one('[itemprop="mpn"][data-model]');heading=s.select_one('h1')
        if label is None or canon(label['data-model'])!=canon(a):raise ValueError('Exact manufacturer MPN mismatch')
        r['manufacturer_MPN']=label['data-model'];r['product_title']=txt(heading) if heading else ''
        if heading is None or not re.search(r'^ШРУС\b|^Шарнир.*равных.*скорост',r['product_title'],re.I):raise ValueError('Requested product category not confirmed')
        r['exact_sku_verified']=True
        references=[]
        for tr in s.select('table.pcard-analog-bottom tr'):
            cells=tr.find_all('td',recursive=False)
            if len(cells)>=2:
                number,make=txt(cells[0]),txt(cells[1]).upper()
                if maker_key(make) in MAKER_KEYS and number and not re.search('[,;/]',number) and re.fullmatch('[A-Za-z0-9 .-]+',number):references.append([make,number])
        r['automaker_reference_rows']=list(dict.fromkeys(tuple(x) for x in references))
        r['OEM_source_kind']='AUTOMAKER_ROWS_IN_MANUFACTURER_MIXED_REFERENCE_TABLE'
        groups={}
        for group in s.select('.applicabilit-group'):
            name=group.select_one('.applicabilit-group-title')
            if name is None:continue
            rows=[]
            for link in group.select('.applicabilit-item a'):
                model_node=link.select_one('.model');mod=link.select_one('.mofif')
                if model_node is not None:rows.append({'model':txt(model_node),'modification':txt(mod) if mod else '', 'url':urljoin(url,link.get('href',''))})
            if rows:groups[txt(name).upper()]=rows
        r['applicability_make_counts']={k:len(v) for k,v in groups.items()}
        selected=None;fit_make=None
        for ref in r['automaker_reference_rows']:
            targets=(maker_key(ref[0]),)+tuple(maker_key(x) for x in OEM_GROUP_MAKES.get(maker_key(ref[0]),()))
            fit_make=next((g for g in groups if maker_key(g) in targets),None)
            if fit_make:selected=ref;break
        if selected:
            r.update(OEM_make=selected[0],OEM_raw=selected[1],OEM=canon(selected[1]),fitment_rows=groups[fit_make][:5],applicability_make=fit_make,OEM_group_label_as_on_manufacturer_page=selected[0],fitment_status='MANUFACTURER_APPLICABILITY_VERIFIED',OEM_applicability_binding='SAME_EXACT_PRODUCT_PAGE_WITH_AUTOMAKER_OR_GROUP_LABEL')
        elif references:r['OEM_applicability_binding_status']='NOT_CONFIRMED'
        r['source_status']='MANUFACTURER_FACTS_VERIFIED' if selected else 'OEM_OR_SAME_MAKE_APPLICABILITY_NOT_CONFIRMED'
        photo=s.select_one('a.lightboxgroup[href]');r['photo_status']='NOT_CONFIRMED'
        if photo:
            image_url=urljoin(url,photo['href']);r['photo_url']=image_url
            if urlparse(image_url).hostname!='sufix.pro':raise ValueError('Unexpected primary image host')
            try:
                pp=D/(a+'-original.image');image_raw=pp.read_bytes() if pp.exists() else get(image_url)
                im=Image.open(io.BytesIO(image_raw));im.load()
                if min(im.size)<200 or im.format not in ('JPEG','PNG'):raise ValueError('Photo format or dimensions not confirmed')
                pp.write_bytes(image_raw);im.convert('RGB').save(D/(a+'-contact.jpg'))
                r.update(photo_status='DOWNLOADED_AWAITING_VISUAL_REVIEW',photo_sha256=hashlib.sha256(image_raw).hexdigest(),photo_dimensions=list(im.size),photo_format=im.format)
            except Exception as e:r['photo_error_class']=type(e).__name__
    except Exception as e:r['source_error_class']=type(e).__name__
    time.sleep(0.15)
    return r

if __name__=='__main__':
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for r in pool.map(review,items):
            rows.append(r)
            if len(rows)%10==0:
                (B/'sources-partial.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
                print('SUFIX_SOURCE_PROGRESS',len(rows),'FACTS',sum(x['source_status']=='MANUFACTURER_FACTS_VERIFIED' for x in rows),'PHOTOS',sum(x.get('photo_status')=='DOWNLOADED_AWAITING_VISUAL_REVIEW' for x in rows),flush=True)
    (B/'sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print('SUFIX_SOURCE_COMPLETE',len(rows),flush=True)

    import base64,collections
    prepared=[r for r in rows if r['source_status']=='MANUFACTURER_FACTS_VERIFIED' and r.get('photo_status')=='DOWNLOADED_AWAITING_VISUAL_REVIEW']
    print('AVITO_SOURCE24_PRIMARY_REVIEW',json.dumps({'items':rows,'facts_verified':sum(r['source_status']=='MANUFACTURER_FACTS_VERIFIED' for r in rows),'ready_for_visual_review':len(prepared)},ensure_ascii=False),flush=True)
    for start in range(0,len(prepared),20):
        part=prepared[start:start+20];canvas=Image.new('RGB',(1200,240*((len(part)+4)//5)),'white');draw=ImageDraw.Draw(canvas)
        for i,r in enumerate(part):
            im=Image.open(D/(r['article']+'-contact.jpg'));im.thumbnail((230,205));x=i%5*240;y=i//5*240;canvas.paste(im,(x,y+30));draw.text((x+3,y+3),r['article'],fill='black')
        buffer=io.BytesIO();canvas.save(buffer,format='JPEG',quality=72);print('CONTACT_SOURCE24_PAGE',json.dumps({'page':start//20+1,'articles':[r['article'] for r in part],'image_base64':base64.b64encode(buffer.getvalue()).decode()}),flush=True)
