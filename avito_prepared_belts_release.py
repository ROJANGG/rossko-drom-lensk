"""Build an append-only belt candidate; workflow owns public-photo checks/push."""
import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urljoin
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from PIL import Image
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts, META
from avito_reviewed_drive_belts import load_reviewed_belts
from avito_belt_release import prepare_photo as lynx_photo, make_ad as lynx_ad
from avito_active_feed_refresh import key, seller_sku, supplier_products, add_raw_source_costs, price_decimal, APPROVED_CATALOG_LIMIT
from avito_irkutsk import load_fresh_price
from avito_pricing import progressive_price
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import zeep_client, rpc, choose_delivery, retry_transient
from update_prices import load_config

PUBLIC = 'https://raw.githubusercontent.com/ROJANGG/rossko-drom-lensk/avito-irkutsk-feed/avito-images/'
def canon(v):
    return re.sub('[^A-Z0-9]', '', str(v).upper())

def stable_id(r):
    return 'irk-' + hashlib.sha256((r['category']+'|'+r['brand'].casefold()+'|'+r['article'].casefold()).encode()).hexdigest()[:22]

def text(node):
    return ' '.join(node.get_text(' ', strip=True).split())

def validate_source(r, product, fitment=None):
    page=BeautifulSoup(product,'html.parser');label=page.select_one('[itemprop="mpn"][data-model]')
    if label is None or canon(label['data-model'])!=canon(r['article']):raise ValueError('Exact SUFIX MPN changed')
    heading=page.select_one('h1')
    label_text=text(heading) if heading else ''
    if r['category']=='Радиаторы охлаждения':
        if not re.search(r'радиатор.*охлажд',label_text,re.I) or re.search('кондицион',label_text,re.I):raise ValueError('SUFIX cooling radiator category mismatch')
    elif r['category']=='Радиаторы кондиционера':
        if not re.search(r'радиатор.*кондицион',label_text,re.I):raise ValueError('SUFIX AC radiator category mismatch')
    elif r['category']=='ШРУС':
        if not re.search(r'^ШРУС\b|^Шарнир.*равных.*скорост',label_text,re.I):raise ValueError('SUFIX CV joint category mismatch')
    else:
        if not re.search(r'ремень',label_text,re.I):raise ValueError('SUFIX product category changed')
        is_timing=bool(re.search('грм',label_text,re.I))
        if is_timing != (r['category']=='Ремни ГРМ'):raise ValueError('SUFIX drive/timing category mismatch')
    refs=[]
    for tr in page.select('table.pcard-analog-bottom tr'):
        cells=tr.find_all('td',recursive=False)
        if len(cells)>=2:refs.append((canon(text(cells[0])),text(cells[1]).upper()))
    if (r['oem'],r['OEM_make']) not in refs:raise ValueError('Exact automaker reference changed')
    actual=None
    for group in page.select('.applicabilit-group'):
        title=group.select_one('.applicabilit-group-title')
        if title is None or text(title).upper()!=r['applicability_make']:continue
        actual=[]
        for link in group.select('.applicabilit-item a'):
            model=link.select_one('.model');mod=link.select_one('.mofif')
            if model is not None:actual.append({'model':text(model),'modification':text(mod) if mod else '', 'url':urljoin(r['manufacturer_page'],link.get('href',''))})
    if not actual or actual[:len(r['fitment_rows'])]!=r['fitment_rows']:raise ValueError('SUFIX applicability changed')
    if r['photo_url'] not in {urljoin(r['manufacturer_page'],x['href']) for x in page.select('a.lightboxgroup[href]')}:raise ValueError('Exact photo binding changed')
    return True

def get(url):
    response = requests.get(url, timeout=(5, 12))
    response.raise_for_status()
    if len(response.content) > 8_000_000:
        raise ValueError('Oversize source response')
    return response.content

def prepare_sufix_photo(r, place):
    page = get(r['manufacturer_page'])
    validate_source(r, page)
    raw = get(r['photo_url'])
    if hashlib.sha256(raw).hexdigest() != r['photo_sha256']:
        raise ValueError('Visually reviewed original photo bytes changed')
    image = Image.open(io.BytesIO(raw)); image.load()
    if list(image.size) != r['photo_dimensions'] or min(image.size) < 200:
        raise ValueError('Photo dimensions changed')
    ext = {'JPEG': 'jpg', 'PNG': 'png'}.get(image.format)
    if not ext:
        raise ValueError('Unsupported original photo format')
    name = stable_id(r)+'-'+r['photo_sha256'][:12]+'.'+ext
    (place/name).write_bytes(raw)
    return {'filename': name, 'sha256': r['photo_sha256'], 'public_url': PUBLIC+name,
            'manufacturer_page_sha256': hashlib.sha256(page).hexdigest(),
            'fitment_page_sha256': hashlib.sha256(page).hexdigest(),
            'verified_at_utc': datetime.now(timezone.utc).isoformat()}

