"""Generate SMALL, review-only Avito XML v3 diagnostics from a fresh 50-SKU preflight.

Do not publish or schedule the resulting file until Avito validates category tags
and item details. Input CSV is a temporary GitHub Actions artifact (never commit it).
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from update_prices import normalize_key

ADDRESS = "г. Иркутск, ул. Каховского, д. 11/1"
TEST_SKUS = {
    "Рулевые рейки": [("Krauf", "HNQ2139GQ"), ("Master KiT", "77R036")],
    "Тормозные диски": [("CTR", "GD0156"), ("Marshall", "M2000404")],
}
META = {
    "Рулевые рейки": ("Рулевая рейка", "Рулевое управление"),
    "Тормозные диски": ("Тормозной диск", "Тормозная система"),
}

# Confirmed genuine OE cross-references, NOT third-party brand articles.
# Evidence from ROSSKO product pages for discs, from Motorherz / Avto.pro for racks:
# https://rossko.ru/card/ctr-gd0156-nsii0026903735/
# https://rossko.ru/card/marshall-m2000404-nsii0021333792/
# https://www.motorherz.ru/product.php?id=19337
# https://avto.pro/part-77R036-MASTERKIT-422/
# Avito's checker requests Latin letters and digits; remove hyphens in OEM values.
VERIFIED_OEM_BY_SKU = {
    ("ctr", "gd0156"): "584110U300",
    ("marshall", "m2000404"): "517120U000",
    ("krauf", "hnq2139gq"): "4001L1",
    ("masterkit", "77r036"): "48001JD900",
}


def verified_oem(brand: str, article: str) -> str:
    key = (normalize_key(brand), normalize_key(article))
    value = VERIFIED_OEM_BY_SKU.get(key)
    if not value:
        raise ValueError(
            f"No sourced OEM cross-reference for {brand} {article}; "
            "do not substitute supplier article number"
        )
    return value


def build_xml(rows):
    root = ET.Element("Ads", {"formatVersion": "3", "target": "Avito.ru"})
    ids = set()
    for row in rows:
        group = row["Группа"]
        label, part_type = META[group]
        brand = row["Бренд"]
        article = row["Артикул"]
        ident = stable_id(group, brand, article)
        if ident in ids:
            raise ValueError("Duplicate stable ID: " + ident)
        ids.add(ident)
        price = int(row["Цена ₽"])
        stock = int(row["Остаток"])
        photo = row["Фото URL"].strip()
        if price <= 0 or stock <= 0 or not photo.startswith("https://imgs.rossko.ru/"):
            raise ValueError(f"Invalid local stock, price or image: {brand} {article}")
        ad = ET.SubElement(root, "Ad")

        def field(name, value):
            ET.SubElement(ad, name).text = str(value)

        field("Id", ident)
        field("Category", "Запчасти и аксессуары")
        field("GoodsType", "Запчасти")
        field("AdType", "Товар приобретен на продажу")
        field("ProductType", "Для автомобилей")
        field("SparePartType", part_type)
        field("OEM", verified_oem(brand, article))
        field("Title", f"{label} {brand} {article} новый")
        fit = row.get("Применимость РОССКО", "").strip()
        desc = (f"{label}, производитель {brand}, артикул {article}.\n"
                "Состояние: новое.\n"
                + (f"Применимость по данным РОССКО: {fit}.\n" if fit else "")
                + "Наличие в Иркутске по последнему прайсу РОССКО.\n"
                + f"Самовывоз: {ADDRESS}.\n"
                + "Наличие перед приездом уточняйте, совместимость проверяйте по VIN.")
        field("Description", desc)
        field("Address", ADDRESS)
        field("Price", price)
        field("Condition", "Новое")
        field("Availability", "В наличии")
        field("Brand", brand)
        ET.SubElement(ET.SubElement(ad, "Images"), "Image", {"url": photo})

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="output/avito_irkutsk_preflight/checklist_50.csv")
    ap.add_argument("--out", default="output/avito_xml_test_only")
    args = ap.parse_args()
    with open(args.source, newline="", encoding="utf-8-sig") as fp:
        all_rows = list(csv.DictReader(fp, delimiter=";"))
    by_key = {
        (r["Группа"], normalize_key(r["Бренд"]), normalize_key(r["Артикул"])): r
        for r in all_rows
    }
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    four = []
    for group, expected in TEST_SKUS.items():
        items = []
        for brand, article in expected:
            k = (group, normalize_key(brand), normalize_key(article))
            if k not in by_key:
                raise ValueError("No fresh Irkutsk stock for test article: " + repr(k))
            items.append(by_key[k])
        four.extend(items)
        fname = "AVITO_XML_TEST_2_BRAKES.xml" if group == "Тормозные диски" else "AVITO_XML_TEST_2_STEERING.xml"
        content = build_xml(items)
        target = output / fname
        target.write_bytes(content)
        doc = ET.parse(target)
        assert len(doc.findall("./Ad")) == 2
        print(f"XML_DIAGNOSTIC {fname}: 2 ads, real stable IDs, no publication")
    together = output / "AVITO_XML_TEST_4_COMBINED.xml"
    together.write_bytes(build_xml(four))
    assert len(ET.parse(together).findall("./Ad")) == 4
    print("XML_DIAGNOSTIC done. Category field validity requires Avito validator report.")


if __name__ == "__main__":
    main()
