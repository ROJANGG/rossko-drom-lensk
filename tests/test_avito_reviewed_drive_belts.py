import copy
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_active_feed_refresh import key, seller_sku, plan, supplier_products, APPROVED_CATALOG_LIMIT
from avito_reviewed_drive_belts import load_reviewed_belts, ENGINE_TYPE
from test_avito_active_feed_refresh import fixture

MANIFEST = Path(__file__).resolve().parent.parent / 'input/avito_reviewed_drive_belts.json'


class ReviewedBeltsTest(unittest.TestCase):
    def setUp(self):
        self.records = load_reviewed_belts(MANIFEST)

    def ad(self, record):
        root = ET.Element('Ad')
        for k, v in {'Id': 'belt-' + record['article'],
                     'Title': 'Ремень приводной LYNXauto ' + record['article'] + ' новый',
                     'Brand': 'LYNXauto', 'SparePartType': 'Двигатель',
                     'EngineSparePartType': ENGINE_TYPE, 'OEM': record['oem'],
                     'Description': record['fitment'], 'Price': '1500'}.items():
            ET.SubElement(root, k).text = v
        ET.SubElement(ET.SubElement(root, 'Images'), 'Image', url=record['photo_url'])
        return root

    def test_all_85_round_trip_and_unreviewed_sku_is_rejected(self):
        for r in self.records:
            self.assertEqual(seller_sku(self.ad(r)), (key(r['brand'], r['article']), 'Ремни приводные'))
        a = self.ad(self.records[0])
        a.find('Title').text = 'Ремень приводной LYNXauto UNREVIEWED новый'
        with self.assertRaises(ValueError):
            seller_sku(a)

    def test_wrong_brand_and_wrong_engine_type_are_rejected(self):
        for field in ('Brand', 'EngineSparePartType', 'SparePartType'):
            a = self.ad(self.records[0])
            a.find(field).text = 'OTHER'
            with self.assertRaises(ValueError):
                seller_sku(a)

    def test_changed_scope_or_unverified_photo_is_rejected(self):
        original = json.loads(MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as place:
            p = Path(place) / 'manifest.json'
            for field, value in [('article', 'OTHER'), ('photo_review', 'DIAGRAM'),
                                 ('photo_url', 'https://example.org/photo.jpg')]:
                changed = copy.deepcopy(original)
                changed['items'][0][field] = value
                p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    load_reviewed_belts(p)

    def test_330_ad_refresh_preserves_all_existing_and_unconfirmed_belt_prices(self):
        raw, products, retail = fixture(count=245, absent=0)
        root = ET.fromstring(raw)
        for r in self.records:
            root.append(self.ad(r))
            k = key(r['brand'], r['article'])
            products[k] = {'Группа': 'Ремни приводные', 'Остаток РОССКО': 2,
                           'Срок поставки': 0, '_source_list_price': 1000}
        before = [ET.tostring(a) for a in root.findall('Ad')]
        # No API verification for these new belt keys: prices must stay intact.
        result, report = plan(ET.tostring(root), products, retail, freshly_verified=set())
        self.assertEqual(len(ET.fromstring(result).findall('Ad')), 330)
        self.assertEqual([ET.tostring(a) for a in ET.fromstring(result).findall('Ad')], before)
        self.assertEqual(report['repriced'], 0)
        self.assertEqual(APPROVED_CATALOG_LIMIT, 851)

    def test_supplier_gate_rejects_wrong_city_delivery_stock_and_unknown_sku(self):
        from openpyxl import Workbook
        book = Workbook()
        ws = book.active
        ws.append(['Бренд', 'Артикул', 'Описание', 'Цена, руб.', 'Наличие',
                   'Срок поставки, дн.', 'Город склада'])
        for r, city, days, stock in [(self.records[0], 'Иркутск', 0, 2),
                                     (self.records[1], 'Москва', 0, 2),
                                     (self.records[2], 'Иркутск', 2, 2),
                                     (self.records[3], 'Иркутск', 0, 0),
                                     (self.records[4], 'Иркутск', 0, -2)]:
            ws.append([r['brand'], r['article'], 'Ремень приводной', 1000, stock, days, city])
        ws.append(['LYNXauto', 'UNREVIEWED', 'Ремень приводной', 1000, 2, 0, 'Иркутск'])
        products = supplier_products(book, {'avito': {'pickup_address': 'Иркутск'}})
        book.close()
        self.assertEqual([(p['Бренд'], p['Артикул']) for p in products.values()],
                         [('LYNXauto', self.records[0]['article'])])


if __name__ == '__main__':
    unittest.main()
