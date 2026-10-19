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
    "Рулевые рейки": [("Krauf", "HNQ2139GQ"), ("Master KiT", "77R036"),
                      ("Krauf", "HNQ5020GQ"), ("Krauf", "HNQ5047GQ"),
                      ("Krauf", "HNQ2424GQ"), ("Krauf", "HNQ5090GQ"),
                      ("Krauf", "HNQ9012GQ"), ("Krauf", "HNQ9048GQ"),
                      ("Krauf", "HNQ9065GQ"), ("Krauf", "HNQ2025GQ"),
                      ("Krauf", "HNQ5056GQ"), ("Krauf", "HNQ5119GQ"),
                      ("Master KiT", "77R010"), ("Master KiT", "77R046"),
                      ("Master KiT", "77R047"), ("Master KiT", "77R070"),
                      ("Krauf", "HNQ2434GQ"), ("Krauf", "HNQ2470GQ"),
                      ("Krauf", "HNQ2724GQ"), ("Krauf", "HNQ5054GQ"),
                      ("Krauf", "HNQ5082GQ"), ("Krauf", "HNQ9011GQ"),
                      ("Master KiT", "77R015"), ("Master KiT", "77R025"),
                      ("Master KiT", "77R040")],
    "Тормозные диски": [("CTR", "GD0156"), ("Marshall", "M2000404"),
                        ("CTR", "GD0063"), ("Marshall", "M2000408"),
                        ("CTR", "GD0004"), ("CTR", "GD0008"),
                        ("CTR", "GD0009"), ("CTR", "GD0026"),
                        ("Fenox", "TB219353"), ("Marshall", "M2000429"),
                        ("Marshall", "M2000745"), ("CTR", "GD0021"),
                        ("CTR", "GD0024"), ("CTR", "GD0019"),
                        ("CTR", "GD0162"), ("Brave", "BRBD198"),
                        ("Allied Nippon", "ADC0832V"),
                        ("CTR", "GD0166"), ("CTR", "GD0010"),
                        ("CTR", "GD0015"), ("CTR", "GD0016"),
                        ("Allied Nippon", "ADC0456V"), ("Allied Nippon", "ADC01128V"),
                        ("Allied Nippon", "ADC3722V"), ("NGN", "361427")],
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
    # Product-to-OE evidence: official supplier for CTR, official manufacturer for Marshall.
    ("ctr", "gd0063"): "6R0615301A",
    ("marshall", "m2000408"): "517120Z000",
    # Cross-references documented in input/avito_oem_verified.csv with source URLs.
    ("ctr", "gd0004"): "1K0615601AB",
    ("ctr", "gd0008"): "5Q0615601G",
    ("ctr", "gd0009"): "1K0615301AC",
    ("ctr", "gd0026"): "4615A117",
    ("fenox", "tb219353"): "9064230112",
    ("marshall", "m2000429"): "5Q0615301F",
    ("marshall", "m2000745"): "51712L0000",
    ("krauf", "hnq5020gq"): "48001BG10A",
    ("krauf", "hnq5047gq"): "56500A7500",
    ("ctr", "gd0021"): "1K0615601AA",
    ("ctr", "gd0024"): "04743999AA",
    ("ctr", "gd0019"): "7H0615601B",
    # Further documented OEM matches (source URLs in avito_oem_verified.csv).
    ("krauf", "hnq2424gq"): "LR007501",
    ("krauf", "hnq5090gq"): "4550005030",
    ("krauf", "hnq9012gq"): "4551052041",
    ("krauf", "hnq9048gq"): "490018H305",
    ("krauf", "hnq9065gq"): "53601S10013",
    ("krauf", "hnq2025gq"): "4420060012",
    ("krauf", "hnq5056gq"): "4551006061",
    ("krauf", "hnq5119gq"): "4551078022",
    ("masterkit", "77r010"): "BV613A500AH",
    ("masterkit", "77r046"): "4551042030",
    ("masterkit", "77r047"): "4420033320",
    ("masterkit", "77r070"): "565002L301",
    ("krauf", "hnq2434gq"): "49001ES60A",
    ("krauf", "hnq2470gq"): "8D1422052",
    ("krauf", "hnq2724gq"): "577004H100",
    ("krauf", "hnq5054gq"): "565000X500",
    ("krauf", "hnq5082gq"): "480014EH0A",
    ("krauf", "hnq9011gq"): "D65132110A",
    ("masterkit", "77r015"): "577000Z801",
    ("masterkit", "77r025"): "4410A723",
    ("masterkit", "77r040"): "490013367R",
    ("ctr", "gd0162"): "40206JD00B",
    ("brave", "brbd198"): "3502102XGW02A",
    ("alliednippon", "adc0832v"): "45251S1AG60",
    # Verified specific-brand cross references for the final eight products.
    ("ctr", "gd0166"): "402066478R",
    ("ctr", "gd0010"): "1K0615301T",
    ("ctr", "gd0015"): "8K0615601B",
    ("ctr", "gd0016"): "G25Y26251A",
    ("alliednippon", "adc0456v"): "BP4Y3325XC",
    ("alliednippon", "adc01128v"): "4351260151",
    ("alliednippon", "adc3722v"): "3502108XPW01A",
    ("ngn", "361427"): "5Q0615601F",
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

