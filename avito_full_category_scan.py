"""Persistent, bounded account-API census of all requested-category candidates.

Only the review branch is written. Never publishes XML or private buying costs.
"""
import argparse,hashlib,json,os,subprocess,threading,time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from avito_requested_categories import GROUPS,classify
from avito_irkutsk import load_fresh_price,zero_days
from avito_active_feed_refresh import seller_sku
from update_prices import load_config
from rossko_wholesale_private_audit import norm,number,decimal,rpc,retry_transient,zeep_client,choose_delivery
from rossko_category_wholesale_export import audit_one
from avito_pricing import progressive_price

REVIEW_BRANCH='avito-expansion-review'
RETRY_PREFIXES=('сбой_API_','ошибка_ответа_','NOT_CHECKED_')
def now():return datetime.now(timezone.utc).isoformat()
def sku(r):return (norm(r['brand']),norm(r['article']))
def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
def retryable(r):return str(r.get('api_status','')).startswith(RETRY_PREFIXES) or r.get('api_status') in ('api_no_structured_response','UNKNOWN')
def scope_hash(items):
    return hashlib.sha256(json.dumps([[r['category'],r['brand'],r['article'],r['supplier_nomenclature']] for r in items],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
class RateLimiter:
    def __init__(self,interval=1.0):self.interval=interval;self.last=None;self.lock=threading.Lock()
    def wait(self):
        with self.lock:
            if self.last is not None:time.sleep(max(0,self.interval-(time.monotonic()-self.last)))
            self.last=time.monotonic()
def quote_result(item,quote):
    out={k:item[k] for k in ('category','brand','article','supplier_nomenclature')}
    out.update(checked_at_utc=now(),api_status=str(quote.get('status','UNKNOWN')),source='fresh_personal_ROSSKO_API')
    if quote.get('status')=='опт_Иркутск_подтвержден' and quote.get('api_irkutsk_stock_ids'):
        cost=decimal(quote.get('api_irkutsk_same_delivery_price_rub'));source=decimal(item.get('supplier_list_price_rub'))
        if cost is None or source is None or not source/Decimal(10)<=cost<=source*2:
            out['api_status']='API_QUOTE_PRICE_SANITY_NOT_CONFIRMED'
        else:
            out['avito_retail_rub']=progressive_price(cost);out['source_review_status']='PENDING_OEM_FITMENT_REAL_PHOTO_VERIFICATION'
    return out

def inventory(config,config_dir,live):
    livekeys={tuple(norm(v) for v in seller_sku(a)[0]) for a in ET.fromstring(live).findall('Ad')}
    book=load_fresh_price(config,config_dir,2);eligible={};ambiguous={};rowcount=0
    try:
        rows=book.active.iter_rows(values_only=True);h={str(v):i for i,v in enumerate(next(rows))}
        required={'Номенклатура','Бренд','Артикул','Описание','Наличие','Цена, руб.','Срок поставки, дн.'}
        if not required<=set(h):raise ValueError('Supplier columns missing')
        citycols=[h[c] for c in ('Город склада','Склад отгрузки','Филиал','Город') if c in h]
        for row in rows:
            rowcount+=1;category=classify(row[h['Описание']])
            if category is None:continue
            record={'brand':str(row[h['Бренд']] or '').strip(),'article':str(row[h['Артикул']] or '').strip(),'supplier_nomenclature':str(row[h['Номенклатура']] or '').strip()};k=sku(record)
            if not all(k):continue
            if isinstance(category,tuple):
                ambiguous[k]={**record,'description':str(row[h['Описание']] or '')[:300],'classification':'AMBIGUOUS_MANUAL_REVIEW_REQUIRED'};continue
            qty=number(row[h['Наличие']],0);cost=decimal(row[h['Цена, руб.']])
            if qty<=0 or cost is None or cost<=0 or not zero_days(row[h['Срок поставки, дн.']]):continue
            if citycols and not any('иркутск' in str(row[c] or '').casefold() for c in citycols):continue
            record.update(category=category,supplier_stock=qty,supplier_delivery_days=0,supplier_list_price_rub=str(cost),supplier_description=str(row[h['Описание']] or '')[:300])
            eligible[k]=record
    finally:book.close()
    allcounts=Counter(r['category'] for r in eligible.values());existingcounts=Counter(r['category'] for k,r in eligible.items() if k in livekeys)
    selected=[r for k,r in eligible.items() if k not in livekeys]
    order={g:i for i,(g,_) in enumerate(GROUPS)};selected.sort(key=lambda r:(order[r['category']],norm(r['brand']),norm(r['article'])))
    return selected,{'source_rows':rowcount,'eligible_total':len(eligible),'already_active_excluded':sum(existingcounts.values()),'category_inventory_counts':dict(allcounts),'category_already_active_counts':dict(existingcounts)},list(ambiguous.values())

def recent_cache(source_dir,items):
    allowed={sku(r):r for r in items};out={};cutoff=datetime.now(timezone.utc)-timedelta(minutes=60)
    for name in ('avito_heater_batch01_20261113.json','avito_heater_batch02_20261113.json','avito_expansion_batch03_20261113.json'):
        path=source_dir/name
        if not path.exists():continue
        for row in json.loads(path.read_text()).get('items',[]):
            result=row.get('account_API_review',{});key=sku(row)
            try:stamp=datetime.fromisoformat(result['checked_at_utc'])
            except (KeyError,ValueError):continue
            if key not in allowed or stamp.tzinfo is None or not cutoff<=stamp<=datetime.now(timezone.utc):continue
            if result.get('api_status')!='Иркутск_есть_иной_срок':continue
            r=allowed[key];out[key]={**{k:r[k] for k in ('category','brand','article','supplier_nomenclature')},'checked_at_utc':result['checked_at_utc'],'api_status':result['api_status'],'source':'recent_exact_API_result_with_original_timestamp'}
    return out

def load_batches(base,items):
    allowed={sku(r):r for r in items};done={}
    for path in sorted((base/'batches').glob('*.json')):
        for r in json.loads(path.read_text()).get('results',[]):
            k=sku(r)
            if k not in allowed or r['supplier_nomenclature']!=allowed[k]['supplier_nomenclature'] or r['category']!=allowed[k]['category']:raise ValueError('Checkpoint SKU identity mismatch')
            if not retryable(r):done[k]=r
    return done

def checkpoint(base,items,done,meta,state,session_requests,session_cached):
    status=Counter(r['api_status'] for r in done.values());positive=[r for r in done.values() if 'avito_retail_rub' in r]
    categories=[]
    for group,_ in GROUPS:
        q=[r for r in items if r['category']==group];checked=[r for r in done.values() if r['category']==group]
        categories.append({'category':group,'queued':len(q),'checked':len(checked),'API_zero_day_candidates':sum('avito_retail_rub' in r for r in checked),'pending':len(q)-len(checked)})
    summary={**meta,'updated_at_utc':now(),'state':state,'queue_total':len(items),'scope_sha256':scope_hash(items),'checked':len(done),'pending':len(items)-len(done),'session_new_API_requests':session_requests,'session_recent_cache_reused':session_cached,'status_counts':dict(status),'API_zero_day_candidate_count':len(positive),'fully_source_verified_publishable_count':0 if state=='COMPLETE' and not positive else None,'source_verification_pending_count':len(positive),'categories':categories,'Avito_XML_modified':False,'private_buying_prices_written':False,'API_max_workers':2,'API_start_interval_seconds':1.0,'results_are_timestamped_not_a_simultaneous_stock_snapshot':True}
    atomic_json(base/'summary.json',summary);atomic_json(base/'API_zero_day_candidates_REQUIRE_SOURCE_REVIEW.json',{'items':positive,'not_approved_for_publication':True})
    lines=['# Полная проверка запрошенных 22 категорий','',f"Состояние: **{state}**. Обновлено (UTC): {summary['updated_at_utc']}.",'',f"Кандидатов в очереди: **{len(items)}**; проверено: **{len(done)}**; осталось: **{len(items)-len(done)}**.",f"API подтвердил Иркутск, положительный остаток и 0 дней: **{len(positive)}**. Эти позиции требуют отдельной проверки OEM, применимости и реального фото.",'','Действующий XML не изменяется. Покупные цены и ключи не сохраняются. Результаты имеют индивидуальное время проверки; это не одновременный снимок всех остатков.','', '| Категория | В очереди | Проверено | API: 0 дней | Осталось |','| --- | ---: | ---: | ---: | ---: |']
    lines += [f"| {r['category']} | {r['queued']} | {r['checked']} | {r['API_zero_day_candidates']} | {r['pending']} |" for r in categories]
    (base/'PROGRESS.md').write_text('\n'.join(lines)+'\n');return summary

def push_checkpoint(repo,base):
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=repo,text=True).strip()
    if branch!=REVIEW_BRANCH:raise ValueError('Refuse writing outside review branch')
    rel=str(base.relative_to(repo));subprocess.run(['git','add','--',rel],cwd=repo,check=True)
    if subprocess.run(['git','diff','--cached','--quiet'],cwd=repo).returncode==0:return
    subprocess.run(['git','commit','-m','Checkpoint requested-category API review; no XML or private costs'],cwd=repo,check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['git','push','origin','HEAD:'+REVIEW_BRANCH],cwd=repo,check=True,stdout=subprocess.DEVNULL)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--live',type=Path,required=True);p.add_argument('--state-repo',type=Path,required=True);p.add_argument('--scan-id',default='20261113');p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--max-batches',type=int,default=0);a=p.parse_args()
    if a.scan_id!='20261113':raise ValueError('Unreviewed scan ID')
    repo=a.state_repo.resolve();base=repo/'results'/a.scan_id;base.mkdir(parents=True,exist_ok=True)
    config=load_config(a.config);fresh,meta,ambiguous=inventory(config,a.config.parent,a.live.read_bytes());freshmap={sku(r):r for r in fresh}
    queuefile=base/'queue.json'
    if queuefile.exists():
        saved=json.loads(queuefile.read_text());items=saved['items'];meta=saved['inventory_at_start']
        if saved['scope_sha256']!=scope_hash(items):raise ValueError('Frozen queue changed')
    else:
        items=[{k:v for k,v in r.items() if k not in ('supplier_list_price_rub','supplier_stock','supplier_delivery_days')} for r in fresh];meta['inventory_created_at_utc']=now();meta['source_commit']=os.environ.get('GITHUB_SHA');atomic_json(queuefile,{'items':items,'scope_sha256':scope_hash(items),'inventory_at_start':meta});atomic_json(base/'ambiguous_MANUAL_REVIEW_REQUIRED.json',{'items':ambiguous})
    if not 1<=len(items)<=50000 or len({sku(r) for r in items})!=len(items):raise ValueError('Unexpected queue size')
    done=load_batches(base,items);cache=recent_cache(a.source_dir,items);done.update({k:r for k,r in cache.items() if k not in done});cached_count=sum(r.get('source')=='recent_exact_API_result_with_original_timestamp' for r in done.values())
    # Persist recent reuse in its own bounded, timestamped file so resume does not lose it.
    atomic_json(base/'batches'/'recent-cache.json',{'results':[r for r in done.values() if r.get('source')=='recent_exact_API_result_with_original_timestamp']})
    requests_count=0;checkpoint(base,items,done,meta,'RUNNING',requests_count,cached_count);push_checkpoint(repo,base)
    creds={k:(os.environ.get('ROSSKO_API_'+k) or '').strip() for k in ('KEY1','KEY2')}
    if not all(creds.values()):raise ValueError('Missing API credentials')
    checkout=retry_transient(lambda:rpc(zeep_client('GetCheckoutDetails'),'GetCheckoutDetails',creds),attempts=3);delivery,_=choose_delivery(checkout)
    if not delivery:raise ValueError('Account delivery unavailable')
    limiter=RateLimiter();local=threading.local();failure_streak=0;stop=threading.Event();session_batches=0
    def check(r):
        if stop.is_set():return None
        freshitem=freshmap.get(sku(r))
        if not freshitem or freshitem['supplier_nomenclature']!=r['supplier_nomenclature']:
            return {**{k:r[k] for k in ('category','brand','article','supplier_nomenclature')},'checked_at_utc':now(),'api_status':'NO_FRESH_SUPPLIER_ZERO_DAY_STOCK','source':'fresh_supplier_recheck'}
        if not hasattr(local,'client'):local.client=zeep_client('GetSearch')
        limiter.wait()
        if stop.is_set():return None
        return quote_result(freshitem,audit_one(local.client,creds,delivery,freshitem))
    with ThreadPoolExecutor(max_workers=2) as pool:
        for offset in range(0,len(items),100):
            chunk=items[offset:offset+100];remaining=[r for r in chunk if sku(r) not in done]
            if not remaining:continue
            path=base/'batches'/f'{offset//100+1:04d}.json';partial={sku(r):r for r in json.loads(path.read_text()).get('results',[])} if path.exists() else {}
            # At most two outstanding requests. Stop submitting on repeated network faults.
            iterator=iter(remaining);active={}
            for _ in range(2):
                r=next(iterator,None)
                if r is not None:active[pool.submit(check,r)]=r
            from concurrent.futures import wait,FIRST_COMPLETED
            while active:
                finished,_=wait(active,return_when=FIRST_COMPLETED)
                for future in finished:
                    r=active.pop(future)
                    try:result=future.result()
                    except Exception as exc:result={**{k:r[k] for k in ('category','brand','article','supplier_nomenclature')},'checked_at_utc':now(),'api_status':'сбой_API_'+type(exc).__name__,'source':'fresh_API_attempt'}
                    if result is not None:
                        if result['source']!='fresh_supplier_recheck':requests_count+=1
                        partial[sku(result)]=result
                        if not retryable(result):done[sku(result)]=result
                        failure_streak=failure_streak+1 if retryable(result) else 0
                        if failure_streak>=5:stop.set()
                    if not stop.is_set():
                        nxt=next(iterator,None)
                        if nxt is not None:active[pool.submit(check,nxt)]=nxt
            atomic_json(path,{'results':list(partial.values()),'batch_max_size':100});session_batches+=1
            state='PAUSED_API_ERRORS' if stop.is_set() else 'RUNNING';summary=checkpoint(base,items,done,meta,state,requests_count,cached_count);push_checkpoint(repo,base)
            print('AVITO_FULL_SCAN_PROGRESS',json.dumps({k:summary[k] for k in ('state','queue_total','checked','pending','API_zero_day_candidate_count','session_new_API_requests')},ensure_ascii=False),flush=True)
            if stop.is_set() or (a.max_batches and session_batches>=a.max_batches):break
    state='COMPLETE' if len(done)==len(items) else 'PAUSED_API_ERRORS' if stop.is_set() else 'PAUSED_BATCH_LIMIT'
    summary=checkpoint(base,items,done,meta,state,requests_count,cached_count);push_checkpoint(repo,base);print('AVITO_FULL_SCAN_FINAL',json.dumps({k:summary[k] for k in ('state','queue_total','checked','pending','API_zero_day_candidate_count')},ensure_ascii=False),flush=True)
if __name__=='__main__':
    try:main()
    except Exception as exc:print('AVITO_FULL_SCAN_FAILED',type(exc).__name__,flush=True);raise SystemExit(1)
