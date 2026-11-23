import copy,json,tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as E
from openpyxl import Workbook
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts
from avito_prepared_belts_release import make_ad,append_ads,validate_source
from avito_active_feed_refresh import seller_sku,key,supplier_products,APPROVED_CATALOG_LIMIT
from avito_wholesale_live_api_refresh import list_approved
from test_avito_active_feed_refresh import fixture
P=Path(__file__).resolve().parents[1]/'input/avito_reviewed_sufix_drive_belts.json'
class SufixDriveRelease(unittest.TestCase):
 def test_closed_93_scope_and_package_holds(self):
  rs=load_reviewed_sufix_belts(P);self.assertEqual(len(rs),356);self.assertEqual(sum(r['package_unit_verified'] for r in rs),356);self.assertEqual(APPROVED_CATALOG_LIMIT,998)
  bad=json.loads(P.read_text());bad['items'][0]['article']='UNREVIEWED'
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'bad.json';f.write_text(json.dumps(bad))
   with self.assertRaises(ValueError):load_reviewed_sufix_belts(f)
 def test_single_unit_append_preserves_408_and_API_accepts_new_category(self):
  old,_,_=fixture(count=408,absent=0);rs=[r for r in load_reviewed_sufix_belts(P) if r['package_unit_verified']]
  ads=[make_ad(r,1500,{'public_url':'https://example.test/'+r['article']+'.jpg'},'Иркутск') for r in rs]
  for r,a in zip(rs,ads):self.assertEqual(seller_sku(a),(key(r['brand'],r['article']),r['category']))
  new=append_ads(old,ads);self.assertEqual(len(list_approved(new)),764);self.assertEqual([E.tostring(a) for a in E.fromstring(old)],[E.tostring(a) for a in E.fromstring(new)][:408])
 def test_mixed_reference_table_never_substitutes_aftermarket_maker(self):
  r=copy.deepcopy(load_reviewed_sufix_belts(P)[0]);r['fitment_rows']=[{'model':'MODEL','modification':'ENGINE','url':'https://sufix.pro/car'}]
  page='<h1>Ремень приводной</h1><span itemprop="mpn" data-model="'+r['article']+'"></span><table class="pcard-analog-bottom"><tr><td>'+r['OEM_raw']+'</td><td>'+r['OEM_make']+'</td></tr></table><div class="applicabilit-group"><div class="applicabilit-group-title">'+r['applicability_make']+'</div><div class="applicabilit-item"><a href="https://sufix.pro/car"><span class="model">MODEL</span><span class="mofif">ENGINE</span></a></div></div><a class="lightboxgroup" href="'+r['photo_url']+'"></a>'
  self.assertTrue(validate_source(r,page))
  for bad in [page.replace(r['OEM_make'],'GMB'),page.replace(r['article'],'OTHER'),page.replace('MODEL','OTHER'),page.replace(r['photo_url'],'https://sufix.pro/other.jpg')]:
   with self.assertRaises(ValueError):validate_source(r,bad)
 def test_supplier_zero_day_city_and_exact_SKU_gate(self):
  rs=load_reviewed_sufix_belts(P);b=Workbook();w=b.active;w.append(['Бренд','Артикул','Описание','Цена, руб.','Наличие','Срок поставки, дн.','Город склада'])
  for r,city,days,qty in [(rs[0],'Иркутск',0,2),(rs[1],'Москва',0,2),(rs[2],'Иркутск',2,2),(rs[3],'Иркутск',0,0)]:w.append(['SUFIX',r['article'],'Ремень приводной',1000,qty,days,city])
  w.append(['SUFIX','UNKNOWN','Ремень приводной',1000,2,0,'Иркутск']);got=supplier_products(b,{'avito':{'pickup_address':'Иркутск'}});b.close();self.assertEqual(set(got),{key('SUFIX',rs[0]['article'])})