# ROSSKO uses "Master KiT", while Avito's Brand dictionary expects
# the continuous commercial spelling "MasterKit" (check via XML validator).
# Never change stable_id / article / OEM when normalizing the display brand.
BRAND_AVITO_ALIASES = {
    "masterkit": "MasterKit",
}


def avito_brand_name(value: str) -> str:
    return BRAND_AVITO_ALIASES.get(normalize_key(value), value)


def build_xml(rows, *, verified_extra_oems: dict[str, str] | None = None):
    # Never override sourced OEM data for the original pilot; extras are
    # explicitly approved by identity and source in the separate staging step.
    extra = verified_extra_oems or {}
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
        key = normalize_key(brand) + "|" + normalize_key(article)
        if key in extra:
            if (normalize_key(brand), normalize_key(article)) in VERIFIED_OEM_BY_SKU:
                raise ValueError("Cannot override pilot OEM: " + key)
            oem = extra[key]
            if not oem or not oem.isalnum() or len(oem) > 32:
                raise ValueError("Invalid extra OEM: " + key)
        else:
            oem = verified_oem(brand, article)
        field("OEM", oem)
        field("Title", f"{label} {brand} {article} новый")
        # Supplier fitment is not independently verified for public ad text.
        # Do not insert bulk vehicle keywords into Avito descriptions.
        desc = (f"{label}, производитель {brand}, артикул {article}.\n"
                "Состояние: новое.\n"
                "Доступно к самовывозу в Иркутске.\n"
                + f"Самовывоз: {ADDRESS}.\n"
                + "Наличие перед приездом уточняйте, совместимость проверяйте по VIN.")
        field("Description", desc)
        field("Address", ADDRESS)
        field("Price", price)
        field("Condition", "Новое")
        field("Availability", "В наличии")
        field("Brand", avito_brand_name(brand))
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
        fname = f"AVITO_XML_TEST_{len(items)}_BRAKES.xml" if group == "Тормозные диски" else f"AVITO_XML_TEST_{len(items)}_STEERING.xml"
        content = build_xml(items)
        target = output / fname
        target.write_bytes(content)
        doc = ET.parse(target)
        assert len(doc.findall("./Ad")) == len(items)
        print(f"XML_DIAGNOSTIC {fname}: 2 ads, real stable IDs, no publication")
    together = output / f"AVITO_XML_TEST_{len(four)}_COMBINED.xml"
    together.write_bytes(build_xml(four))
    assert len(ET.parse(together).findall("./Ad")) == len(four)
    print(f"XML_DIAGNOSTIC {len(four)} ads; category field validity requires Avito validator report.")


if __name__ == "__main__":
    main()
