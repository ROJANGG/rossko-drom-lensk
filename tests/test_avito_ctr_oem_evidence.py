import tempfile
import unittest
from pathlib import Path

from avito_ctr_oem_evidence import documented_ctr_oems, read_ctr_pinned


class CTROEMTests(unittest.TestCase):
    def test_realistic_manufacturer_article_and_oem_section(self):
        html = """<html><h1>Диск тормозной CTR GD0037</h1>
        <div>Артикул:GD0037</div><p>OEM-номера:</p>
        <div>43206-EB300 43206-EA000 43206-EB30A</div>
        <p>* Результаты поиска по марке и модели носят справочный характер.</p>
        <h2>Применимость</h2></html>"""
        self.assertEqual(documented_ctr_oems(html, "GD0037"),
                         ["43206EB300", "43206EA000", "43206EB30A"])
        self.assertEqual(documented_ctr_oems(html, "GD0031"), [])

    def test_reject_unlabeled_text_and_wrong_article(self):
        html = "<div>CTR GD0037 Артикул:GD0037 43206-EB300</div>"
        self.assertEqual(documented_ctr_oems(html, "GD0037"), [])
        html = "<div>CTR GD0037 Артикул:GD0037 OEM-номера: GD0037 Применимость</div>"
        self.assertEqual(documented_ctr_oems(html, "GD0037"), ["GD0037"])

    def test_filter_only_original_100_and_ctr(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"skus.csv"
            rows=["brand;article"] + [f"CTR;GD{i:04d}" for i in range(33)] + [
                f"NGN;{100000+i}" for i in range(67)]
            p.write_text("\n".join(rows)+"\n",encoding="utf-8")
            self.assertEqual(len(read_ctr_pinned(p)), 33)
            rows[-1]=rows[1]
            p.write_text("\n".join(rows)+"\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Duplicate"):
                read_ctr_pinned(p)


if __name__ == "__main__":
    unittest.main()
