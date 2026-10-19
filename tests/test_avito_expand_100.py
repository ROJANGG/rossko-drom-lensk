"""No-network tests for the next 100 Avito review candidates."""
import unittest

from PIL import Image

from avito_feed import stable_id
from avito_expand_100 import GROUPS, TOTAL, new_candidates, prepare_selection, review_records


def candidate(group, brand, article, url=None):
    return {
        "Группа": group,
        "Бренд": brand,
        "Артикул": article,
        "Цена Авито": 7500,
        "Остаток РОССКО": 3,
        "Фото для проверки": url or f"https://imgs.rossko.ru/AB/CD/{article}/1.jpg",
        "Применимость": "MANY MODELS FROM SUPPLIER UNVERIFIED",
    }


class ExpansionTests(unittest.TestCase):
    def test_skip_every_original_sku_even_if_temporarily_unavailable(self):
        a, b = GROUPS
        old = candidate(a, "Master KiT", "77R036")
        duplicated_image = candidate(b, "CTR", "NEW1", old["Фото для проверки"])
        fresh = candidate(b, "CTR", "NEW2")
        excluded = {"masterkit|77r036"}
        photos = {"masterkit|77r036": old["Фото для проверки"],
                  "ctr|new1": duplicated_image["Фото для проверки"],
                  "ctr|new2": fresh["Фото для проверки"]}
        found = new_candidates([old, duplicated_image, fresh], photos, excluded)
        self.assertEqual(found[a], [])
        self.assertEqual([r["Артикул"] for r in found[b]], ["NEW2"])

    def test_remanufactured_motorherz_excluded_from_new_ads(self):
        group = GROUPS[0]
        restored = candidate(group, "Motorherz", "J50031RB")
        new_part = candidate(group, "Motorherz", "J50031NW")
        urls = {
            "motorherz|j50031rb": restored["Фото для проверки"],
            "motorherz|j50031nw": new_part["Фото для проверки"],
        }
        found = new_candidates([restored, new_part], urls, set())
        self.assertEqual([r["Артикул"] for r in found[group]], ["J50031NW"])

    def test_balanced_selection_and_fill_if_shortage(self):
        a, b = GROUPS
        groups = {
            a: [candidate(a, "Krauf", str(n)) for n in range(65)],
            b: [candidate(b, "CTR", str(n + 1000)) for n in range(35)],
        }
        def validate(rows, cap, selected_keys, hashes):
            result = []
            for row in rows:
                key = (row["Бренд"].casefold(), row["Артикул"])
                if key in selected_keys:
                    continue
                selected_keys.add(key)
                hashes.add(row["Артикул"])
                result.append((row, Image.new("RGB", (200, 200)), "200", "200"))
                if len(result) == cap:
                    break
            return result
        result = prepare_selection(groups, validate)
        self.assertEqual({g: len(result[g]) for g in GROUPS}, {a: 65, b: 35})
        self.assertEqual(sum(len(v) for v in result.values()), TOTAL)

    def test_review_has_new_stable_ids_and_never_invents_oem(self):
        a, b = GROUPS
        img = Image.new("RGB", (220, 220))
        item = candidate(a, "Krauf", "NEW123")
        records = review_records({a: [(item, img, "220", "220")], b: []},
                                 {"ctr|gd0156"})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["ID Авито"], stable_id(a, "Krauf", "NEW123"))
        self.assertEqual(records[0]["Номер детали OEM"], "")
        self.assertEqual(records[0]["Источник подтверждения OEM"], "")
        self.assertIn("НЕ ПУБЛИКОВАТЬ", records[0]["Статус"])

    def test_old_and_duplicate_skus_rejected(self):
        group = GROUPS[0]
        img = Image.new("RGB", (220, 220))
        item = candidate(group, "Krauf", "NEW123")
        with self.assertRaisesRegex(ValueError, "previously published"):
            review_records({group: [(item, img, "220", "220")]},
                           {"krauf|new123"})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            review_records({group: [(item, img, "220", "220"),
                                    (item, img, "220", "220")]}, set())


if __name__ == "__main__":
    unittest.main()
