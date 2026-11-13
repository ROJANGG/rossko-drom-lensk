import ast,hashlib,json,tempfile,threading,time,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from avito_requested_categories import classify,GROUPS
BASE=Path(__file__).resolve().parents[1]
class FullScanGuards(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((BASE/'avito_full_category_scan.py').read_text());names={'now','sku','atomic_json','retryable','scope_hash','quote_result','load_batches','recent_cache'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RETRY_PREFIXES' for t in n.targets)]
        self.s={'hashlib':hashlib,'json':json,'Path':Path,'datetime':datetime,'timezone':timezone,'timedelta':timedelta,'Decimal':Decimal,'norm':lambda x:''.join(str(x).lower().split()),'decimal':lambda x:Decimal(str(x)) if x is not None else None,'progressive_price':lambda x:999}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual_scan_functions','exec'),self.s)
        self.item={'brand':'Luzar','article':'LRH0826','category':'Радиаторы печки','supplier_nomenclature':'GUID','supplier_list_price_rub':'1000'}
    def test_exactly_22_requested_categories_and_accessories_not_glow_plugs(self):
        self.assertEqual(len(GROUPS),22);self.assertEqual(classify('Радиатор отопителя'),'Радиаторы печки');self.assertIsNone(classify('Смазка для свечей накала'));self.assertIsNone(classify('Кольцо уплотнительное форсунки топливной'))
    def test_other_delivery_never_includes_private_cost_or_retail(self):
        out=self.s['quote_result'](self.item,{'status':'Иркутск_есть_иной_срок','api_irkutsk_same_delivery_price_rub':'SECRET_COST'})
        self.assertNotIn('SECRET_COST',json.dumps(out));self.assertNotIn('avito_retail_rub',out)
    def test_only_confirmed_stock_and_sane_zero_day_price_produces_retail(self):
        q={'status':'опт_Иркутск_подтвержден','api_irkutsk_stock_ids':'HST','api_irkutsk_same_delivery_price_rub':'800'};out=self.s['quote_result'](self.item,q);self.assertEqual(out['avito_retail_rub'],999);self.assertNotIn('api_irkutsk_same_delivery_price_rub',out)
        q['api_irkutsk_same_delivery_price_rub']='999999';self.assertNotIn('avito_retail_rub',self.s['quote_result'](self.item,q))
        q['api_irkutsk_stock_ids']='';self.assertNotIn('avito_retail_rub',self.s['quote_result'](self.item,q))
    def test_resume_retains_non_transient_result_and_retries_failed_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);r={**self.item,'api_status':'Иркутск_есть_иной_срок'};self.s['atomic_json'](base/'batches/0001.json',{'results':[r]});self.assertEqual(len(self.s['load_batches'](base,[self.item])),1)
            r['api_status']='сбой_API_ConnectionError';self.s['atomic_json'](base/'batches/0001.json',{'results':[r]});self.assertEqual(self.s['load_batches'](base,[self.item]),{})
    def test_resume_rejects_different_exact_supplier_sku(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);r={**self.item,'supplier_nomenclature':'OTHER','api_status':'Иркутск_есть_иной_срок'};self.s['atomic_json'](base/'batches/0001.json',{'results':[r]})
            with self.assertRaises(ValueError):self.s['load_batches'](base,[self.item])
    def test_cache_preserves_time_and_rejects_stale_or_failed_results(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);row={**self.item,'account_API_review':{'api_status':'Иркутск_есть_иной_срок','checked_at_utc':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()}}
            path=base/'avito_heater_batch01_20261113.json';path.write_text(json.dumps({'items':[row]}))
            cache=self.s['recent_cache'](base,[self.item]);self.assertEqual(len(cache),1);self.assertEqual(next(iter(cache.values()))['checked_at_utc'],row['account_API_review']['checked_at_utc'])
            row['account_API_review']['checked_at_utc']=(datetime.now(timezone.utc)-timedelta(minutes=61)).isoformat();path.write_text(json.dumps({'items':[row]}));self.assertEqual(self.s['recent_cache'](base,[self.item]),{})

    def test_scope_hash_binds_category_brand_article_and_nomenclature(self):
        digest=self.s['scope_hash']([self.item]);other={**self.item,'article':'OTHER'};self.assertNotEqual(digest,self.s['scope_hash']([other]))
if __name__=='__main__':unittest.main()
