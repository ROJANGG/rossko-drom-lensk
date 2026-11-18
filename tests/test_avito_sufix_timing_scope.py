import unittest
from pathlib import Path
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts
from avito_prepared_belts_release import make_ad,validate_source
from avito_active_feed_refresh import seller_sku,key
B=Path(__file__).resolve().parents[1]
class ExactTimingScope(unittest.TestCase):
 def setUp(self):self.r=next(r for r in load_reviewed_sufix_belts(B/'input/avito_reviewed_sufix_drive_belts.json') if r['category']=='Ремни ГРМ')
 def test_timing_title_engine_type_and_refresh_identity_agree(self):
  r=self.r;a=make_ad(r,1500,{'public_url':r['photo_url']},'Иркутск');self.assertEqual(seller_sku(a),(key('SUFIX',r['article']),'Ремни ГРМ'));self.assertEqual(a.findtext('EngineSparePartType'),'Ремни, цепи, элементы ГРМ')
  a.find('EngineSparePartType').text='Приводные ремни, натяжители'
  with self.assertRaises(ValueError):seller_sku(a)
 def test_manufacturer_drive_heading_cannot_substitute_for_timing(self):
  r=self.r;p='<h1>Ремень поликлиновой</h1><span itemprop="mpn" data-model="'+r['article']+'"></span>'
  with self.assertRaisesRegex(ValueError,'category mismatch'):validate_source(r,p)
