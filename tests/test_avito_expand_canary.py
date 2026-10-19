import csv
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_expand_canary import CANARY, approved_canary_ids, read_canary, extend_xml
from avito_feed import stable_id
from avito_feed_transition import analyze_transition
from avito_image_mirror import image_urls_for_pilot
from avito_xml_v3_diagnostic import build_xml, TEST_SKUS


def pilot_rows():
    return [{
        "Группа": group, "Бренд":brand, "Артикул":article,
        "Цена ₽":9000, "Остаток":1,
        "Фото URL":"https://imgs.rossko.ru/12/34/NSII0000000000/1.jpg",
    } for group, rows in TEST_SKUS.items() for brand,article in rows]


def extras():
    return [{
        "Группа":"Тормозные диски", "Бренд":"CTR", "Артикул":article,
        "Остаток РОССКО":3, "Цена Авито":3000
    } for article in ("GD0037","GD0053")]


def photos():
    return {
        "ctr|gd0037":"https://imgs.rossko.ru/12/34/NSII001/1.jpg",
        "ctr|gd0053":"https://imgs.rossko.ru/12/34/NSII002/1.jpg",
    }


def full():
    pilot=build_xml(pilot_rows())
    approved={("ctr","gd0037"):"43206EB300", ("ctr","gd0053"):"40206EM10A"}
    info={("ctr","gd0037"):"NSII001", ("ctr","gd0053"):"NSII002"}
    expanded,meta=extend_xml(pilot,approved,extras(),photos(),info,require_two=True)
    return pilot,expanded,meta


class CanaryTests(unittest.TestCase):
    def test_two_new_oem_verified_and_old_ids_preserved(self):
        old,new,meta=full()
        o=ET.fromstring(old)
        n=ET.fromstring(new)
        oids={x.findtext("Id") for x in o.findall("Ad")}
        nids={x.findtext("Id") for x in n.findall("Ad")}
        self.assertEqual(len(oids),50)
        self.assertEqual(len(nids),52)
        self.assertTrue(oids <= nids)
        self.assertEqual(meta["new_in_stock"],2)
        self.assertEqual(meta["total"],52)
        self.assertTrue({stable_id("Тормозные диски", "CTR", x) for x in ("GD0037","GD0053")} <= nids)
        oems={a.findtext("Id"):a.findtext("OEM") for a in n.findall("Ad")}
        self.assertEqual(oems[stable_id("Тормозные диски","CTR","GD0037")],"43206EB300")
        self.assertEqual(oems[stable_id("Тормозные диски","CTR","GD0053")],"40206EM10A")

    def test_expansion_approved_transition_not_arbitrary(self):
        old,new,_=full()
        with self.assertRaisesRegex(ValueError,"Unexpected new"):
            analyze_transition(old,new)
        ids={stable_id("Тормозные диски","CTR",s) for s in ("GD0037","GD0053")}
        report=analyze_transition(old,new,approved_extra_ids=ids)
        self.assertEqual(report["added"],2)
        self.assertEqual(report["removed"],0)
        self.assertEqual(report["current_ads"],52)
        with self.assertRaisesRegex(ValueError,"unexpected|Unexpected|too many"):
            image_urls_for_pilot(new)
        self.assertEqual(len(image_urls_for_pilot(new,extra_ids=ids)),52)

    def test_unavailable_on_first_release_fails_closed(self):
        old,_,_=full()
        approved={("ctr","gd0037"):"43206EB300", ("ctr","gd0053"):"40206EM10A"}
        nomenclatures={("ctr","gd0037"):"NSII001", ("ctr","gd0053"):"NSII002"}
        with self.assertRaisesRegex(ValueError,"requires both"):
            extend_xml(old,approved,extras()[:1],photos(),nomenclatures,require_two=True)
        out,audit=extend_xml(old,approved,extras()[:1],photos(),nomenclatures)
        self.assertEqual(len(ET.fromstring(out).findall("Ad")),51)
        self.assertEqual(audit["missing_new"],["ctr|gd0053"])

    def test_unverified_supplier_image_path_blocks(self):
        old,_,_=full()
        bad=photos()
        bad["ctr|gd0037"]="https://imgs.rossko.ru/12/34/NOT_THIS/1.jpg"
        with self.assertRaisesRegex(ValueError,"nomenclature"):
            extend_xml(old,{("ctr","gd0037"):"43206EB300",("ctr","gd0053"):"40206EM10A"},
                       extras(),bad,{("ctr","gd0037"):"NSII001",("ctr","gd0053"):"NSII002"},
                       require_two=True)

    def test_canary_strict_scope_and_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            manifest=root/"allowed.csv"
            evidence=root/"evidence.csv"
            manifest.write_text("brand;article\\nCTR;GD0037\\nCTR;GD0053\\n".replace("\\n","\n"))
            evidence.write_text(
                "brand;article;proposed_original_oem;source;verification_status\n"+
                "CTR;GD0037;43206EB300;https://ctr.co.ru/catalog/GD0037;MANUFACTURER_OEM_CATALOG_REVIEW\n"+
                "CTR;GD0053;40206EM10A;https://ctr.co.ru/catalog/GD0053;MANUFACTURER_OEM_CATALOG_REVIEW\n"
            )
            self.assertEqual(len(approved_canary_ids(manifest)),2)
            self.assertEqual(len(read_canary(manifest,evidence)),2)
            manifest.write_text("brand;article\nCTR;GD0037\nCTR;GD0038\n")
            with self.assertRaisesRegex(ValueError,"EXACTLY"):
                read_canary(manifest,evidence)


if __name__=="__main__":
    unittest.main()
