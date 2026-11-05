import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_wholesale_live_api_refresh import (
    list_approved, compare_and_build, render_results,
)
from avito_active_feed_refresh import key

class WholesaleAvitoOnlyTests(unittest.TestCase):
    @staticmethod
    def sample(n=170):
        root=ET.Element("Ads",{"formatVersion":"3"})
        stock={}
        old={}
        for i in range(n):
            article=f"T{i:04d}"
            row=ET.SubElement(root,"Ad")
            ET.SubElement(row,"Id").text=f"irk-{i:04d}"
            ET.SubElement(row,"Title").text=f"Тормозной диск NGN {article} новый"
            ET.SubElement(row,"Brand").text="NGN"
            k=key("NGN",article)
            stock[k]={
                "Бренд":"NGN", "Артикул":article,"Группа":"Тормозные диски",
                "Остаток РОССКО":3,"Срок поставки":0,
                "_source_list_price":"2000"
            }
            old[k]={"brand":"NGN","article":article,
                    "supplier_price":Decimal("2000"),"days":0,
                    "drom":9999,"avito_price":2750}
        return ET.tostring(root),stock,old

    def test_calls_only_approved_skus_and_preserves_drom_price(self):
        xml,stock,old=self.sample()
        approved=list_approved(xml)
        self.assertEqual(len(approved),170)
        calls=[]
        def search(brand,article,group,cost,quantity):
            calls.append((brand,article,group))
            return {"status":"опт_Иркутск_подтвержден",
                    "api_irkutsk_same_delivery_price_rub":"1700",
                    "api_irkutsk_stock_ids":"IRK1",
                    "supplier_list_price_rub":"2000"}
        updated,fresh,report=compare_and_build(
            approved,stock,old,search,sleeper=lambda _:None)
        self.assertEqual(len(calls),170)
        self.assertEqual(len(fresh),170)
        self.assertEqual(report["api_wholesale_confirmed"],170)
        self.assertEqual(len(updated),170)
        self.assertEqual(next(iter(updated.values()))["drom"],9999)
        self.assertNotEqual(next(iter(updated.values()))["avito_price"],2750)
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)
            render_results(dest,updated,fresh,report)
            with (dest/"runtime_verified_retail_only.csv").open(
                    encoding="utf-8-sig",newline="") as fp:
                rows=list(csv.DictReader(fp,delimiter=";"))
            self.assertEqual(len(rows),170)
            self.assertEqual(rows[0]["drom_retail"],"9999")
            self.assertNotIn("personal_cost",rows[0])

    def test_low_api_success_rate_refuses_output(self):
        xml,stock,old=self.sample()
        approved=list_approved(xml)
        counter=[0]
        def search(brand,article,group,cost,quantity):
            counter[0]+=1
            return {"status":"опт_Иркутск_подтвержден" if counter[0]<=40 else "сбой_API_Timeout",
                    "api_irkutsk_same_delivery_price_rub":"1700",
                    "api_irkutsk_stock_ids":"IRK1",
                    "supplier_list_price_rub":"2000"}
        with self.assertRaisesRegex(RuntimeError,"success rate insufficient"):
            compare_and_build(approved,stock,old,search,sleeper=lambda _:None)

    def test_source_price_mismatch_does_not_validate(self):
        xml,stock,old=self.sample()
        approved=list_approved(xml)
        def search(brand,article,group,cost,quantity):
            return {"status":"опт_Иркутск_подтвержден",
                    "api_irkutsk_same_delivery_price_rub":"1700",
                    "api_irkutsk_stock_ids":"IRK1",
                    "supplier_list_price_rub":"1000"}
        with self.assertRaisesRegex(RuntimeError,"success rate insufficient"):
            compare_and_build(approved,stock,old,search,sleeper=lambda _:None)

    def test_no_nonapproved_api_calls(self):
        xml,stock,old=self.sample()
        approved=list_approved(xml)
        stock[key("NGN","UNAPPROVED")]={
            "Бренд":"NGN","Артикул":"UNAPPROVED","Группа":"Тормозные диски",
            "Остаток РОССКО":2,"Срок поставки":0,"_source_list_price":"2000"}
        calls=[]
        def search(brand,article,group,cost,quantity):
            calls.append(article)
            return {"status":"опт_Иркутск_подтвержден",
                    "api_irkutsk_same_delivery_price_rub":"1700",
                    "api_irkutsk_stock_ids":"IRK1",
                    "supplier_list_price_rub":"2000"}
        compare_and_build(approved,stock,old,search,sleeper=lambda _:None)
        self.assertNotIn("UNAPPROVED",calls)

if __name__=="__main__":
    unittest.main()
