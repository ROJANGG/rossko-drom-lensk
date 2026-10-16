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
            self.assertRegex(ad.findtext("OEM") or "", r"^[A-Z0-9]+$")
            # The wholesaler's name belongs in private sourcing, not the public ad.
            self.assertNotIn("росско", (ad.findtext("Description") or "").casefold())
            self.assertIn("совместимость", (ad.findtext("Description") or "").casefold())

    def test_avito_brand_alias_keeps_stable_id(self):
        from avito_xml_v3_diagnostic import avito_brand_name
        self.assertEqual(avito_brand_name("Master KiT"), "MasterKit")
        self.assertEqual(avito_brand_name("Krauf"), "Krauf")
        source = {
            "Группа": "Рулевые рейки",
            "Бренд": "Master KiT",
            "Артикул": "77R036",
            "Цена ₽": "21400", "Остаток": "6",
            "Фото URL": "https://imgs.rossko.ru/12/89/NSII0018148865/1.jpg",
            "Применимость РОССКО": "Nissan Qashqai",
        }
        ad = ET.fromstring(build_xml([source])).find("./Ad")
        self.assertEqual(ad.findtext("Brand"), "MasterKit")
        self.assertIn("Master KiT", ad.findtext("Title"))
        self.assertEqual(ad.findtext("Id"), stable_id("Рулевые рейки", "Master KiT", "77R036"))

    def test_real_oem_for_all_four_pilot_articles(self):
        from avito_xml_v3_diagnostic import verified_oem
        self.assertEqual(verified_oem("CTR", "GD0156"), "584110U300")
        self.assertEqual(verified_oem("Marshall", "M2000404"), "517120U000")
        self.assertEqual(verified_oem("Krauf", "HNQ2139GQ"), "4001L1")
        self.assertEqual(verified_oem("Master KiT", "77R036"), "48001JD900")
        self.assertEqual(verified_oem("CTR", "GD0063"), "6R0615301A")
        self.assertEqual(verified_oem("Marshall", "M2000408"), "517120Z000")
        self.assertEqual(verified_oem("CTR", "GD0004"), "1K0615601AB")
        self.assertEqual(verified_oem("CTR", "GD0008"), "5Q0615601G")
        self.assertEqual(verified_oem("CTR", "GD0009"), "1K0615301AC")
        self.assertEqual(verified_oem("CTR", "GD0026"), "4615A117")
        self.assertEqual(verified_oem("Fenox", "TB219353"), "9064230112")
        self.assertEqual(verified_oem("Marshall", "M2000429"), "5Q0615301F")
        self.assertEqual(verified_oem("Marshall", "M2000745"), "51712L0000")
        self.assertEqual(verified_oem("Krauf", "HNQ5020GQ"), "48001BG10A")
        self.assertEqual(verified_oem("Krauf", "HNQ5047GQ"), "56500A7500")
        self.assertEqual(verified_oem("CTR", "GD0021"), "1K0615601AA")
        self.assertEqual(verified_oem("CTR", "GD0024"), "04743999AA")
        self.assertEqual(verified_oem("CTR", "GD0019"), "7H0615601B")
        self.assertEqual(verified_oem("Krauf", "HNQ2424GQ"), "LR007501")
        self.assertEqual(verified_oem("Krauf", "HNQ5090GQ"), "4550005030")
        self.assertEqual(verified_oem("Krauf", "HNQ9012GQ"), "4551052041")
        self.assertEqual(verified_oem("Krauf", "HNQ9048GQ"), "490018H305")
        self.assertEqual(verified_oem("Krauf", "HNQ9065GQ"), "53601S10013")
        self.assertEqual(verified_oem("Krauf", "HNQ2025GQ"), "4420060012")
        self.assertEqual(verified_oem("Krauf", "HNQ5056GQ"), "4551006061")
        self.assertEqual(verified_oem("Krauf", "HNQ5119GQ"), "4551078022")
        self.assertEqual(verified_oem("Master KiT", "77R010"), "BV613A500AH")
        self.assertEqual(verified_oem("Master KiT", "77R046"), "4551042030")
        self.assertEqual(verified_oem("Master KiT", "77R047"), "4420033320")
        self.assertEqual(verified_oem("Master KiT", "77R070"), "565002L301")
        with self.assertRaises(ValueError):
            verified_oem("Unknown", "NOSUCHSKU")


if __name__ == "__main__":
    unittest.main()