def make_sufix_ad(r, retail, photo, address):
    prefix,part,detail_tag,detail_value=META[r['category']]
    title = prefix+' '+r['brand']+' '+r['article']+' новый'
    if len(title) > 50:
        raise ValueError('Title exceeds Avito limit')
    values = {'Id': stable_id(r), 'Category': 'Запчасти и аксессуары', 'GoodsType': 'Запчасти',
              'AdType': 'Товар приобретен на продажу', 'ProductType': 'Для автомобилей',
              'SparePartType': part, 'OEM': r['oem'],
              'Title': title, 'Description': prefix+'. Производитель: '+r['brand']+'. Артикул: '+r['article']+'.\nСостояние: новое. Цена за одну штуку.\nOEM: '+r['oem']+'.\nПрименяемость по каталогу производителя, выборка: '+r['fitment']+'.\nСамовывоз: '+address+'.\nПеред покупкой сверьте OEM и VIN. Наличие перед приездом уточняйте.',
              'Address': address, 'Price': str(retail), 'Condition': 'Новое', 'Availability': 'В наличии', 'Brand': r['brand']}
    if detail_tag:
        ordered={}
        for name,value in values.items():
            ordered[name]=value
            if name=='SparePartType':ordered[detail_tag]=detail_value
        values=ordered
    if r['category']=='ШРУС':values['Description']=values['Description'].replace('Цена за одну штуку.','Цена за один ШРУС. Комплектацию сверяйте по артикулу перед заказом.')
    ad = ET.Element('Ad')
    for k, v in values.items():
        ET.SubElement(ad, k).text = v
    ET.SubElement(ET.SubElement(ad, 'Images'), 'Image', url=photo['public_url'])
    seller_sku(ad)
    ET.indent(ad, space='  ', level=1)
    return ad

def prepare_photo(r,place):
    return lynx_photo(r,place) if r['brand']=='LYNXauto' else prepare_sufix_photo(r,place)
def make_ad(r,retail,photo,address):
    return lynx_ad(r,retail,photo,address) if r['brand']=='LYNXauto' else make_sufix_ad(r,retail,photo,address)

def append_ads(original, ads):
    root = ET.fromstring(original)
    old = [ET.tostring(a) for a in root.findall('Ad')]
    ids = {a.findtext('Id') for a in root.findall('Ad')}
    if None in ids or len(ids) != len(old):
        raise ValueError('Invalid starting IDs')
    for a in ads:
        if a.findtext('Id') in ids:
            raise ValueError('Duplicate added ID')
        ids.add(a.findtext('Id')); root.append(copy.deepcopy(a))
    raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    parsed = ET.fromstring(raw).findall('Ad')
    if len(parsed) > APPROVED_CATALOG_LIMIT or old != [ET.tostring(a) for a in parsed[:len(old)]]:
        raise ValueError('Unsafe append-only transition')
    return raw

def account_retail(quote, cost):
    buying=price_decimal(quote.get('api_irkutsk_same_delivery_price_rub'))
    if buying is None or not cost/Decimal(10)<=buying<=cost*Decimal(2) or price_decimal(quote.get('supplier_list_price_rub'))!=cost:return None
    return progressive_price(buying)

def filter_selection(records,path):
    selected=json.loads(path.read_text())['items']
    keys={key(r['brand'],r['article']):r['category'] for r in selected}
    known={key(r['brand'],r['article']):r['category'] for r in records}
    if not 1<=len(selected)<=100 or len(keys)!=len(selected) or any(known.get(k)!=v for k,v in keys.items()):raise ValueError('Invalid exact release selection')
    return [r for r in records if key(r['brand'],r['article']) in keys]

