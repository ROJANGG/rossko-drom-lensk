import unittest,json,copy,tempfile
from pathlib import Path
from xml.etree import ElementTree as E
from avito_reviewed_lynx_source06 import load_reviewed_lynx,META
from avito_active_feed_refresh import seller_sku,key,APPROVED_CATALOG_LIMIT
from avito_lynx_source06_release import make_ad,append_ads,validate_source
B=Path(__file__).resolve().parents[1]
class ExactLYNXReview(unittest.TestCase):
 def setUp(self):self.m=B/'input/avito_reviewed_lynx_source06.json';self.rs=load_reviewed_lynx(self.m)
 def test_closed_scope_rejects_substitution(self):
  d=json.loads(self.m.read_text());d['items'][0]['article']='OTHER'
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'m.json';p.write_text(json.dumps(d))
   with self.assertRaises(ValueError):load_reviewed_lynx(p)
 def test_all_new_ads_are_recognized_and_append_preserves_old_fields(self):
  ads=[make_ad(r,1500,{'public_url':r['photo_url']},'г. Иркутск, ул. Каховского, д. 11/1') for r in self.rs]
  for r,a in zip(self.rs,ads):self.assertEqual(seller_sku(a),(key(r['brand'],r['article']),r['category']))
  old=b'<Ads formatVersion="3"><Ad><Id>old</Id><OEM>unchanged</OEM><Price>1234</Price></Ad></Ads>'
  new=E.fromstring(append_ads(old,ads));self.assertEqual(E.tostring(new[0]),E.tostring(E.fromstring(old)[0]));self.assertEqual(len(new),1+len(ads))
  self.assertEqual(APPROVED_CATALOG_LIMIT,576+len(self.rs))
 def test_wrong_engine_type_and_unapproved_article_are_rejected(self):
  r=self.rs[0];a=make_ad(r,1500,{'public_url':r['photo_url']},'Иркутск');a.find('EngineSparePartType').text='Двигатель в сборе'
  with self.assertRaises(ValueError):seller_sku(a)
  a.find('EngineSparePartType').text=META[r['category']][3];a.find('Title').text='Ремень ГРМ LYNXauto OTHER новый'
  with self.assertRaises(ValueError):seller_sku(a)
 def test_source_validates_both_original_make_and_number(self):
  r=self.rs[0];raw=(B/'tests/fixtures/product.html').read_bytes();fit=(B/'tests/fixtures/fitment.html').read_bytes()
  self.assertTrue(validate_source(r,raw,fit));r=copy.deepcopy(r);r['OEM_make']='FAKE'
  with self.assertRaises(ValueError):validate_source(r,raw,fit)
if __name__=='__main__':unittest.main()
