import json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
from types import SimpleNamespace
from avito_prepared_belts_release import load_release_records,make_ad,append_ads
from avito_active_feed_refresh import seller_sku,key
from avito_wholesale_live_api_refresh import list_approved
from test_avito_active_feed_refresh import fixture
B=Path(__file__).resolve().parents[1]
class MixedNov23Categories(unittest.TestCase):
 def test_production_entrypoint_preserves_old_ads_and_dispatches_every_selected_category(self):
  args=SimpleNamespace(manifest=B/'input/avito_reviewed_sufix_drive_belts.json',lynx_manifest=B/'input/avito_reviewed_drive_belts_source09.json',febest_manifest=B/'input/avito_reviewed_febest_cvj.json',lynx06_manifest=B/'input/avito_reviewed_lynx_source06.json',selection=B/'input/avito_release_selection_20261123.json');rs=load_release_records(args);self.assertEqual(len(rs),51);self.assertEqual(sum(r['category']=='Ремни ГРМ' for r in rs),10);ads=[]
  for r in rs:
   a=make_ad(r,1500,{'public_url':r['photo_url']},'Иркутск');self.assertEqual(seller_sku(a),(key(r['brand'],r['article']),r['category']))
   if r['category']=='Ремни ГРМ':self.assertEqual(a.findtext('EngineSparePartType'),'Ремни, цепи, элементы ГРМ');self.assertTrue(a.findtext('Title').startswith('Ремень ГРМ LYNXauto '));self.assertEqual(a.findtext('SparePartType'),'Двигатель')
   elif r['category']=='Ремни приводные':self.assertEqual(a.findtext('EngineSparePartType'),'Приводные ремни, натяжители');self.assertTrue(a.findtext('Title').startswith('Ремень приводной LYNXauto '));self.assertEqual(a.findtext('SparePartType'),'Двигатель');self.assertIsNone(a.find('TransmissionSparePartType'))
   else:self.assertIsNone(a.find('EngineSparePartType'));self.assertEqual(a.findtext('TransmissionSparePartType'),'Приводные валы, полуоси и ШРУСы')
   ads.append(a)
  old,_,_=fixture(count=408,absent=0);new=append_ads(old,ads);self.assertEqual(len(list_approved(new)),459);self.assertEqual([E.tostring(x) for x in E.fromstring(old)],[E.tostring(x) for x in E.fromstring(new)][:408])
