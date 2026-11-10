#!/usr/bin/env python3
"""Prepare an append-only Avito extension from reviewed first-party evidence.

Never publishes. The workflow stages hash-pinned images, checks their public
bytes, then atomically commits XML, approved archive and retail-only prices.
"""
import argparse,copy,csv,hashlib,html as html_std,io,json,os,re,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote,urlparse
from xml.etree import ElementTree as ET
import requests
from bs4 import BeautifulSoup
from PIL import Image
from avito_active_feed_refresh import supplier_products,add_raw_source_costs,key,price_decimal,seller_sku
from avito_irkutsk import load_fresh_price
from avito_pricing import progressive_price
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import rpc,zeep_client,choose_delivery,retry_transient
from update_prices import load_config

REPO='ROJANGG/rossko-drom-lensk'
BRANCH='avito-irkutsk-feed'
TYPES={'Колодки барабанные':('Колодки барабанные','новые','Тормозная система'),
       'Радиаторы кондиционера':('Радиатор кондиционера','новый','Система охлаждения'),
       'Свечи накала':('Свеча накаливания','новая','Двигатель')}
PAGE_HOSTS={'stellox':{'ru.stellox.com'},'lynx':{'ecatalogue.lynxauto.jp'},
            'transmaster':{'transmaster.ru'},'startvolt':{'startvolt.com'},
            'ngk':{'www.ngkpartfinder.co.uk'},'febest':{'febest.de'}}
IMAGE_HOSTS={'ru.stellox.com','ecatalogue.lynxauto.jp','api.transmaster.ru',
             's3.carvilleshop.ru','cdn.carvilleshop.ru','www.ngkpartfinder.co.uk','static.febest.de'}
def canon(v):return re.sub(r'[^A-Z0-9]','',str(v).upper())
def stable_id(record):
    return 'irk-'+hashlib.sha256(f"{record['category']}|{record['brand'].casefold()}|{record['article'].casefold()}".encode()).hexdigest()[:22]
def get(url,referer=None):
    if not url.startswith('https://'):raise ValueError('Non-HTTPS source')
    headers={'User-Agent':'Mozilla/5.0'}
    if referer:headers['Referer']=referer
    response=requests.get(url,headers=headers,timeout=(10,35))
    response.raise_for_status()
    if len(response.content)>8_000_000:raise ValueError('Oversize manufacturer response')
    return response
def validate_manifest(manifest):
    scope=manifest['scope_skus'];records=manifest['items']
    approved={key(x['brand'],x['article']) for x in scope}
    if len(scope)!=95 or len(approved)!=95 or not 1<=len(records)<=95:
        raise ValueError('Unexpected owner-approved review scope')
    keys=set();photos=set()
    for r in records:
        k=key(r['brand'],r['article'])
        if k not in approved or k in keys or r['category'] not in TYPES:
            raise ValueError('Unapproved/duplicate exact SKU')
        if (not r.get('exact_sku_verified') or not r.get('oem') or not r.get('fitment')
                or r.get('photo_review')!='ACTUAL_EXACT_PRODUCT_PHOTO_VERIFIED'):
            raise ValueError('Incomplete manual manufacturer review')
        if urlparse(r['manufacturer_page']).hostname not in PAGE_HOSTS[r['source_kind']]:
            raise ValueError('Wrong manufacturer page host')
        if len(r.get('images',[]))!=1:raise ValueError('Expected one reviewed exact-product photo')
        im=r['images'][0]
        if (urlparse(im['url']).hostname not in IMAGE_HOSTS or not re.fullmatch('[a-f0-9]{64}',im['sha256'])
                or im['sha256'] in photos):raise ValueError('Unapproved/reused photo')
        photos.add(im['sha256']);keys.add(k)
    return records
def load_source_cache(record,base=None,now=None):
    """Only today's independently captured NGK primary-source facts, max 3h."""
    cache=record.get('source_cache')
    if record['source_kind']!='ngk' or not cache:raise ValueError('No verified primary-source cache')
    if not re.fullmatch(r'input/avito-ngk-source-cache/[A-Z0-9]+\.json',cache['path']):raise ValueError('Invalid source-cache path')
    path=(base or Path(__file__).parent)/cache['path'];raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=cache['sha256']:raise ValueError('Primary-source cache hash mismatch')
    proof=json.loads(raw);stamp=datetime.fromisoformat(proof['verified_at_utc']);now=now or datetime.now(timezone.utc)
    if stamp.tzinfo is None or not timedelta(0)<=now-stamp<=timedelta(hours=3):raise ValueError('Primary-source cache expired')
    if (canon(proof['article'])!=canon(record['article']) or proof['manufacturer_page']!=record['manufacturer_page']
            or proof['oem_source']!=record['oem_source'] or proof['photo_sha256']!=record['images'][0]['sha256']):
        raise ValueError('Primary-source cache identity mismatch')
    photo_path=path.parent/proof['photo_filename']
    if photo_path.parent!=path.parent or hashlib.sha256(photo_path.read_bytes()).hexdigest()!=proof['photo_sha256']:
        raise ValueError('Cached manufacturer photo hash mismatch')
    return proof,photo_path
