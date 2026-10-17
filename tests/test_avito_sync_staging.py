"""Pure, offline tests of stock/OEM safety gates for Avito staging."""
import tempfile
import unittest
from pathlib import Path

from avito_sync_staging import evaluate, load_verified_oem


class AvitoStockStagingTests(unittest.TestCase):
    def test_only_verified_evidence_and_positive_local_stock_are_exported(self):
        allow = {"ctr|gd0156", "masterkit|77r036", "krauf|hnq2139gq"}
        products = [
            {"Бренд": "CTR", "Артикул": "GD0156", "Группа": "Тормозные диски",
             "Остаток РОССКО": 3, "Цена Авито": 4000, "Применимость": "Hyundai"},
            {"Бренд": "Krauf", "Артикул": "HNQ2139GQ", "Группа": "Рулевые рейки",
             "Остаток РОССКО": 1, "Цена Авито": 49500, "Применимость": "Peugeot"},
        ]
        photos = {
            "ctr|gd0156": "https://imgs.rossko.ru/00/11/a/1.jpg",
            "krauf|hnq2139gq": "https://imgs.rossko.ru/00/22/b/1.jpg",
        }
        verified = {"ctr|gd0156": "584110U300"}
        ready, audit = evaluate(allow, products, photos, verified)
        self.assertEqual([(x["Бренд"], x["Артикул"]) for x in ready], [("CTR", "GD0156")])
        self.assertEqual({x["sku_key"]:x["status"] for x in audit}, {
            "ctr|gd0156": "staging_xml_ready",
            "krauf|hnq2139gq": "needs_documented_OEM_cross_reference",
            "masterkit|77r036": "out_of_stock_or_not_zero_day_in_irkutsk",
        })

    def test_oem_list_rejects_undocumented_number(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"oem.csv"
            p.write_text("brand;article;oem_number;source\nCTR;GD0156;FAKEOEM;https://example.org/evidence\n",encoding="utf-8")
            with self.assertRaises(ValueError):
                load_verified_oem(p, {"ctr|gd0156"})

    def test_only_known_supplier_picture_hosts_are_allowed(self):
        allow = {"ctr|gd0156"}
        p = {"Бренд":"CTR", "Артикул":"GD0156", "Группа":"Тормозные диски",
             "Остаток РОССКО":1,"Цена Авито":4500}
        ready, audit = evaluate(allow,[p],{"ctr|gd0156":"https://malicious.example/a.jpg"},{"ctr|gd0156":"584110U300"})
        self.assertEqual(ready,[])
        self.assertEqual(audit[0]["status"],"missing_supplier_photo")


if __name__=="__main__":
    unittest.main()
