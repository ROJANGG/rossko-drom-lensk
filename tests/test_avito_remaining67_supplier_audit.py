import csv
import tempfile
import unittest
from pathlib import Path

from avito_remaining67_supplier_audit import read_manifest, audit, sku


class Remaining67SafetyTests(unittest.TestCase):
    def test_requires_exactly_67_unique_brand_article_keys(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"manifest.csv"
            rows=["brand;article"]+[f"NGN;{i}" for i in range(67)]
            file.write_text("\n".join(rows)+"\n",encoding="utf-8")
            self.assertEqual(len(read_manifest(file)),67)
            rows[-1]=rows[1]
            file.write_text("\n".join(rows)+"\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"67 unique"):
                read_manifest(file)

    def test_raw_supplier_oem_does_not_become_verified_oem(self):
        item={"brand":"NGN","article":"361431"}
        key=sku("NGN","361431")
        p={key:{"Группа":"Тормозные диски","Остаток РОССКО":4,"Цена Авито":5400}}
        raw={key:{"raw_oem":"5Q0-615-601-F","catalog":"361431","nomenclature":"NSII123"}}
        photos={key:"https://imgs.rossko.ru/12/34/NSII123/1.jpg"}
        actual=audit([item],p,raw,photos)[0]
        self.assertEqual(actual["supplier_raw_oem_candidate"],"5Q0-615-601-F")
        self.assertEqual(actual["verified_manufacturer_oem"],"")
        self.assertEqual(actual["approved_for_publication"],"NO")
        self.assertEqual(actual["block_reason"],"MISSING_VERIFIED_OEM_EVIDENCE")

    def test_missing_stock_or_wrong_photo_blocks(self):
        item={"brand":"NGN","article":"361431"}
        key=sku("NGN","361431")
        raw={key:{"raw_oem":"","catalog":"361431","nomenclature":"NSII123"}}
        p={key:{"Группа":"Тормозные диски","Остаток РОССКО":2,"Цена Авито":5400}}
        self.assertEqual(audit([item],{},raw,{})[0]["block_reason"],"NOT_IN_FRESH_IRKUTSK_STOCK")
        self.assertEqual(audit([item],p,raw,{key:"https://imgs.rossko.ru/AB/CD/WRONG/1.jpg"})[0]["block_reason"],"PHOTO_NOMENCLATURE_MISMATCH")


if __name__=="__main__":
    unittest.main()