def validate_source(record,page,extra_pages=None):
    soup=BeautifulSoup(page,'html.parser');sku=canon(record['article']);kind=record['source_kind']
    txt=soup.get_text(' ',strip=True)
    if kind=='stellox':
        heading=soup.find('h1')
        if not heading or sku not in canon(heading.get_text(' ',strip=True)):raise ValueError('Manufacturer SKU changed')
        block=soup.select_one('.product-oe')
        numbers={canon(x.get_text()) for x in block.select('.product-usability__item .body-text2')} if block else set()
        if canon(record['oem']) not in numbers:raise ValueError('OE reference changed')
    elif kind=='lynx':
        label=soup.select_one('input[name="product_model"]')
        if label is None or canon(label.get('value',''))!=sku:raise ValueError('Manufacturer SKU changed')
        block=soup.select_one('#pcard-oeno')
        numbers={canon(cells[1].get_text()) for row in block.select('tr') if len(cells:=row.find_all('td',recursive=False))>=2} if block else set()
        if canon(record['oem']) not in numbers:raise ValueError('OE reference changed')
    elif kind=='startvolt':
        label=soup.select_one('[itemprop="sku"]')
        if label is None or canon(label.get('content',''))!=sku:raise ValueError('Manufacturer SKU changed')
        blocks=[x for x in soup.select('.product__codes-item') if x.find('h3') and x.find('h3').get_text(' ',strip=True)=='OEM номер']
        if not blocks or canon(record['oem']) not in {canon(x.get_text()) for x in blocks[0].select('.product__codes_row_oem')}:
            raise ValueError('OE reference changed')
    elif kind=='transmaster':
        heading=soup.find('h1')
        if not heading or sku not in canon(heading.get_text()):raise ValueError('Manufacturer SKU changed')
        if canon(record['oem']) not in {canon(x.get_text()) for x in soup.find_all('button')}:raise ValueError('OE reference changed')
    elif kind=='febest':
        if 'АРТИКУЛ'+sku not in re.sub(r'[^A-ZА-Я0-9]','',txt.upper()):raise ValueError('Manufacturer SKU changed')
        values=soup.select('#oem_select option')
        if canon(record['oem']) not in {canon(x.get_text()) for x in values}:raise ValueError('OE reference changed')
    elif kind=='ngk':
        if 'PARTNO'+sku not in canon(txt):raise ValueError('Manufacturer SKU changed')
        cross=BeautifulSoup((extra_pages or {}).get(record['oem_source'],''),'html.parser')
        matched=False
        for tr in cross.select('tbody tr'):
            cells=[x.get_text(' ',strip=True) for x in tr.find_all('td',recursive=False)]
            if len(cells)>=4 and canon(cells[2])==canon(record['oem']) and canon(cells[3])==sku:matched=True
        if not matched:raise ValueError('NGK original OE-to-product mapping changed')
    else:raise ValueError('Unsupported manufacturer')
    decoded=unquote(html_std.unescape(page)).replace('\\/','/')
    if urlparse(record['images'][0]['url']).path not in decoded:
        raise ValueError('Photo absent from exact manufacturer product page')
    fit_text=txt+' '+' '.join(BeautifulSoup(x,'html.parser').get_text(' ',strip=True) for x in (extra_pages or {}).values())
    for token in record.get('fitment_tokens',[]):
        if canon(token) not in canon(fit_text):raise ValueError('Manufacturer applicability changed')
    return True
