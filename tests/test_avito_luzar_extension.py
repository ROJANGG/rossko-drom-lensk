import unittest
from decimal import Decimal
from xml.etree import ElementTree as ET
from openpyxl import Workbook
from avito_active_feed_refresh import supplier_products,seller_sku,key,plan

class LuzarAvitoExtensionTest(unittest.TestCase):
    def stock_fixture(self):
        w=Workbook()
        ws=w.active
        ws.append(["Бренд","Артикул","Описание","Цена, руб.","Наличие","Срок поставки, дн."])
        ws.append(["Luzar","LRAC3034","Радиатор кондиционера Jetour Dashing",10870.12,2,0])
        ws.append(["Luzar","LRAC3049","Радиатор кондиционера Changan UNI-T",9231.50,3,0])
        ws.append(["Luzar","LRAC9999","Радиатор кондиционера без OEM",9000,3,0])
        ws.append(["Luzar","LRAC3030","Радиатор кондиционера другого SKU",9000,0,0])
        return w

    def test_only_allowlisted_extra_category_skus(self):
        ws=self.stock_fixture()
        stock=supplier_products(ws,{"avito":{"pickup_address":"г. Иркутск, ул. Каховского"}})
        self.assertEqual(set(stock),{key("Luzar","LRAC3034"),key("Luzar","LRAC3049")})
        self.assertEqual(stock[key("Luzar","LRAC3034")]["Группа"],"Радиаторы кондиционера")

    def test_exact_title_brand_article(self):
        ad=ET.fromstring("<Ad><Id>irk-extra-test</Id><Brand>Luzar</Brand><Title>Радиатор кондиционера Luzar LRAC3034 новый</Title></Ad>")
        self.assertEqual(seller_sku(ad),(key("Luzar","LRAC3034"),"Радиаторы кондиционера"))
        ad.find("Brand").text="STELLOX"
        with self.assertRaisesRegex(ValueError,"Unrecognized"):
            seller_sku(ad)

    def test_never_update_non_price_fields(self):
        root=ET.Element("Ads",{"formatVersion":"3","target":"Avito.ru"})
        for i in range(151):
            ad=ET.SubElement(root,"Ad")
            ET.SubElement(ad,"Id").text=str(i)
            ET.SubElement(ad,"Title").text=("Радиатор кондиционера Luzar LRAC3034 новый"
                                            if i==0 else "Тормозной диск NGN "+str(i)+" новый")
            ET.SubElement(ad,"Brand").text="Luzar" if i==0 else "NGN"
            ET.SubElement(ad,"Price").text="11000"
            ET.SubElement(ad,"OEM").text="F20-8105010" if i==0 else "999"
        sample=ET.tostring(root)
        k=key("Luzar","LRAC3034")
        products={k:{"Группа":"Радиаторы кондиционера","Остаток РОССКО":2,
                     "Срок поставки":0,"_source_list_price":"9000"}}
        for i in range(1,151):
            products[key("NGN",str(i))]={"Группа":"Тормозные диски",
                "Остаток РОССКО":1,"Срок поставки":0,
                "_source_list_price":"7000"}
        retail={k:{"supplier_price":Decimal("9000"),"avito_price":10000,"days":0}}
        for i in range(1,151):
            retail[key("NGN",str(i))]={"supplier_price":Decimal("7000"),
                                      "avito_price":11000,"days":0}
        out,report=plan(sample,products,retail)
        new=ET.fromstring(out)
        self.assertEqual(report["repriced"],1)
        self.assertEqual(new.findall("Ad")[0].findtext("OEM"),"F20-8105010")
        self.assertEqual(new.findall("Ad")[0].findtext("Price"),"10000")

if __name__=="__main__":
    unittest.main()
