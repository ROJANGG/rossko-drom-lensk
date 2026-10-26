"""Offline regression tests: safe XML staging without changing published IDs."""
import unittest
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_remaining_discs_candidate_xml import (build_review_xml, eligible_by_article)


def live_feed():
    root=ET.Element("Ads",{"formatVersion":"3","target":"Avito.ru"})
    for i in range(144):
        ad=ET.SubElement(root,"Ad")
        ET.SubElement(ad,"Id").text=f"old-{i:03d}"
        ET.SubElement(ad,"Price").text="8000"
    return ET.tostring(root,encoding="utf-8")


def stock(article="361366", status="available_unverified"):
    return {"brand":"NGN", "article":article,
            "photo_status":status, "photo_path_matches_nomenclature":"yes",
            "image_sha256":"e"*64,
            "photo_url":"https://imgs.rossko.ru/12/1/NOM123/0.jpg",
            "irkutsk_stock":"5", "avito_price_rub":"5000",
            "delivery_days":"0"}


def oem(article="361366"):
    return {"brand":"NGN", "article":article,
            "source_status":"NGN_EXACT_SKU_MANUFACTURER_SOURCE",
            "maker":"SUZUKI", "verified_oem_candidate":"5521165J00",
            "manufacturer_exact_sku_page":f"https://ngn-parts.com/36-{article[2:]}.html"}


class CandidateXmlTests(unittest.TestCase):
    def test_preserves_all_existing_ids_exactly(self):
        source=live_feed()
        xml,audit,old,added=build_review_xml(source,[stock()],[oem()],set())
        prior=ET.fromstring(source).findall("Ad")
        merged=ET.fromstring(xml).findall("Ad")
        self.assertEqual((old,added,len(merged)),(144,1,145))
        self.assertEqual([[ (field.tag, field.attrib, field.text) for field in x] for x in prior],
                         [[ (field.tag, field.attrib, field.text) for field in x] for x in merged[:-1]])
        self.assertEqual(merged[-1].findtext("Id"),
                         stable_id("Тормозные диски","NGN","361366"))
        self.assertEqual(merged[-1].findtext("OEM"),"5521165J00")

    def test_reserved_or_poor_photo_never_added(self):
        reserved={("ngn","361366")}
        chosen,logs=eligible_by_article([stock()],[oem()],set(),reserved)
        self.assertEqual(chosen,[])
        self.assertEqual(logs[0]["status"],"OLD_OR_RESERVED_SKU")
        chosen,logs=eligible_by_article([stock(status="technical_drawing_replace_photo")],
                                         [oem()],set(),set())
        self.assertEqual(chosen,[])
        self.assertEqual(logs[0]["status"],"NO_USABLE_PRODUCT_PHOTO")

    def test_fake_maker_or_wrong_original_sku_source_rejected(self):
        evidence=oem()
        evidence["manufacturer_exact_sku_page"]="https://ngn-parts.com/36-9999.html"
        chosen,logs=eligible_by_article([stock()],[evidence],set(),set())
        self.assertEqual(chosen,[])
        self.assertEqual(logs[0]["status"],"MISSING_ORIGINAL_MANUFACTURER_OEM")
        evidence=oem()
        evidence["maker"]="FENOX"
        chosen,logs=eligible_by_article([stock()],[evidence],set(),set())
        self.assertEqual(chosen,[])

    def test_no_unexpected_shrink_or_duplicates(self):
        root=ET.fromstring(live_feed())
        for item in root.findall("Ad")[139:]:
            root.remove(item)
        with self.assertRaisesRegex(ValueError,"shrink"):
            build_review_xml(ET.tostring(root),[stock()],[oem()],set())
        root=ET.fromstring(live_feed())
        root.findall("Ad")[-1].find("Id").text="old-000"
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            build_review_xml(ET.tostring(root),[stock()],[oem()],set())


if __name__=="__main__":
    unittest.main()
