"""Offline regression tests for new-disc read-only audit and stable IDs."""
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import Workbook

from avito_feed import stable_id
from avito_remaining_discs_audit import collect_candidates, current_ids


class RemainingDiscsAuditTests(unittest.TestCase):
    def make_feed(self, duplicate=False):
        root = ET.Element("Ads", {"formatVersion": "3"})
        for i in range(145):
            ad = ET.SubElement(root, "Ad")
            ET.SubElement(ad, "Id").text = str(0 if duplicate else i)
        return ET.tostring(root, encoding="utf-8")

    def test_requires_at_least_145_unique_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "live.xml"
            path.write_bytes(self.make_feed())
            self.assertEqual(len(current_ids(path)), 145)
            path.write_bytes(self.make_feed(duplicate=True))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                current_ids(path)
            path.write_bytes(b'<Ads formatVersion="3"><Ad><Id>a</Id></Ad></Ads>')
            with self.assertRaisesRegex(ValueError, "smaller than 145"):
                current_ids(path)

    def test_only_unpublished_local_in_stock_discs(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Бренд", "Артикул", "Описание", "Цена, руб.",
                      "Наличие", "Срок поставки, дн.", "Город склада",
                      "Номенклатура", "OEМ Номер"])
        sheet.append(["CTR", "GDTEST1", "Диск тормозной", 2000, 3, 0, "Иркутск", "NOM1", ""])
        sheet.append(["CTR", "GDTEST2", "Диск тормозной", 3000, 2, 0, "Иркутск", "NOM2", ""])
        sheet.append(["CTR", "GDTEST3", "Диск тормозной", 3000, 0, 0, "Иркутск", "NOM3", ""])
        sheet.append(["CTR", "GDTEST4", "Диск тормозной", 3000, 3, 0, "Москва", "NOM4", ""])
        sheet.append(["CTR", "GDTEST5", "Диск тормозной", 3000, 3, 1, "Иркутск", "NOM5", ""])
        sheet.append(["CTR", "STEERING", "Рейка рулевая", 3000, 3, 0, "Иркутск", "NOM6", ""])
        config = {"avito": {"pickup_address": "Иркутск, тестовый адрес"}}
        photos = {"ctr|gdtest1": "https://imgs.rossko.ru/NOM1/1.jpg",
                  "ctr|gdtest2": "https://imgs.rossko.ru/NOM2/1.jpg"}
        published = {stable_id("Тормозные диски", "CTR", "GDTEST1")}
        candidates, source, total = collect_candidates(workbook, config, photos, published)
        self.assertEqual(total, 2)
        self.assertEqual([row["Артикул"] for row in candidates], ["GDTEST2"])
        self.assertEqual(source[("ctr", "gdtest2")]["nomenclature"], "NOM2")


if __name__ == "__main__":
    unittest.main()
