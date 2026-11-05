import copy
import unittest
from decimal import Decimal
from xml.etree import ElementTree as ET
from avito_active_feed_refresh import plan, key, reconstruct_approved_catalog


def fixture(count=170, absent=6):
    root=ET.Element("Ads",{"formatVersion":"3","target":"Avito.ru"})
    products={}
    retail={}
    for i in range(count):
        article=f"T{i:05}"
        ad=ET.SubElement(root,"Ad")
        ET.SubElement(ad,"Id").text=f"irk-safe-{i:04}"
        ET.SubElement(ad,"Title").text=f"Тормозной диск NGN {article} новый"
        ET.SubElement(ad,"Brand").text="NGN"
        ET.SubElement(ad,"Price").text="3000"
        ET.SubElement(ad,"OEM").text=f"OEM{i:06}"
        ET.SubElement(ad,"Availability").text="В наличии"
        ET.SubElement(ET.SubElement(ad,"Images"),"Image",{"url":f"https://example.org/{i}.jpg"})
        sku=key("NGN",article)
        if i>=absent:
            products[sku]={"Бренд":"NGN","Артикул":article,"Группа":"Тормозные диски",
                           "Остаток РОССКО":2,"Срок поставки":0,"_source_list_price":2000}
        retail[sku]={"supplier_price":Decimal("2000"),"avito_price":2750,"days":0}
    return ET.tostring(root,encoding="utf-8"),products,retail


class ActiveRefreshTest(unittest.TestCase):
    def test_approved_safe_removals_and_price_changes(self):
        old, products, retail=fixture()
        new,report=plan(old,products,retail,second_stock=copy.deepcopy(products))
        self.assertEqual(report["before"],170)
        self.assertEqual(report["after"],164)
        # min_ads guard protects against too-small live XML, so use larger count
        self.assertEqual(report["removed_confirmed_no_stock"],6)
        self.assertEqual(report["repriced"],164)
        oldroot=ET.fromstring(old);newroot=ET.fromstring(new)
        self.assertEqual(len(newroot.findall("Ad")),164)
        for a,b in zip(oldroot.findall("Ad")[6:],newroot.findall("Ad")):
            self.assertEqual(b.findtext("Id"),a.findtext("Id"))
            self.assertEqual(b.findtext("OEM"),a.findtext("OEM"))
            self.assertEqual(b.find("Images/Image").attrib,a.find("Images/Image").attrib)
            self.assertEqual(b.findtext("Price"),"2750")

    def test_disagreement_blocks_removal(self):
        old,products,retail=fixture(count=170)
        second=dict(products)
        second[key("NGN","T00001")]={
            "Группа":"Тормозные диски","Остаток РОССКО":2,
            "Срок поставки":0}
        with self.assertRaisesRegex(ValueError,"snapshots disagree"):
            plan(old,products,retail,second_stock=second)

    def test_unconfirmed_prices_are_unchanged(self):
        old,products,retail=fixture(count=170,absent=0)
        some=key("NGN","T00007")
        retail.pop(some)
        drift=key("NGN","T00008")
        retail[drift]["supplier_price"]=Decimal("999")
        new,report=plan(old,products,retail)
        self.assertEqual(report["repriced"],168)
        self.assertEqual(report["price_kept_unverified"],2)
        ads=ET.fromstring(new).findall("Ad")
        self.assertEqual(ads[7].findtext("Price"),"3000")
        self.assertEqual(ads[8].findtext("Price"),"3000")


    def test_restore_only_approved_previous_skus(self):
        archive,products,retail=fixture(count=170,absent=0)
        root=ET.fromstring(archive)
        old_ids=[x.findtext("Id") for x in root.findall("Ad")]
        root.remove(root.findall("Ad")[3])
        root.remove(root.findall("Ad")[9])
        current=ET.tostring(root)
        universe,restocks=reconstruct_approved_catalog(archive,current,products,retail)
        self.assertEqual(len(restocks),2)
        after=ET.fromstring(universe)
        self.assertEqual([a.findtext("Id") for a in after.findall("Ad")],old_ids)
        self.assertEqual(after.findall("Ad")[3].findtext("Price"),"2750")
        # Existing ads retain their current prices and full metadata.
        self.assertEqual(after.findall("Ad")[0].findtext("Price"),"3000")

    def test_no_restore_without_personal_verified_price(self):
        archive,products,retail=fixture(count=170,absent=0)
        root=ET.fromstring(archive)
        root.remove(root.findall("Ad")[3])
        retail.pop(key("NGN","T00003"))
        universe,restocks=reconstruct_approved_catalog(
            archive,ET.tostring(root),products,retail)
        self.assertEqual(restocks,[])
        self.assertEqual(len(ET.fromstring(universe).findall("Ad")),169)

    def test_mass_removals_are_blocked(self):
        old,products,retail=fixture(count=170,absent=15)
        with self.assertRaisesRegex(ValueError,"Unusual stock removals"):
            plan(old,products,retail,require_second=False)

    def test_no_second_stock_blocks(self):
        old,products,retail=fixture(count=170,absent=4)
        with self.assertRaisesRegex(ValueError,"Second independently"):
            plan(old,products,retail)

    def test_duplicate_id_blocks(self):
        old,products,retail=fixture(count=170,absent=0)
        root=ET.fromstring(old)
        root.findall("Ad")[1].find("Id").text=root.findall("Ad")[0].findtext("Id")
        with self.assertRaisesRegex(ValueError,"duplicate"):
            plan(ET.tostring(root),products,retail)

    def test_bad_title_blocks(self):
        old,products,retail=fixture(count=170,absent=0)
        root=ET.fromstring(old)
        root.findall("Ad")[0].find("Title").text="Недопустимый артикул"
        with self.assertRaisesRegex(ValueError,"Unrecognized"):
            plan(ET.tostring(root),products,retail)

if __name__=="__main__":
    unittest.main()