def prepare_photo(record,place):
    extra={};cache_photo=None;verification='current_manufacturer_http'
    try:
        for url in set(record.get('fitment_sources',[])+[record['oem_source']]):
            if url!=record['manufacturer_page']:
                if urlparse(url).hostname not in PAGE_HOSTS[record['source_kind']]:raise ValueError('Foreign evidence host')
                extra[url]=get(url).text
        page=get(record['manufacturer_page']).text
    except requests.RequestException:
        proof,cache_photo=load_source_cache(record)
        page=proof['product_html'];extra={record['oem_source']:proof['oem_html']}
        verification='same_day_primary_source_cache_max_3h'
    validate_source(record,page,extra)
    image=record['images'][0]
    try:raw=get(image['url'],record['manufacturer_page']).content
    except requests.RequestException:
        if cache_photo is None:_,cache_photo=load_source_cache(record)
        raw=cache_photo.read_bytes();verification='same_day_primary_source_cache_max_3h'
    if hashlib.sha256(raw).hexdigest()!=image['sha256']:raise ValueError('Reviewed photo bytes changed')
    im=Image.open(io.BytesIO(raw));im.load()
    if list(im.size)!=[image['width'],image['height']] or min(im.size)<200:raise ValueError('Photo dimensions changed')
    ext={'JPEG':'jpg','PNG':'png','WEBP':'webp'}.get(im.format)
    if not ext:raise ValueError('Unsupported photo format')
    name=stable_id(record)+'-'+image['sha256'][:12]+'.'+ext
    (place/name).write_bytes(raw)
    return {'filename':name,'sha256':image['sha256'],'public_url':f'https://raw.githubusercontent.com/{REPO}/{BRANCH}/avito-images/{name}','source_verification':verification}
def make_ad(record,retail,photo,address):
    noun,suffix,group=TYPES[record['category']]
    if record.get('pack_quantity'):
        noun,suffix='Свечи накала','новые'
    title=f"{noun} {record['brand']} {record['article']} {suffix}"
    if len(title)>50:raise ValueError('Avito title exceeds 50 characters')
    details=f"{noun}, производитель {record['brand']}, артикул {record['article']}.\nСостояние: новое.\n"
    if record.get('pack_quantity'):details+=f"Комплект: {record['pack_quantity']} шт. Цена за комплект.\n"
    details+='OEM: '+record['oem']+'.\n'+record['fitment']+'\n'
    details+=f"Доступно к самовывозу в Иркутске.\nСамовывоз: {address}.\nНаличие перед приездом уточняйте, совместимость проверяйте по VIN."
    data={'Id':stable_id(record),'Category':'Запчасти и аксессуары','GoodsType':'Запчасти',
          'AdType':'Товар приобретен на продажу','ProductType':'Для автомобилей',
          'SparePartType':group,'OEM':canon(record['oem']),'Title':title,'Description':details,
          'Address':address,'Price':str(retail),'Condition':'Новое','Availability':'В наличии','Brand':record['brand']}
    ad=ET.Element('Ad')
    for k,v in data.items():ET.SubElement(ad,k).text=v
    ET.SubElement(ET.SubElement(ad,'Images'),'Image',url=photo['public_url'])
    ET.indent(ad,space='  ',level=1)
    return ad
def append_ads(original,ads):
    root=ET.fromstring(original);before=root.findall('Ad');old=[ET.tostring(x) for x in before]
    ids={x.findtext('Id') for x in before}
    if None in ids or len(ids)!=len(before):raise ValueError('Existing duplicate IDs')
    for ad in ads:
        if ad.findtext('Id') in ids:raise ValueError('Duplicate extension ID')
        root.append(copy.deepcopy(ad));ids.add(ad.findtext('Id'))
    result=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    parsed=ET.fromstring(result).findall('Ad')
    if [ET.tostring(x) for x in parsed[:len(old)]]!=old:raise ValueError('Existing ad attributes changed')
    if len(parsed)>300:raise ValueError('Approved catalogue upper bound exceeded')
    return result
