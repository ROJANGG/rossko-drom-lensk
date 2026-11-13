"""Bounded first-pass API gate for 100 exact, newly selected expansion SKUs.

Never publishes XML. Buying prices and credentials are never written.
"""
import hashlib,json,os,re,time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from avito_irkutsk import load_fresh_price,zero_days
from update_prices import load_config
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import zeep_client,rpc,choose_delivery,retry_transient,decimal,number
from avito_pricing import progressive_price
SCOPE_SHA256='68486e9a8e91b52503abff15834a03529fcfa284f8da08e48e373897244d1388'
def canon(v):return re.sub('[^A-Z0-9]','',str(v or '').upper())
def validate(records):
    scope=[[r['category'],r['brand'],r['article'],r['supplier_nomenclature']] for r in records]
    digest=hashlib.sha256(json.dumps(scope,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if len(records)!=100 or digest!=SCOPE_SHA256:raise ValueError('Unexpected exact 100-SKU scope')
    if len({(canon(r['brand']),canon(r['article'])) for r in records})!=100:raise ValueError('Duplicate SKU')
    if any(r['category'] not in ('Радиаторы печки','Комплекты цепи ГРМ') for r in records):raise ValueError('Unexpected category')
def review(records,found,client,creds,delivery,sleep=time.sleep):
    results=[];attempts=0;transient_streak=0
    for index,r in enumerate(records):
        k=(canon(r['brand']),canon(r['article']));item=found.get(k)
        out={'brand':r['brand'],'article':r['article'],'category':r['category'],'checked_at_utc':datetime.now(timezone.utc).isoformat()}
        if transient_streak>=5:out['api_status']='NOT_CHECKED_API_TEMPORARY_FAILURE_LIMIT'
        elif item:
            quote=audit_one(client,creds,delivery,item);attempts+=1;status=str(quote.get('status','UNKNOWN'));out['api_status']=status;out['supplier_zero_day_stock']=item['supplier_stock']
            transient_streak=transient_streak+1 if status.startswith('сбой_API_') else 0
            if status=='опт_Иркутск_подтвержден' and quote.get('api_irkutsk_stock_ids'):
                cost=decimal(quote.get('api_irkutsk_same_delivery_price_rub'))
                if cost is not None and cost>0:out['avito_retail_rub']=progressive_price(cost)
            sleep(0.35)
        else:out['api_status']='NO_FRESH_SUPPLIER_ZERO_DAY_STOCK'
        results.append(out)
        if (index+1)%20==0:print('AVITO_BATCH03_PROGRESS',json.dumps({'processed':index+1,'scope':100,'API_requests':attempts,'status_counts':dict(Counter(x['api_status'] for x in results))},ensure_ascii=False),flush=True)
    return results,attempts
def main():
    records=json.loads(Path('input/avito_expansion_batch03_20261113.json').read_text())['items'];validate(records)
    expected={(canon(r['brand']),canon(r['article'])):r for r in records}
    config=load_config(Path('config.json'));book=load_fresh_price(config,Path('.'),2);found={}
    try:
        rows=book.active.iter_rows(values_only=True);h={str(x):i for i,x in enumerate(next(rows))}
        for row in rows:
            k=(canon(row[h['Бренд']]),canon(row[h['Артикул']]))
            if k not in expected:continue
            r=expected[k]
            if str(row[h['Номенклатура']])!=r['supplier_nomenclature']:raise ValueError('Fresh supplier nomenclature changed')
            if not zero_days(row[h['Срок поставки, дн.']]) or number(row[h['Наличие']],0)<=0:continue
            cost=decimal(row[h['Цена, руб.']])
            if cost is None or cost<=0:continue
            found[k]={'category':r['category'],'brand':r['brand'],'article':r['article'],'supplier_delivery_days':0,'supplier_stock':number(row[h['Наличие']],0),'supplier_list_price_rub':str(cost)}
    finally:book.close()
    creds={k:(os.environ.get('ROSSKO_API_'+k) or '').strip() for k in ('KEY1','KEY2')}
    if not all(creds.values()):raise ValueError('Missing account credentials')
    checkout=retry_transient(lambda:rpc(zeep_client('GetCheckoutDetails'),'GetCheckoutDetails',creds),attempts=3);delivery,_=choose_delivery(checkout)
    if not delivery:raise ValueError('Account delivery not confirmed')
    results,attempts=review(records,found,zeep_client('GetSearch'),creds,delivery)
    report={'batch_size':100,'API_requests_attempted':attempts,'results':results,'status_counts':dict(Counter(r['api_status'] for r in results)),'ready_for_full_source_review':[{'brand':r['brand'],'article':r['article']} for r in results if r.get('avito_retail_rub')],'source_review_policy':'Full OEM/fitment/photo verification follows only a successful fresh zero-day API gate','no_XML_changes':True,'no_private_buying_prices_written':True,'publication_performed':False}
    Path('review').mkdir(exist_ok=True);Path('review/expansion-batch03-api-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('AVITO_EXPANSION_BATCH03_REVIEW',json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
