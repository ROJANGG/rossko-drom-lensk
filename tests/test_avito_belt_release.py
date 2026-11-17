import copy
import html
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from avito_reviewed_drive_belts import load_reviewed_belts
from avito_belt_release import validate_source, make_ad, append_ads
from avito_wholesale_live_api_refresh import list_approved
from test_avito_active_feed_refresh import fixture

class BeltReleaseTest(unittest.TestCase):
    def setUp(self):
        self.records = load_reviewed_belts(Path(__file__).resolve().parent.parent/'input/avito_reviewed_drive_belts.json')

    def source_fixture(self):
        r = copy.deepcopy(self.records[0])
        r['fitment_page'] = 'https://ecatalogue.lynxauto.jp/applicability.php?mark=BMW'
        r['fitment'] = 'BMW MODEL, ENGINE'
        page = '<span itemprop="mpn">'+r['article']+'</span><table class="pcard-oeno-bottom"><tr><td>BMW</td><td>'+r['oem']+'</td></tr></table><div class="pcard-list-mark-item" data-link="'+html.escape(r['fitment_page'])+'"></div><div class="pcard-images"><a class="lightbox" href="'+html.escape(r['photo_url'])+'">photo</a></div>'
        return r, page, '<table><tr><td>MODEL</td><td>ENGINE</td></tr></table>'

    def test_reject_changed_sku_oe_photo_and_applicability(self):
        r, page, fit = self.source_fixture()
        self.assertTrue(validate_source(r, page, fit))
        for bad in [page.replace(r['article'], 'OTHER'), page.replace(r['oem'], 'OTHER'), page.replace(r['photo_url'], 'https://ecatalogue.lynxauto.jp/other.jpg')]:
            with self.assertRaises(ValueError):
                validate_source(r, bad, fit)
        with self.assertRaises(ValueError):
            validate_source(r, page, fit.replace('MODEL', 'OTHER'))
        with self.assertRaises(ValueError):
            validate_source(r, page.replace('pcard-oeno-bottom', 'aftermarket-analogs'), fit)

    def test_85_append_only_and_all_330_can_be_api_refreshed(self):
        raw, _, _ = fixture(count=245, absent=0)
        ads = [make_ad(r, 1500, {'public_url': 'https://example.test/'+r['article']+'.jpg'}, 'Иркутск') for r in self.records]
        result = append_ads(raw, ads)
        self.assertEqual(len(list_approved(result)), 330)
        self.assertEqual([ET.tostring(a) for a in ET.fromstring(raw)], [ET.tostring(a) for a in ET.fromstring(result)][:245])
        with self.assertRaises(ValueError):
            append_ads(result, [ads[0]])

if __name__ == '__main__':
    unittest.main()
