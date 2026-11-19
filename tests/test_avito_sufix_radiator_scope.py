import unittest
from pathlib import Path
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts
from avito_prepared_belts_release import make_ad,validate_source
from avito_active_feed_refresh import seller_sku,key
B=Path(__file__).resolve().parents[1]
class ExactRadiatorScope(unittest.TestCase):
 def records(self):
  rs=load_reviewed_sufix_belts(B/'input/avito_reviewed_sufix_drive_belts.json')
  return [next(r for r in rs if r['category']==c) for c in ('Радиаторы охлаждения','Радиаторы кондиционера')]
 def test_both_radiator_types_are_refreshable_without_engine_parameter(self):
  for r in self.records():
   a=make_ad(r,6000,{'public_url':r['photo_url']},'Иркутск');self.assertEqual(seller_sku(a),(key('SUFIX',r['article']),r['category']));self.assertEqual(a.findtext('SparePartType'),'Система охлаждения');self.assertIsNone(a.find('EngineSparePartType'))
   a.find('Title').text=a.findtext('Title').replace(r['article'],'UNKNOWN')
   with self.assertRaises(ValueError):seller_sku(a)
 def test_manufacturer_cooling_and_ac_headings_cannot_be_interchanged(self):
  for r in self.records():
   heading='Радиатор кондиционера' if r['category']=='Радиаторы охлаждения' else 'Радиатор охлаждения'
   raw='<h1>'+heading+'</h1><span itemprop="mpn" data-model="'+r['article']+'"></span>'
   with self.assertRaisesRegex(ValueError,'category mismatch'):validate_source(r,raw)
