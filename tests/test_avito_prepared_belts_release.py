import unittest
from pathlib import Path
from xml.etree import ElementTree as E
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts
from avito_reviewed_drive_belts import load_reviewed_belts
from avito_prepared_belts_release import make_ad,append_ads
from avito_active_feed_refresh import seller_sku,key
from avito_wholesale_live_api_refresh import list_approved
from test_avito_active_feed_refresh import fixture
B=Path(__file__).resolve().parents[1]
class PreparedBeltsIntegration(unittest.TestCase):
 def test_both_manufacturers_append_15_and_remain_refreshable(self):
  rs=load_reviewed_sufix_belts(B/'input/avito_reviewed_sufix_drive_belts.json')[16:29]+load_reviewed_belts(B/'input/avito_reviewed_drive_belts_source09.json')
  self.assertEqual(len(rs),15);self.assertEqual({r['brand'] for r in rs},{'SUFIX','LYNXauto'})
  raw,_,_=fixture(count=510,absent=0);ads=[make_ad(r,1500,{'public_url':r['photo_url']},'Иркутск') for r in rs]
  for r,a in zip(rs,ads):self.assertEqual(seller_sku(a),(key(r['brand'],r['article']),r['category']))
  out=append_ads(raw,ads);self.assertEqual(len(list_approved(out)),525)
  self.assertEqual([E.tostring(a) for a in E.fromstring(raw)],[E.tostring(a) for a in E.fromstring(out)][:510])