def build(args):
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'));records=validate_manifest(manifest)
    args.out.mkdir(parents=True,exist_ok=True);photo_dir=args.out/'avito-images';photo_dir.mkdir(exist_ok=True)
    current=args.live.read_bytes();archive=args.archive.read_bytes();live=ET.fromstring(current);historic=ET.fromstring(archive)
    old=live.findall('Ad');prior=historic.findall('Ad')
    if not 150<=len(old)<=len(prior)<=300 or live.attrib!=historic.attrib:raise ValueError('Unexpected starting catalogue')
    old_ids={x.findtext('Id') for x in old};archive_ids={x.findtext('Id') for x in prior}
    if len(old_ids)!=len(old) or len(archive_ids)!=len(prior) or not old_ids<=archive_ids:raise ValueError('Unsafe starting IDs')
    existing={seller_sku(x)[0] for x in prior};records=[r for r in records if key(r['brand'],r['article']) not in existing]
    config=load_config(args.config);book=load_fresh_price(config,args.config.parent,2)
    try:source=supplier_products(book,config);add_raw_source_costs(book,source)
    finally:book.close()
    skipped=[];prepared=[]
    def prepare(r):
        try:return (r,prepare_photo(r,photo_dir),None)
        except Exception as e:return (r,None,'manufacturer_evidence_'+type(e).__name__+': '+str(e)[:180])
    with ThreadPoolExecutor(max_workers=5) as pool:
        for r,photo,error in pool.map(prepare,records):
            if error:skipped.append({'brand':r['brand'],'article':r['article'],'reason':error})
            else:prepared.append((r,photo))
    credentials={name:(os.environ.get('ROSSKO_API_'+name) or '').strip() for name in ['KEY1','KEY2']}
    if not all(credentials.values()):raise RuntimeError('Required ROSSKO secrets missing')
    checkout=retry_transient(lambda:rpc(zeep_client('GetCheckoutDetails'),'GetCheckoutDetails',credentials),attempts=3,base_delay=1.3)
    delivery,mode=choose_delivery(checkout)
    if not delivery:raise ValueError('Account pickup mode not verified')
    api=zeep_client('GetSearch');ads=[];additions=[]
    with args.retail.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f,delimiter=';');columns=reader.fieldnames;price_rows=list(reader)
    previous_map={key(x['brand'],x['article']):i for i,x in enumerate(price_rows)}
    if len(previous_map)!=len(price_rows) or len(price_rows)<700:raise ValueError('Invalid original retail map')
    addresses={x.findtext('Address') for x in old}
    if len(addresses)!=1 or None in addresses:raise ValueError('Pickup location ambiguous')
    address=next(iter(addresses))
    for record,photo in prepared:
        k=key(record['brand'],record['article']);stock=source.get(k)
        if not stock or stock['Группа']!=record['category']:
            skipped.append({'brand':record['brand'],'article':record['article'],'reason':'no_current_Irkutsk_zero_day_stock'});continue
        cost=price_decimal(stock.get('_source_list_price'))
        if cost is None or cost<=0:raise ValueError('Invalid current supplier source price')
        item={'category':record['category'],'brand':record['brand'],'article':record['article'],
              'description':record['fitment'],'supplier_list_price_rub':str(cost),
              'supplier_stock':int(stock['Остаток РОССКО']),'supplier_delivery_days':0}
        quote=audit_one(api,credentials,delivery,item)
        if quote.get('status')!='опт_Иркутск_подтвержден' or not quote.get('api_irkutsk_stock_ids'):
            skipped.append({'brand':record['brand'],'article':record['article'],'reason':'fresh_personal_API_not_confirmed'});continue
        buying=price_decimal(quote.get('api_irkutsk_same_delivery_price_rub'))
        if (buying is None or not cost/Decimal(10)<=buying<=cost*Decimal(2)
                or price_decimal(quote.get('supplier_list_price_rub'))!=cost):raise ValueError('Implausible/mismatched API quote')
        retail=progressive_price(buying);ad=make_ad(record,retail,photo,address);ads.append(ad)
        additions.append({'id':ad.findtext('Id'),'brand':record['brand'],'article':record['article'],'category':record['category'],'retail':retail,'photo':photo})
        retail_row={c:'' for c in columns};retail_row.update(brand=record['brand'],article=record['article'],supplier_price=str(cost),supplier_delivery_days='0',drom_retail='0',avito_retail=str(retail))
        if k in previous_map:
            index=previous_map[k];retail_row['drom_retail']=price_rows[index].get('drom_retail','0');price_rows[index]=retail_row
        else:previous_map[k]=len(price_rows);price_rows.append(retail_row)
        time.sleep(0.4)
    (args.out/'AVITO_EXTENSION_LIVE_CANDIDATE.xml').write_bytes(append_ads(current,ads))
    (args.out/'AVITO_EXTENSION_APPROVED_CANDIDATE.xml').write_bytes(append_ads(archive,ads))
    with (args.out/'avito-verified-retail-prices.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,delimiter=';');writer.writeheader();writer.writerows(price_rows)
    report={'as_of_utc':datetime.now(timezone.utc).isoformat(),'before':len(old),'after':len(old)+len(ads),
            'approved_before':len(prior),'approved_after':len(prior)+len(ads),'scope_count':95,
            'source_review_approved':len(manifest['items']),'added_count':len(ads),'added':additions,'skipped':skipped,
            'blocked_source_review':manifest['blocked'],'all_original_ads_preserved':True,
            'private_API_costs_published':False,'checkout_mode':mode,'publication_performed':False}
    (args.out/'avito-verified-extension-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('AVITO_EXTENSION_CANDIDATE',json.dumps({k:report[k] for k in ['before','after','added_count','all_original_ads_preserved']},ensure_ascii=False),flush=True)
    print('SKIPPED',json.dumps(skipped,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['config','live','archive','retail','manifest','out']:p.add_argument('--'+name,type=Path,required=True)
    build(p.parse_args())
