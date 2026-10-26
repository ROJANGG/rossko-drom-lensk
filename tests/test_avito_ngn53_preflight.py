"""Offline release safeguards for 53 new NGN brake discs."""
import unittest
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_ngn53_preflight import pinned_oem_evidence, assemble


def old_xml(count=144):
    root=ET.Element("Ads", {"formatVersion":"3", "target":"Avito.ru"})
    for i in range(count):
        ad=ET.SubElement(root,"Ad")
        ET.SubElement(ad,"Id").text=f"old-{i}"
        ET.SubElement(ad,"Price").text="5000"
    return ET.tostring(root,encoding="utf-8")


def stock():
    return {"Группа":"Тормозные диски","Бренд":"NGN","Артикул":"361366",
            "Остаток РОССКО":2,"Цена Авито":7750,"Срок поставки":0}


class TestNGN53Preflight(unittest.TestCase):
    def test_manifest_is_exactly_53_manufacturer_oem_articles(self):
        evidence=pinned_oem_evidence()
        self.assertEqual(len(evidence),53)
        self.assertEqual(evidence["361366"]["oem"],"5521165J00")
        self.assertEqual(evidence["361366"]["source"],"https://ngn-parts.com/36-1366.html")

    def test_addition_retains_prior_ids_and_preserves_sourced_price(self):
        photos={"ngn|361366":"https://imgs.rossko.ru/AB/12/NOM1/1.jpg"}
        evidence={"361366":{"oem":"5521165J00","maker":"SUZUKI",
                             "source":"https://ngn-parts.com/36-1366.html"}}
        prev=old_xml()
        out,report=assemble(prev,[stock()],photos,{("ngn","361366"):"NOM1"},evidence)
        root=ET.fromstring(out)
        ads=root.findall("Ad")
        self.assertEqual(len(ads),145)
        self.assertEqual([x.findtext("Id") for x in ads[:-1]],
                         [x.findtext("Id") for x in ET.fromstring(prev).findall("Ad")])
        new=ads[-1]
        self.assertEqual(new.findtext("Id"),stable_id("Тормозные диски","NGN","361366"))
        self.assertEqual(new.findtext("Price"),"7750")
        self.assertEqual(new.findtext("OEM"),"5521165J00")
        self.assertEqual(report["added"],1)

    def test_fail_closed_bad_photo_duplicate_id_unexpected_stock_loss(self):
        url="https://imgs.rossko.ru/AB/12/NOM1/1.jpg"
        evidence={"361366":{"oem":"5521165J00","maker":"SUZUKI",
                             "source":"https://ngn-parts.com/36-1366.html"}}
        with self.assertRaisesRegex(ValueError,"nomenclature"):
            assemble(old_xml(),[stock()],{"ngn|361366":url},
                     {("ngn","361366"):"DIFFERENT"},evidence)
        root=ET.fromstring(old_xml())
        root[0].find("Id").text=stable_id("Тормозные диски","NGN","361366")
        with self.assertRaisesRegex(ValueError,"Already-existing"):
            assemble(ET.tostring(root),[stock()],{"ngn|361366":url},
                     {("ngn","361366"):"NOM1"},evidence)
        with self.assertRaisesRegex(ValueError,"out of Irkutsk stock"):
            assemble(old_xml(),[],{}, {}, evidence,max_missing=0)
        with self.assertRaisesRegex(ValueError,"missing or duplicate"):
            assemble(old_xml(2),[stock()],{"ngn|361366":url},
                     {("ngn","361366"):"NOM1"},evidence)


if __name__=="__main__":
    unittest.main()
