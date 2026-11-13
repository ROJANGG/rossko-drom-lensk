import ast,json,re,time,hashlib,unittest
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
class Batch100Guards(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((BASE/'avito_expansion_batch03_review.py').read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('canon','validate','review') or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCOPE_SHA256' for t in n.targets)]
        self.scope={'json':json,'re':re,'time':time,'hashlib':hashlib,'Counter':Counter,'datetime':datetime,'timezone':timezone,'print':lambda *a,**k:None};exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual_batch_code','exec'),self.scope);self.rs=json.loads((BASE/'input/avito_expansion_batch03_20261113.json').read_text())['items'];self.found={(self.scope['canon'](r['brand']),self.scope['canon'](r['article'])):{'supplier_stock':1} for r in self.rs}
    def test_scope_is_exact_and_tampering_is_rejected(self):
        self.scope['validate'](self.rs);self.rs[0]['article']='OTHER'
        with self.assertRaises(ValueError):self.scope['validate'](self.rs)
    def test_outage_stops_after_five_failures_without_requerying_remainder(self):
        self.scope['audit_one']=lambda *a:{'status':'сбой_API_ConnectionError','private_field':'DO_NOT_WRITE'}
        out,attempts=self.scope['review'](self.rs,self.found,None,{},None,sleep=lambda _:None)
        self.assertEqual(attempts,5);self.assertEqual(len(out),100);self.assertEqual(sum(r['api_status']=='NOT_CHECKED_API_TEMPORARY_FAILURE_LIMIT' for r in out),95);self.assertNotIn('DO_NOT_WRITE',json.dumps(out))
    def test_safe_resume_checkpoints_every_twenty_records(self):
        self.scope['audit_one']=lambda *a:{'status':'Иркутск_есть_иной_срок'}
        checkpoints=[]
        self.scope['review'](self.rs,self.found,None,{},None,sleep=lambda _:None,checkpoint=lambda out,attempts:checkpoints.append((len(out),attempts)))
        self.assertEqual(checkpoints,[(20,20),(40,40),(60,60),(80,80),(100,100)])

    def test_other_delivery_does_not_produce_retail_or_ready_listing(self):
        self.scope['audit_one']=lambda *a:{'status':'Иркутск_есть_иной_срок','api_irkutsk_same_delivery_price_rub':'DO_NOT_WRITE'}
        out,attempts=self.scope['review'](self.rs,self.found,None,{},None,sleep=lambda _:None)
        self.assertEqual(attempts,100);self.assertTrue(all('avito_retail_rub' not in r for r in out));self.assertNotIn('DO_NOT_WRITE',json.dumps(out))
if __name__=='__main__':unittest.main()
