"""Ensure Avito XML test has the v3 root and stable, nonempty IDs."""
import unittest
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_xml_v3_diagnostic import build_xml


class TestAvitoXmlDiagnostic(unittest.TestCase):
    def test_two_ads_have_original_ids(self):
        items = [
            {
                "Группа": "Тормозные диски",
                "Бренд": "CTR",
                "Артикул": "GD0156",
                "Цена ₽": "3850",
                "Остаток": "2",
                "Фото URL": "https://imgs.rossko.ru/5F/48/NSII0026903735/9.jpg",
                "Применимость РОССКО": "Hyundai Solaris",
            },
            {
                "Группа": "Рулевые рейки",
                "Бренд": "Master KiT",
                "Артикул": "77R036",
                "Цена ₽": "21400",
                "Остаток": "6",
                "Фото URL": "https://imgs.rossko.ru/12/89/NSII0018148865/1.jpg",
                "Применимость РОССКО": "Nissan Qashqai",
            },
        ]
        doc = ET.fromstring(build_xml(items))
        self.assertEqual(doc.tag, "Ads")
        self.assertEqual(doc.attrib.get("formatVersion"), "3")
        ads = doc.findall("./Ad")
        self.assertEqual(len(ads), 2)
        self.assertEqual(
            [ad.findtext("Id") for ad in ads],
            [stable_id(i["Группа"], i["Бренд"], i["Артикул"]) for i in items],
        )
        self.assertEqual(len({ad.findtext("Id") for ad in ads}), 2)
        for ad in ads:
            self.assertTrue(ad.findtext("Category"))
            self.assertTrue(ad.findtext("Price"))
            self.assertTrue(ad.findtext("Address"))
            self.assertIsNotNone(ad.find("./Images/Image").attrib.get("url"))


if __name__ == "__main__":
    unittest.main()
