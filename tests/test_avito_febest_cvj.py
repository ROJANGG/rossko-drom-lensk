import copy,json,tempfile,unittest,html
from pathlib import Path
from xml.etree import ElementTree as E
from openpyxl import Workbook
from avito_reviewed_febest_cvj import load_reviewed_febest,validate_source
from avito_prepared_belts_release import make_ad,append_ads,load_release_records
from types import SimpleNamespace
from avito_active_feed_refresh import seller_sku,key,supplier_products
from avito_wholesale_live_api_refresh import list_approved
from test_avito_active_feed_refresh import fixture
B=Path(__file__).resolve().parents[1];P=B/'input/avito_reviewed_febest_cvj.json'
class ExactFebestCVJ(unittest.TestCase):
 def records(self):return load_reviewed_febest(P)
 def test_new_brand_exact_type_and_unknown_SKU_protection(self):
  r=self.records()[0];a=make_ad(r,3000,{'public_url':r['photo_url']},'Иркутск');self.assertEqual(seller_sku(a),(key('Febest',r['article']),'ШРУС'));self.assertIsNone(a.find('EngineSparePartType'))
  for field,value in [('Brand','OTHER'),('TransmissionSparePartType','КПП в сборе'),('Title','ШРУС Febest UNKNOWN новый')]:
   bad=copy.deepcopy(a);bad.find(field).text=value
   with self.assertRaises(ValueError):seller_sku(bad)
 def test_primary_binding_rejects_wrong_MPN_boot_scheme_and_assembly_OEM(self):
  r=self.records()[0];esc=html.escape;models=''.join('<option value="'+esc(x,quote=True)+'">'+esc(x)+'</option>' for x in r['fitment_rows']);page='<h1>'+esc(r['product_title'])+'</h1><h2 class="detPartCode">Code: '+r['manufacturer_MPN']+'</h2><table id="detailsgrid_table"><tr><td>'+r['manufacturer_MPN']+'</td><td>'+esc(r['product_title'])+'</td><td>'+r['OEM_raw']+'</td></tr></table><select id="oem_select"><option value="'+r['OEM_raw']+'">'+r['OEM_raw']+'</option></select><select id="model_list">'+models+'</select><div id="foto"><img src="'+r['photo_url']+'"></div>';self.assertTrue(validate_source(r,page))
  for bad in [page.replace(r['manufacturer_MPN'],'OTHER'),page.replace(r['product_title'],'CV JOINT BOOT'),page.replace(r['OEM_raw'],'#'+r['OEM_raw']),page.replace('_p0.jpg','_s0.png')]:
   with self.assertRaises(ValueError):validate_source(r,bad)
 def test_review_scope_photo_OEM_and_ambiguous_unit_are_fail_closed(self):
  raw=json.loads(P.read_text())
  for field,value in [('article','UNKNOWN'),('photo_review','DIAGRAM'),('primary_product_count_verified',2),('oem','OTHER'),('photo_url','https://example.org/photo.jpg')]:
   d=copy.deepcopy(raw);d['items'][0][field]=value
   with tempfile.TemporaryDirectory() as t:
    p=Path(t)/'bad.json';p.write_text(json.dumps(d))
    with self.assertRaises(ValueError):load_reviewed_febest(p)
 def test_city_zero_day_positive_stock_and_exact_brand_are_required(self):
  r=self.records()[0]
  for brand,article,city,days,qty,want in [('Febest',r['article'],'Иркутск',0,2,True),('Febest',r['article'],'Москва',0,2,False),('Febest',r['article'],'Иркутск',1,2,False),('Febest',r['article'],'Иркутск',0,0,False),('Febest','UNKNOWN','Иркутск',0,2,False)]:
   b=Workbook();w=b.active;w.append(['Бренд','Артикул','Описание','Цена, руб.','Наличие','Срок поставки, дн.','Город склада']);w.append([brand,article,'ШРУС наружный',1000,qty,days,city]);got=supplier_products(b,{'avito':{'pickup_address':'Иркутск'}});b.close();self.assertEqual(key(brand,article) in got,want)
 def test_append_preserves_old_ads_and_API_reader_accepts_all_exact_Febest(self):
  old,_,_=fixture(count=408,absent=0);rs=self.records();ads=[make_ad(r,3000,{'public_url':r['photo_url']},'Иркутск') for r in rs];new=append_ads(old,ads);self.assertEqual(len(list_approved(new)),408+len(rs));self.assertEqual([E.tostring(a) for a in E.fromstring(old)],[E.tostring(a) for a in E.fromstring(new)][:408])

 def test_combined_release_loads_every_brand_before_applying_exact_selection(self):
  args=SimpleNamespace(manifest=B/'input/avito_reviewed_sufix_drive_belts.json',lynx_manifest=B/'input/avito_reviewed_drive_belts_source09.json',febest_manifest=P,lynx06_manifest=B/'input/avito_reviewed_lynx_source06.json',selection=B/'input/avito_release_selection_20261123.json')
  rs=load_release_records(args);self.assertEqual(len(rs),15);self.assertEqual(sum(r['brand']=='Febest' for r in rs),2);self.assertEqual(sum(r['brand']=='SUFIX' for r in rs),3);self.assertEqual({(r['brand'],r['article']) for r in rs},{(r['brand'],r['article']) for r in json.loads(args.selection.read_text())['items']})
