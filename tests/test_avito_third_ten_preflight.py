"""Regression tests for a guarded +10 CTR Avito rollout."""
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_xml_v3_diagnostic import TEST_SKUS, build_xml
from avito_expand_canary import CANARY
from avito_next_five_preflight import EXTRA_ARTICLES as FIRST_FIVE
from avito_second_five_preflight import EXTRA_ARTICLES as SECOND_FIVE
from avito_third_ten_preflight import (
    EXTRA_ARTICLES, GROUP, assemble, approved_third_ten_ids, read_evidence
)
from avito_feed_transition import analyze_transition
from avito_image_mirror import image_urls_for_pilot, public_photo_url

def previous_feed():
    original = [{
        "Группа": group, "Бренд": brand, "Артикул": article,
        "Цена ₽": 6000, "Остаток": 2,
        "Фото URL": "https://imgs.rossko.ru/12/34/NSIIBASE/1.jpg"
    } for group, pairs in TEST_SKUS.items() for brand, article in pairs]
    root = ET.fromstring(build_xml(original))
    extras = [article for brand, article in CANARY] + list(FIRST_FIVE) + list(SECOND_FIVE)
    additional = [{
        "Группа": GROUP, "Бренд": "CTR", "Артикул": article,
        "Цена ₽": 7500, "Остаток": 3,
        "Фото URL": "https://imgs.rossko.ru/12/34/NSIIEXTRA/1.jpg",
    } for article in extras]
    verified = {"ctr|"+a.casefold(): "123456"+str(i) for i,a in enumerate(extras)}
    for ad in ET.fromstring(build_xml(additional, verified_extra_oems=verified)).findall("Ad"):
        root.append(ad)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

def ten_data():
    rows, photos, nomenclatures, oems = [], {}, {}, {}
    for index, article in enumerate(EXTRA_ARTICLES):
        nom = f"NSII_TEN_{index:04d}"
        rows.append({"Группа": GROUP, "Бренд": "CTR", "Артикул": article,
                     "Остаток РОССКО": 3, "Цена Авито": 5000+50*index})
        photos["ctr|"+article.casefold()] = f"https://imgs.rossko.ru/12/34/{nom}/1.jpg"
        nomenclatures[("ctr", article.casefold())] = nom
        oems["ctr|"+article.casefold()] = "781234"+str(index)
    return rows, photos, nomenclatures, oems

def all_extra_ids():
    ids = {stable_id(GROUP, "CTR", a) for brand,a in CANARY}
    ids |= {stable_id(GROUP, "CTR", a) for a in FIRST_FIVE}
    ids |= {stable_id(GROUP, "CTR", a) for a in SECOND_FIVE}
    ids |= approved_third_ten_ids()
    return ids

class ThirdTenReleaseTests(unittest.TestCase):
    def test_previous_62_ids_unchanged_and_ten_added(self):
        before = previous_feed()
        rows, photos, nomenclatures, oems = ten_data()
        proposed, audit = assemble(before,rows,photos,nomenclatures,oems,
                                   image_check=lambda _:True)
        old = {a.findtext("Id") for a in ET.fromstring(before).findall("Ad")}
        after = {a.findtext("Id") for a in ET.fromstring(proposed).findall("Ad")}
        self.assertEqual(len(old),62)
        self.assertEqual(len(after),72)
        self.assertTrue(old.issubset(after))
        self.assertEqual(after-old,approved_third_ten_ids())
        self.assertEqual(audit["new"],10)
        report = analyze_transition(before,proposed,approved_extra_ids=all_extra_ids())
        self.assertEqual((report["added"], report["removed"]), (10,0))
        self.assertEqual(len(image_urls_for_pilot(proposed,extra_ids=all_extra_ids())),72)
        new_id = stable_id(GROUP,"CTR","GD0149")
        self.assertTrue(public_photo_url(new_id,"part.jpg").startswith("https://cdn.jsdelivr.net/"))
        self.assertEqual(analyze_transition(proposed,proposed,approved_extra_ids=all_extra_ids())["added"],0)

    def test_missing_stock_and_mismatched_photo_fail(self):
        rows, photos, nomenclatures, oems = ten_data()
        with self.assertRaisesRegex(ValueError,"freshly verified"):
            assemble(previous_feed(),rows[:-1],photos,nomenclatures,oems)
        with self.assertRaisesRegex(ValueError,"Photo filename"):
            wrong=dict(photos)
            wrong["ctr|gd0058"]="https://imgs.rossko.ru/12/34/WRONG/1.jpg"
            assemble(previous_feed(),rows,wrong,nomenclatures,oems)
        with self.assertRaisesRegex(ValueError,"image bytes"):
            assemble(previous_feed(),rows,photos,nomenclatures,oems,image_check=lambda _:False)

    def test_recurring_stock_checks_limit_two_missing(self):
        rows, photos, nomenclatures, oems = ten_data()
        proposal, report = assemble(previous_feed(),rows[:-2],photos,nomenclatures,oems,
                                    allow_small_stock_removals=True)
        self.assertEqual((report["new"],len(report["omitted_for_local_stock"])),(8,2))
        with self.assertRaisesRegex(ValueError,"freshly verified"):
            assemble(previous_feed(),rows[:-3],photos,nomenclatures,oems,
                     allow_small_stock_removals=True)

    def test_evidence_requires_exact_source_and_ten_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/"oem.csv"
            header="brand;article;proposed_original_oem;source;verification_status\n"
            lines=[
                f"CTR;{article};123456{i};https://ctr.co.ru/catalog/{article};MANUFACTURER_OEM_CATALOG_REVIEW\n"
                for i,article in enumerate(EXTRA_ARTICLES)
            ]
            file.write_text(header+"".join(lines),encoding="utf-8")
            self.assertEqual(len(read_evidence(file)),10)
            file.write_text(header+"".join(lines[:-1]),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Not all ten"):
                read_evidence(file)

    def test_unplanned_eleventh_id_rejected(self):
        rows,photos,nomenclatures,oems=ten_data()
        candidate,_=assemble(previous_feed(),rows,photos,nomenclatures,oems)
        evil=all_extra_ids()|{stable_id(GROUP,"CTR","GD9999")}
        with self.assertRaisesRegex(ValueError,"Unexpected additional"):
            image_urls_for_pilot(candidate,extra_ids=evil)
        with self.assertRaisesRegex(ValueError,"Unexpected additional"):
            analyze_transition(previous_feed(),candidate,approved_extra_ids=evil)

if __name__=="__main__":
    unittest.main()
