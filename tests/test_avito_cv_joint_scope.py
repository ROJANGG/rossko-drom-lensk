import copy,json,tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as E
from openpyxl import Workbook
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts
from avito_prepared_belts_release import make_ad,validate_source
from avito_active_feed_refresh import seller_sku,key,supplier_products
B=Path(__file__).resolve().parents[1]
class ExactCVJointScope(unittest.TestCase):
 def records(self):return [r for r in load_reviewed_sufix_belts(B/'input/avito_reviewed_sufix_drive_belts.json') if r['category']=='ШРУС']
 def test_transmission_type_identity_and_unknown_SKU_rejection(self):
  r=self.records()[0];a=make_ad(r,3000,{'public_url':r['photo_url']},'Иркутск');self.assertEqual(seller_sku(a),(key('SUFIX',r['article']),'ШРУС'));self.assertEqual(a.findtext('SparePartType'),'Трансмиссия и привод');self.assertEqual(a.findtext('TransmissionSparePartType'),'Приводные валы, полуоси и ШРУСы');self.assertIsNone(a.find('EngineSparePartType'))
  a.find('TransmissionSparePartType').text='КПП в сборе'
  with self.assertRaises(ValueError):seller_sku(a)
 def test_accessory_or_grease_cannot_be_a_CV_joint(self):
  r=self.records()[0]
  for heading in ['Пыльник ШРУСа','Смазка для ШРУСа']:
   p='<h1>'+heading+'</h1><span itemprop="mpn" data-model="'+r['article']+'"></span>'
   with self.assertRaisesRegex(ValueError,'category mismatch'):validate_source(r,p)
 def test_new_category_still_requires_Irkutsk_positive_zero_day_stock(self):
  rs=self.records();b=Workbook();w=b.active;w.append(['Бренд','Артикул','Описание','Цена, руб.','Наличие','Срок поставки, дн.','Город склада'])
  for r,city,days,qty in [(rs[0],'Иркутск',0,2),(rs[1],'Москва',0,2),(rs[2],'Иркутск',2,2),(rs[3],'Иркутск',0,0)]:w.append(['SUFIX',r['article'],'ШРУС наружный',1000,qty,days,city])
  w.append(['SUFIX','ST999999','ШРУС наружный',1000,2,0,'Иркутск']);out=supplier_products(b,{'avito':{'pickup_address':'Иркутск'}});b.close();self.assertEqual(set(out),{key('SUFIX',rs[0]['article'])})
 def test_ambiguous_two_joint_sale_unit_is_rejected(self):
  p=B/'input/avito_reviewed_sufix_drive_belts.json';d=json.loads(p.read_text());r=next(r for r in d['items'] if r['category']=='ШРУС');r['primary_product_count_verified']=2
  with tempfile.TemporaryDirectory() as t:
   q=Path(t)/'bad.json';q.write_text(json.dumps(d))
   with self.assertRaisesRegex(ValueError,'sale unit'):load_reviewed_sufix_belts(q)