def build(args):
    records = load_reviewed_sufix_belts(args.manifest) + load_reviewed_belts(args.lynx_manifest)
    if args.selection is not None:records=filter_selection(records,args.selection)
    scope_count = len(records)
    args.out.mkdir(parents=True, exist_ok=True)
    images = args.out/'avito-images'; images.mkdir(exist_ok=True)
    current, archive = args.live.read_bytes(), args.archive.read_bytes()
    live, historic = ET.fromstring(current), ET.fromstring(archive)
    old, prior = live.findall('Ad'), historic.findall('Ad')
    if not 150 <= len(old) <= len(prior) <= APPROVED_CATALOG_LIMIT or live.attrib != historic.attrib:
        raise ValueError('Unexpected starting catalogue')
    ids, archive_ids = {a.findtext('Id') for a in old}, {a.findtext('Id') for a in prior}
    if None in ids or None in archive_ids or len(ids) != len(old) or len(archive_ids) != len(prior) or not ids <= archive_ids:
        raise ValueError('Unsafe original IDs')
    existing = {seller_sku(a)[0] for a in prior}
    records = [r for r in records if key(r['brand'], r['article']) not in existing]
    config = load_config(args.config); book = load_fresh_price(config, args.config.parent, 2)
    try:
        source = supplier_products(book, config); add_raw_source_costs(book, source)
    finally:
        book.close()
    skipped, prepared = [], []
    def prepare(r):
        try:
            return r, prepare_photo(r, images), None
        except Exception as e:
            return r, None, 'manufacturer_evidence_'+type(e).__name__
    eligible = []
    for r in records:
        if not r.get('package_unit_verified'):
            skipped.append({'brand':r['brand'],'article':r['article'],'reason':'package_unit_confirmation_required'});continue
        stock = source.get(key(r['brand'], r['article']))
        if not stock or stock['Группа'] != r['category']:
            skipped.append({'brand': r['brand'], 'article': r['article'], 'reason': 'no_current_Irkutsk_zero_day_stock'})
        else:
            eligible.append(r)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for i, (r, photo, error) in enumerate(pool.map(prepare, eligible), 1):
            if error:
                skipped.append({'brand': r['brand'], 'article': r['article'], 'reason': error})
            else:
                prepared.append((r, photo))
            if i % 10 == 0:
                print('SUFIX_DRIVE_SOURCE_PROGRESS', i, len(eligible), flush=True)
    credentials = {k: (os.environ.get('ROSSKO_API_'+k) or '').strip() for k in ('KEY1', 'KEY2')}
    if not all(credentials.values()):
        raise ValueError('Required account secrets missing')
    checkout = retry_transient(lambda: rpc(zeep_client('GetCheckoutDetails'), 'GetCheckoutDetails', credentials), attempts=3)
    delivery, mode = choose_delivery(checkout)
    if not delivery:
        raise ValueError('Account pickup not verified')
    with args.retail.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';'); columns = reader.fieldnames; prices = list(reader)
    indices = {key(r['brand'], r['article']): i for i, r in enumerate(prices)}
    if len(indices) != len(prices) or len(prices) < 700:
        raise ValueError('Invalid previous retail map')
    addresses = {a.findtext('Address') for a in old}
    if len(addresses) != 1 or None in addresses:
        raise ValueError('Ambiguous address')
    address = next(iter(addresses)); client = zeep_client('GetSearch')
    ads, added = [], []
    for r, photo in prepared:
        k = key(r['brand'], r['article']); stock = source[k]; cost = price_decimal(stock.get('_source_list_price'))
        if cost is None or cost <= 0:
            raise ValueError('Invalid source price')
        item = {'category': r['category'], 'brand': r['brand'], 'article': r['article'], 'description': r['fitment'],
                'supplier_list_price_rub': str(cost), 'supplier_stock': int(stock['Остаток РОССКО']), 'supplier_delivery_days': 0}
        quote = audit_one(client, credentials, delivery, item)
        if quote.get('status') != 'опт_Иркутск_подтвержден' or not quote.get('api_irkutsk_stock_ids'):
            skipped.append({'brand': r['brand'], 'article': r['article'], 'reason': 'fresh_personal_API_not_confirmed', 'api_status': str(quote.get('status', 'unknown'))})
        else:
            retail=account_retail(quote,cost)
            if retail is None:
                skipped.append({'brand':r['brand'],'article':r['article'],'reason':'fresh_personal_API_price_mismatch'})
                time.sleep(0.6)
                continue
            ad = make_ad(r, retail, photo, address); ads.append(ad)
            added.append({'id': ad.findtext('Id'), 'brand': r['brand'], 'article': r['article'], 'category': r['category'], 'retail': retail, 'photo': photo, 'API_checked_at_utc': datetime.now(timezone.utc).isoformat()})
            row = {c: '' for c in columns}; row.update(brand=r['brand'], article=r['article'], supplier_price=str(cost), supplier_delivery_days='0', drom_retail='0', avito_retail=str(retail))
            if k in indices:
                row['drom_retail'] = prices[indices[k]].get('drom_retail', '0'); prices[indices[k]] = row
            else:
                indices[k] = len(prices); prices.append(row)
        time.sleep(0.6)
    (args.out/'AVITO_EXTENSION_LIVE_CANDIDATE.xml').write_bytes(append_ads(current, ads))
    (args.out/'AVITO_EXTENSION_APPROVED_CANDIDATE.xml').write_bytes(append_ads(archive, ads))
    with (args.out/'avito-verified-retail-prices.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=';'); writer.writeheader(); writer.writerows(prices)
    report = {'as_of_utc': datetime.now(timezone.utc).isoformat(), 'before': len(old), 'after': len(old)+len(ads), 'approved_before': len(prior), 'approved_after': len(prior)+len(ads),
              'scope_count': scope_count, 'added_count': len(ads), 'added': added, 'skipped': skipped, 'all_original_ads_preserved': True, 'private_API_costs_published': False, 'checkout_mode': mode, 'publication_performed': False}
    (args.out/'avito-verified-extension-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('PREPARED_BELTS_CANDIDATE', json.dumps(report, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('config', 'live', 'archive', 'retail', 'manifest', 'lynx-manifest', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--selection',type=Path)
    build(p.parse_args())


