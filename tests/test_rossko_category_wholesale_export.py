import unittest
from decimal import Decimal
import requests
import rossko_category_wholesale_export as m

class CategoryWholesaleTest(unittest.TestCase):
    def test_exact_category(self):
        self.assertEqual(m.category("Диск тормозной вентилируемый"),"Тормозные диски")
        self.assertEqual(m.category("Тормозной диск"),"Тормозные диски")
        self.assertEqual(m.category("Рейка рулевая Toyota"),"Рулевые рейки")
        self.assertEqual(m.category("Рулевая рейка Toyota"),"Рулевые рейки")
        self.assertIsNone(m.category("Диск сцепления"))
        self.assertIsNone(m.category("Тяга рулевая"))
        self.assertIsNone(m.category("Ремкомплект рейки рулевой"))
        self.assertIsNone(m.category("Колодки тормозные"))

    def test_only_irkutsk_zero_day_and_exact_article(self):
        original=m.rpc
        def rpc(client,method,params):
            return {"SearchResult":{"success":True,"PartsList":{"Part":[
                {"brand":"NGN","partnumber":"361366","stocks":{"stock":[
                    {"description":"Москва, склад","price":"100","count":2,
                     "delivery":0,"extra":0,"type":0},
                    {"id":"HST159","description":"Иркутск, центральный склад",
                     "price":"4479","count":2,"delivery":0,"extra":0,"type":0}]}},
                {"brand":"ANOTHER","partnumber":"361366","stocks":{"stock":[
                    {"description":"Иркутск, склад","price":"10","count":4,
                     "delivery":0,"extra":0,"type":0}]}}
            ]}}}
        m.rpc=rpc
        try:
            p={"category":"Тормозные диски","brand":"NGN","article":"361366",
              "description":"Диск тормозной",
              "supplier_list_price_rub":"6046.65","supplier_stock":2,
              "supplier_delivery_days":0}
            result=m.audit_one(object(),{"KEY1":"a","KEY2":"b"},
                               {"delivery_id":"1"},p,sleeper=lambda _:None)
        finally:
            m.rpc=original
        self.assertEqual(result["status"],"опт_Иркутск_подтвержден")
        self.assertEqual(result["api_irkutsk_stock_price_rub"],"4479")
        self.assertTrue(result["drom_preview_rub"]>0)
        self.assertTrue(result["avito_preview_rub"]>0)

    def test_no_city_no_usable_price(self):
        original=m.rpc
        def fake(client,method,params):
            return {"SearchResult":{"PartsList":{"Part":[{
                "brand":"NGN","partnumber":"361366","stocks":{"stock":[{
                    "description":"Москва","price":"100","delivery":0,
                    "count":1,"type":0,"extra":0}]}}]}}}
        m.rpc=fake
        try:
            p={"category":"Тормозные диски","brand":"NGN","article":"361366",
               "description":"Диск тормозной",
               "supplier_list_price_rub":"500","supplier_stock":2,
               "supplier_delivery_days":0}
            r=m.audit_one(object(),{},{"delivery_id":"1"},p,sleeper=lambda _:None)
        finally:
            m.rpc=original
        self.assertEqual(r["status"],"склад_Иркутск_не_подтвержден")
        self.assertEqual(r["drom_preview_rub"],"")

if __name__=="__main__":
    unittest.main()
