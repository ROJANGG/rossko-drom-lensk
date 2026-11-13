"""Read-only, thirty exact heater SKUs. Never writes XML or buying prices."""
import json,os,re
from datetime import datetime,timezone
from pathlib import Path
from avito_irkutsk import load_fresh_price,zero_days
from update_prices import load_config
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import zeep_client,rpc,choose_delivery,retry_transient,decimal,number
from avito_pricing import progressive_price
ALLOWED={'RH0190', 'RH0130', 'RH0226', 'RH0229', 'RH0343', 'RH0066', 'RH0346', 'KRH1025EB', 'RH0283', 'LRH3038', 'RH0161', 'RH0333', 'RH0301', 'RH0340', 'RH0341', 'RH0292', 'RH0350', 'RH0348', 'RH0249', 'LRH3042', 'RH0300', 'RH0336', 'RH0328', 'RH0331', 'RH0009', 'RH0102', 'RH0214', 'RH0162', 'RH0115', 'RH0084'}
def canon(v):return re.sub('[^A-Z0-9]','',str(v or '').upper())
def main():
    records=json.loads(Path('input/avito_heater_batch02_20261113.json').read_text())['items']
    if len(records)!=30 or {r['article'] for r in records}!=ALLOWED or any(r['brand'] not in ('Luzar','LYNXauto','Krauf') for r in records):raise ValueError('Unexpected batch scope')
    config=load_config(Path('config.json'));book=load_fresh_price(config,Path('.'),2)
    found={}
    try:
        rows=book.active.iter_rows(values_only=True);h={str(x):i for i,x in enumerate(next(rows))}
        for row in rows:
            article=canon(row[h['Артикул']])
            if article not in ALLOWED:continue
            expected=next(r for r in records if r['article']==article)
            if canon(row[h['Бренд']])!=canon(expected['brand']):continue
            if str(row[h['Номенклатура']])!=expected['supplier_nomenclature']:raise ValueError('Fresh supplier identity changed')
            if not zero_days(row[h['Срок поставки, дн.']]) or number(row[h['Наличие']],0)<=0:continue
            cost=decimal(row[h['Цена, руб.']])
            if cost is None or cost<=0:continue
            found[article]={'category':'Радиаторы печки','brand':expected['brand'],'article':article,'supplier_delivery_days':0,'supplier_stock':number(row[h['Наличие']],0),'supplier_list_price_rub':str(cost)}
    finally:book.close()
    results=[]
    creds={k:(os.environ.get('ROSSKO_API_'+k) or '').strip() for k in ('KEY1','KEY2')}
    if not all(creds.values()):raise ValueError('Missing account credentials')
    checkout=retry_transient(lambda:rpc(zeep_client('GetCheckoutDetails'),'GetCheckoutDetails',creds),attempts=3)
    delivery,mode=choose_delivery(checkout)
    if not delivery:raise ValueError('Account delivery not confirmed')
    client=zeep_client('GetSearch')
    for r in records:
        item=found.get(r['article']);out={'brand':r['brand'],'article':r['article'],'category':'Радиаторы печки','checked_at_utc':datetime.now(timezone.utc).isoformat()}
        if item:
            quote=audit_one(client,creds,delivery,item);out['api_status']=quote.get('status');out['supplier_zero_day_stock']=item['supplier_stock']
            if quote.get('status')=='опт_Иркутск_подтвержден' and quote.get('api_irkutsk_stock_ids'):
                cost=decimal(quote.get('api_irkutsk_same_delivery_price_rub'))
                if cost is not None and cost>0:out['avito_retail_rub']=progressive_price(cost)
        else:out['api_status']='NO_FRESH_SUPPLIER_ZERO_DAY_STOCK'
        results.append(out)
    report={'batch_size':30,'results':results,'no_XML_changes':True,'no_private_buying_prices_written':True,'publication_performed':False}
    Path('review').mkdir(exist_ok=True);Path('review/heater-batch02-api-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('AVITO_HEATER_BATCH_REVIEW',json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
