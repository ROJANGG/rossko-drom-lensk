import unittest

from avito_feed import stable_id
from avito_feed_transition import analyze_transition, expected_pilot_ids
from avito_xml_v3_diagnostic import build_xml, TEST_SKUS


def row(group, brand, article, price=9000):
    return {
        "Группа": group,
        "Бренд": brand, "Артикул": article,
        "Цена ₽": price, "Остаток": 2,
        "Фото URL": "https://imgs.rossko.ru/12/34/NSII0000000000/7.jpg",
        "Применимость РОССКО": "Проверка совместимости по VIN",
    }


def rows():
    return [
        row(group, brand, article)
        for group, items in TEST_SKUS.items()
        for brand, article in items
    ]


class TransitionTests(unittest.TestCase):
    def test_six_stable_ids(self):
        self.assertEqual(len(expected_pilot_ids()), 6)
        self.assertEqual({stable_id(x["Группа"], x["Бренд"], x["Артикул"]) for x in rows()},expected_pilot_ids())

    def test_initial_requires_explicit_switch(self):
        data = build_xml(rows())
        with self.assertRaisesRegex(ValueError, "explicitly"):
            analyze_transition(None, data)
        self.assertEqual(analyze_transition(None, data, allow_initial_pilot=True)["added"],6)

    def test_one_disappears_and_reappears(self):
        r=rows()
        full=build_xml(r)
        no_last=build_xml(r[:-1])
        result=analyze_transition(full,no_last)
        self.assertEqual(result["removed"],1)
        back=analyze_transition(no_last,full)
        self.assertEqual(back["added"],1)
        self.assertEqual(back["removed"],0)

    def test_more_than_one_removed_fails(self):
        r=rows()
        with self.assertRaisesRegex(ValueError,"Unexpected removal"):
            analyze_transition(build_xml(r),build_xml(r[:2]))

    def test_zero_stock_feed_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"empty feed"):
            analyze_transition(build_xml(rows()),b'<Ads formatVersion="3" target="Avito.ru" />')

    def test_price_updates_keep_same_ids(self):
        r=rows()
        original=build_xml(r)
        r[0]["Цена ₽"]=9050
        updated=build_xml(r)
        self.assertEqual(analyze_transition(original,updated)["repriced"],1)

    def test_extreme_price_change_is_blocked(self):
        r=rows()
        original=build_xml(r)
        r[0]["Цена ₽"]=16000
        with self.assertRaisesRegex(ValueError,"Price moved"):
            analyze_transition(original,build_xml(r))


if __name__ == "__main__":
    unittest.main()
