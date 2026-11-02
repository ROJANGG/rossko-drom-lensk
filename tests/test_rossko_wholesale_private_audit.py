import unittest
import requests
from decimal import Decimal

from rossko_wholesale_private_audit import (
    calculate_offer, retry_transient, get_prices, is_irkutsk_warehouse,
    choose_delivery, norm,
)

class WholesaleAuditTest(unittest.TestCase):
    def test_only_explicit_irkutsk_warehouse_is_eligible(self):
        data=[
            {"id":"MOW1","description":"Москва, улица 1","delivery":0,
             "count":2,"price":"100.00","type":0,"extra":0},
            {"id":"IRK1","description":"Иркутск, ул. Каховского","delivery":0,
             "count":3,"price":"150.00","type":0,"extra":0},
            {"id":"IRK2","description":"Иркутск, другой склад","delivery":0,
             "count":3,"price":"70.00","type":0,"extra":1},
            {"id":"IRK3","description":"Иркутск, списание","delivery":0,
             "count":3,"price":"60.00","type":2,"extra":0},
            {"id":"IRK4","description":"Иркутск, позже","delivery":2,
             "count":3,"price":"90.00","type":0,"extra":0},
        ]
        r=calculate_offer(data,0,Decimal("175"))
        self.assertEqual(r["min_all"],Decimal("90"))
        self.assertEqual(r["same"],Decimal("150"))
        self.assertEqual(r["min_irkutsk_zero"],Decimal("150"))
        self.assertEqual(r["stock_ids"],["IRK1","IRK4"])

    def test_no_locality_means_no_qualified_price(self):
        r=calculate_offer([{"description":"Неизвестный склад", "delivery":0,
                            "price":"100","count":2,"type":0,"extra":0}],0,Decimal("200"))
        self.assertIsNone(r["same"])
        self.assertFalse(r["city_verified"])

    def test_warehouse_detection(self):
        self.assertTrue(is_irkutsk_warehouse("г. ИРКУТСК, Каховского"))
        self.assertFalse(is_irkutsk_warehouse("Иркутский район"))
        self.assertFalse(is_irkutsk_warehouse(None))

    def test_retry_recovers_from_connection_failure(self):
        count=[0]
        sleeps=[]
        def work():
            count[0]+=1
            if count[0]<3:
                raise requests.exceptions.ConnectionError("temporary")
            return 9
        self.assertEqual(retry_transient(work,sleep=sleeps.append),9)
        self.assertEqual(count[0],3)
        self.assertEqual(sleeps,[1.0,2.0])

    def test_retry_does_not_retry_permanent_failure(self):
        attempts=[0]
        def work():
            attempts[0]+=1
            raise ValueError("permanent")
        with self.assertRaises(ValueError):
            retry_transient(work,sleep=lambda _:None)
        self.assertEqual(attempts[0],1)

    def test_account_pickup_selection(self):
        details={"CheckoutDetailsResult":{
            "DeliveryType":{"delivery":[{"id":"000000001","name":"Самовывоз со склада"},
                                        {"id":"000000002","name":"Курьер"}]},
            "DeliveryAddress":{"address":[{"city":"Иркутск","id":"1"}]}
        }}
        d,m=choose_delivery(details)
        self.assertEqual(m,"account_pickup")
        self.assertEqual(d["delivery_id"],"000000001")

    def test_no_analog_laundering_and_transient_recovery(self):
        import rossko_wholesale_private_audit as mod
        prior=mod.rpc
        calls=[0]
        def fake_rpc(client,name,params):
            calls[0]+=1
            if calls[0]==1:
                raise requests.exceptions.Timeout("temporary")
            return {"SearchResult":{"success":True,"PartsList":{"Part":[
                {"brand":"NGN","partnumber":"361366","stocks":{"stock":[
                    {"id":"IRK","description":"Иркутск, склад","price":"500.5",
                     "count":1,"delivery":0,"type":0,"extra":0}]}},
                {"brand":"Other","partnumber":"361366","stocks":{"stock":[
                    {"id":"OTH","description":"Иркутск, склад","price":"5",
                     "count":1,"delivery":0,"type":0,"extra":0}]}}
            ]}}}
        mod.rpc=fake_rpc
        try:
            rows=get_prices(object(),{"KEY1":"dummy","KEY2":"dummy"},
                {"delivery_id":"000000001"},[{
                  "category":"brake_discs","brand":"NGN","article":"361366",
                  "supplier_list_price_rub":"1000","supplier_stock":2,
                  "supplier_delivery_days":0}],sleeper=lambda _:None)
        finally:
            mod.rpc=prior
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["status"],"confirmed_irkutsk_matching_delivery")
        self.assertEqual(rows[0]["api_matching_delivery_lowest_rub"],"500.5")
        self.assertTrue(rows[0]["api_price_is_lower_than_supplier_list"])
        self.assertEqual(calls[0],2)

if __name__=="__main__":
    unittest.main()
