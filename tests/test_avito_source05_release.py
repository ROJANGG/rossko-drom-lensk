import copy,json,tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as E
from avito_reviewed_drive_belts import load_reviewed_belts
from avito_belt_release import make_ad,append_ads
from avito_wholesale_live_api_refresh import list_approved
from avito_active_feed_refresh import key,seller_sku,APPROVED_CATALOG_LIMIT

class Source05Release(unittest.TestCase):
    def test_411_ad_append_only_and_api_refresh_scope(self):
        from test_avito_active_feed_refresh import fixture
        raw,_,_=fixture(count=329,absent=0)
        records=load_reviewed_belts(Path(__file__).resolve().parents[1]/'input/avito_reviewed_drive_belts_source05.json')
        ads=[make_ad(r,1500,{'public_url':'https://example.test/photo.jpg'},'Иркутск') for r in records]
        result=append_ads(raw,ads)
        self.assertEqual(len(list_approved(result)),411)
        self.assertEqual([E.tostring(a) for a in E.fromstring(raw)],[E.tostring(a) for a in E.fromstring(result)][:329])

    def test_exact_82_scope_and_reject_changed_article(self):
        p=Path(__file__).resolve().parents[1]/'input/avito_reviewed_drive_belts_source05.json'
        records=load_reviewed_belts(p);self.assertEqual(len(records),82)
        for r in records:
            self.assertEqual(seller_sku(make_ad(r,1500,{'public_url':'https://example.test/photo.jpg'},'Иркутск')),(key(r['brand'],r['article']),'Ремни приводные'))
        bad=json.loads(p.read_text());bad['items'][0]['article']='OTHER'
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'bad.json';f.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):load_reviewed_belts(f)
        self.assertEqual(APPROVED_CATALOG_LIMIT,467)
