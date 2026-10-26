"""Read-only ROSSKO price vs generated Drom Lensk XLSX reconciliation.

Compare normalized manufacturer+article keys. Use XLSX XML ZIP streaming rather
than running the exporter; neither spreadsheet nor live site is modified.
A generated XLSX is NOT a verified inventory of published Drom webpages.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COL = re.compile(r"^[A-Z]+")
EXCLUDE = re.compile(
    r"ремкомплект|ремкомпл|тяга|наконечник|пыльник|колодк|суппорт|"
    r"диск сцепления|втулк|болт|подшипник|щиток", re.I)
RACK = re.compile(r"^(?:рулев\w*\s+рейк\w*|рейк\w*\s+рулев\w*)\b", re.I)
BRAKE = re.compile(r"^(?:тормозн\w*\s+диск\w*|диск\w*\s+тормозн\w*)\b", re.I)


def norm(value):
    return re.sub(r"[^0-9a-zа-я]+", "", str(value or "").strip().casefold())


def readable(value):
    return str(value or "").strip()


def classify(description):
    text = re.sub(r"[-_/(),;]+", " ", readable(description).casefold()).strip()
    if EXCLUDE.search(text):
        return "Прочее"
    if BRAKE.search(text):
        return "Тормозные диски"
    if RACK.search(text):
        return "Рулевые рейки"
    return "Прочее"


def extract_cell(element, strings):
    kind = element.get("t", "")
    if kind == "inlineStr":
        return "".join(element.itertext()).strip()
    v = element.find(MAIN + "v")
    value = v.text if v is not None else ""
    if kind == "s" and value:
        return strings[int(value)]
    return value or ""


def iter_xlsx(path):
    """Stream sheet1 cells, preserving text IDs including leading zeroes."""
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            with archive.open("xl/sharedStrings.xml") as source:
                for _, node in ET.iterparse(source, events=("end",)):
                    if node.tag == MAIN + "si":
                        strings.append("".join(node.itertext()))
                        node.clear()
        sheets = sorted(n for n in archive.namelist()
                        if re.fullmatch(r"xl/worksheets/sheet[0-9]+\.xml", n))
        if not sheets:
            raise ValueError("XLSX missing worksheet: " + str(path))
        with archive.open(sheets[0]) as source:
            for _, node in ET.iterparse(source, events=("end",)):
                if node.tag != MAIN + "row":
                    continue
                row = {}
                for cell in node.findall(MAIN + "c"):
                    ref = cell.get("r", "")
                    m = COL.match(ref)
                    if not m:
                        continue
                    ix = 0
                    for letter in m.group(0):
                        ix = ix * 26 + ord(letter) - 64
                    row[ix - 1] = extract_cell(cell, strings)
                node.clear()
                yield row


def header_records(path, needed):
    stream = iter_xlsx(path)
    header_row = next(stream)
    headers = {readable(value): column for column, value in header_row.items()}
    missing = set(needed) - set(headers)
    if missing:
        raise ValueError(f"{path} missing headers {sorted(missing)}; found {list(headers)}")
    for row in stream:
        yield {name: readable(row.get(col, "")) for name, col in headers.items()}


def stock_count(value):
    raw = readable(value).replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", raw)
    return int(float(m.group(0))) if m else 0


def positive_price(value):
    raw = readable(value).replace(" ", "").replace(",", ".")
    try:
        return float(raw) > 0
    except ValueError:
        return False


def output_csv(path, columns, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns, delimiter=";")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in columns})


def run(price_path: Path, drom_path: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    drom_needed = ("Артикул", "Производитель", "Наименование товара", "Цена", "Кол-во")
    supplier_needed = ("Артикул", "Бренд", "Описание", "Цена, руб.", "Наличие",
                       "Срок поставки, дн.")
    drom = {}
    duplicates_drom = 0
    drom_rows = 0
    for row in header_records(drom_path, drom_needed):
        drom_rows += 1
        key = norm(row["Производитель"]) + "|" + norm(row["Артикул"])
        if key in drom:
            duplicates_drom += 1
        if key != "|" and key not in drom:
            drom[key] = row

    all_skus = {}
    source_rows = 0
    duplicate_supplier = 0
    for row in header_records(price_path, supplier_needed):
        source_rows += 1
        brand, article, desc = row["Бренд"], row["Артикул"], row["Описание"]
        key = norm(brand) + "|" + norm(article)
        if not norm(brand) or not norm(article):
            continue
        present = key in all_skus
        if present:
            duplicate_supplier += 1
        stock = stock_count(row["Наличие"])
        # The exporter skips rows with missing SKU/description/price/stock.
        valid = bool(readable(desc)) and stock > 0 and positive_price(row["Цена, руб."])
        reason = []
        if not desc:
            reason.append("нет описания")
        if stock <= 0:
            reason.append("нет остатка")
        if not positive_price(row["Цена, руб."]):
            reason.append("нет цены")
        if not present:
            all_skus[key] = {"brand":brand, "article":article, "name":desc,
                             "category":classify(desc), "quantity":stock,
                             "supplier_price":row["Цена, руб."],
                             "delivery":row["Срок поставки, дн."],
                             "source_rows":1, "eligible":valid,
                             "reason":", ".join(reason) if reason else ""}
        else:
            entry = all_skus[key]
            entry["source_rows"] += 1
            # If any duplicate entry can be legitimately exported, do NOT flag
            # a missing SKU as no-stock just because the first row was stale.
            if valid and not entry["eligible"]:
                entry.update(brand=brand,article=article,name=desc,
                             category=classify(desc),quantity=stock,
                             supplier_price=row["Цена, руб."],
                             delivery=row["Срок поставки, дн."],
                             eligible=True,reason="")

    rows = []
    missing = []
    missing_eligible = []
    missing_ineligible = []
    overlap = 0
    categorised = Counter()
    reasons = Counter()
    brand_count = Counter()
    for key, entry in all_skus.items():
        cat = entry["category"]
        status = "В выгрузке Дром" if key in drom else (
            "ДОСТУПЕН, НО НЕ В ВЫГРУЗКЕ" if entry["eligible"]
            else "Нет в выгрузке — фильтр поставщика")
        row = {
            "Бренд":entry["brand"], "Артикул":entry["article"],
            "Наименование":entry["name"], "Категория":cat,
            "Остаток РОССКО":entry["quantity"],
            "Цена закупки РОССКО":entry["supplier_price"],
            "Срок поставки, дни":entry["delivery"],
            "В выгрузке Дром":"Да" if key in drom else "Нет",
            "Статус":status,
            "Причина исключения":entry["reason"],
            "Повторяющихся строк в прайсе":entry["source_rows"]-1,
        }
        rows.append(row)
        if key in drom:
            overlap+=1
        else:
            missing.append(row)
            categorised[cat] += 1
            brand_count[entry["brand"]] += 1
            if entry["eligible"]:
                missing_eligible.append(row)
            else:
                missing_ineligible.append(row)
                reasons[entry["reason"]] += 1
    extra_drom = [r for key, r in drom.items() if key not in all_skus]
    columns = list(rows[0]) if rows else []
    missing.sort(key=lambda r:(r["Категория"],r["Бренд"],r["Артикул"]))
    missing_eligible.sort(key=lambda r:(r["Категория"],r["Бренд"],r["Артикул"]))
    missing_ineligible.sort(key=lambda r:(r["Категория"],r["Бренд"],r["Артикул"]))
    output_csv(out/"not_in_drom_all.csv", columns, missing)
    output_csv(out/"missing_but_available.csv", columns, missing_eligible)
    output_csv(out/"missing_due_to_stock_price_filters.csv", columns, missing_ineligible)
    output_csv(out/"not_in_drom_brakes_and_racks.csv", columns,
               [r for r in missing if r["Категория"] in ("Тормозные диски","Рулевые рейки")])
    output_csv(out/"drom_not_in_supplier.csv",
               ("Производитель","Артикул","Наименование товара","Цена","Кол-во"),extra_drom)
    summary={
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "source":"Repo main/input/rossko_price.xlsx, snapshot in GitHub",
        "comparison":"Repo main/public/drom_lensk.xlsx, generated Drom Lensk feed",
        "does_not_confirm_live_drom_listings":True,
        "supplier_rows":source_rows,
        "supplier_distinct_brand_article":len(all_skus),
        "supplier_duplicates_rows":duplicate_supplier,
        "drom_rows":drom_rows,
        "drom_unique_brand_article":len(drom),
        "drom_duplicate_rows":duplicates_drom,
        "matched_supplier_keys":overlap,
        "supplier_missing_from_drom_total":len(missing),
        "missing_but_positive_price_and_stock":len(missing_eligible),
        "missing_due_to_export_rules":len(missing_ineligible),
        "missing_by_category":dict(categorised),
        "available_missing_by_category":dict(Counter(r["Категория"] for r in missing_eligible)),
        "missing_due_to_rule_breakdown":dict(reasons),
        "top_missing_brands":brand_count.most_common(20),
        "drom_rows_not_in_supplier":len(extra_drom),
        "supplier_data_status":"GitHub repository snapshots only; not live ROSSKO or Drom API",
    }
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ROSSKO_DROM_CATALOG_COMPARISON",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--rossko",required=True)
    p.add_argument("--drom",required=True)
    p.add_argument("--out",required=True)
    x=p.parse_args()
    run(Path(x.rossko),Path(x.drom),Path(x.out))
