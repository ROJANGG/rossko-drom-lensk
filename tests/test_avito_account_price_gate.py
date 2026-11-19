import unittest
from decimal import Decimal
from avito_prepared_belts_release import account_retail
class ExactAccountPriceGate(unittest.TestCase):
 def test_bad_individual_quote_does_not_produce_retail(self):
  base={'supplier_list_price_rub':'1000','api_irkutsk_same_delivery_price_rub':'700'};self.assertIsNotNone(account_retail(base,Decimal('1000')))
  for fields in [{'supplier_list_price_rub':'1001'},{'api_irkutsk_same_delivery_price_rub':'0'},{'api_irkutsk_same_delivery_price_rub':'99'},{'api_irkutsk_same_delivery_price_rub':'2001'},{'api_irkutsk_same_delivery_price_rub':None}]:self.assertIsNone(account_retail(dict(base,**fields),Decimal('1000')))
