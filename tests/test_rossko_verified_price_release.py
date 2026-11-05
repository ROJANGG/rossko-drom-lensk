import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from openpyxl import Workbook,load_workbook

from rossko_verified_price_release_plan import make_map,extract_title_key,patch_avito
from rossko_verified_retail_override import apply_drom, apply_avito, drom_baseline

class VerifiedPriceReleaseTests(unittest.TestCase):
    def test_source_price_or_stock_mismatch_never_approves(self):
        k=("ngn","361366")
        base={"brand":"NGN","article":"361366","wholesale":Decimal("4479"),
              "supplier_price":Decimal("6046.65"),"days":0,"category":"Тормозные диски"}
        fresh={k:{"cost":Decimal("6046.66"),"stock":3,"days":0}}
        a,r=make_map({k:base},fresh)
        self.assertEqual(a,{})
        self.assertEqual(r["supplier_list_cost_changed"],1)
        fresh[k]["cost"]=Decimal("6046.65")
        fresh[k]["stock"]=0
        a,r=make_map({k:base},fresh)
        self.assertFalse(a)
        self.assertEqual(r["no_fresh_stock"],1)

    def test_title_brand_article_only(self):
        ad=ET.fromstring("<Ad><Title>Тормозной диск NGN 361366 новый</Title><Brand>NGN</Brand></Ad>")
        self.assertEqual(extract_title_key(ad),("ngn","361366"))
        ad.find("Brand").text="Other"
        self.assertIsNone(extract_title_key(ad))

    def test_xml_does_not_change_ids(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"avito.xml"
            root=ET.Element("Ads")
            for i in range(100):
                ad=ET.SubElement(root,"Ad")
                ET.SubElement(ad,"Id").text=str(i)
                ET.SubElement(ad,"Title").text="Тормозной диск NGN 361366 новый" if i==3 else "Диск иной"
                ET.SubElement(ad,"Brand").text="NGN"
                ET.SubElement(ad,"Availability").text="В наличии"
                ET.SubElement(ad,"Price").text="7750" if i==3 else "5000"
            ET.ElementTree(root).write(f,encoding="utf-8",xml_declaration=True)
            prices={("ngn","361366"):{"source":Decimal("6046.65"),
                "drom":6150,"avito":5850,"days":0}}
            changes=apply_avito(f,prices)
            self.assertEqual(len(changes),1)
            check=ET.parse(f).getroot()
            self.assertEqual(len(check.findall("Ad")),100)
            self.assertEqual(check.findall("Ad")[3].findtext("Price"),"5850")

if __name__=="__main__":
    unittest.main()
