"""Two Avito workbook previews from ORIGINAL templates and the fresh 50-SKU list.

Never asserts usage rights, exact photo/article match, compatibility or
inventory at the seller's pickup point. Never publishes to Avito.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from avito_feed import HEADERS, GROUPS, make_fields, stable_id
from avito_irkutsk import load_fresh_price, select_rows, load_sku_whitelist
from avito_photo_check import approved_url, retrieve_image
from update_prices import load_config, normalize_key, read_photo_map, text

CONFIG_PATH = Path("config.json")
ALLOWLIST = Path("input/avito_pilot_articles.csv")
OUT = Path("output/avito_irkutsk_preflight")
CONFIRMATIONS = Path("avito_pilot_confirmations.json")
RED = PatternFill("solid", fgColor="FCE8E6")
YELLOW = PatternFill("solid", fgColor="FFF2CC")
BLUE = PatternFill("solid", fgColor="DCEAF7")
HIGHLIGHT = Font(bold=True, color="9C0006")


def read_pilot_confirmations():
    info = json.loads(CONFIRMATIONS.read_text(encoding="utf-8"))
    if info.get("scope_file") != str(ALLOWLIST) or info.get("sku_count") != 50:
        raise ValueError("Seller statements must apply to the exact 50 SKU pilot")
    if not (info.get("condition") == "Новое" and info.get("condition_confirmed_by_seller") is True):
        raise ValueError("Condition is not seller-confirmed")
    if info.get("rossko_photo_permission_confirmed_by_seller") is not True:
        raise ValueError("Supplier photo permission is not confirmed by seller")
    if info.get("pickup_immediate_confirmed_by_seller") is not True:
        raise ValueError("Immediate pickup is not confirmed by the seller")
    return info


def key(brand, article):
    return normalize_key(brand) + "|" + normalize_key(article)


def check_original_template(path, group):
    if not path.is_file():
        raise FileNotFoundError(path)
    book = load_workbook(path)
    # Reference sheets must be hidden: otherwise Avito may treat the
    # reference values as hundreds of additional ads with no ID.
    for auxiliary in book.worksheets:
        if auxiliary.title not in {"Инструкция", "Объявления"}:
            auxiliary.sheet_state = "hidden"
    ws = book["Объявления"]
    headers = tuple(text(ws.cell(2, col).value) for col in range(1, 72))
    if headers != HEADERS:
        raise ValueError("Template headings changed: " + str(path))
    if not text(ws.cell(1, 1).value).endswith(GROUPS[group]["category"]):
        raise ValueError("Wrong Avito subgroup template: " + str(path))
    if any(ws.cell(i, 1).value is not None for i in range(5, ws.max_row + 1)):
        raise ValueError("Avito template already contains listings")
    return book


def add_qa_sheet(book, rows):
    sheet = book.create_sheet("ПРОВЕРКА — НЕ ЗАГРУЖАТЬ", 0)
    sheet.append(["ЧЕРНОВИК. НЕ ЗАГРУЖАТЬ НА АВИТО БЕЗ ПРОВЕРКИ."])
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=12)
    sheet["A1"].font = Font(size=15, bold=True, color="9C0006")
    sheet["A1"].fill = RED
    sheet["A1"].alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[1].height = 32
    sheet.append(["Новое состояние, право на фото и возможность самовывоза подтверждены продавцом. Наличие в свежем прайсе РОССКО проверено при сборке, однако применимость и точное соответствие фото требуют сверки."])
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=12)
    sheet["A2"].alignment = Alignment(wrap_text=True)
    sheet.row_dimensions[2].height = 32
    headers = ["№", "Группа", "Бренд", "Артикул", "Цена ₽", "Остаток РОССКО",
               "Применимость поставщика", "Фото URL", "Фото соответствует артикулу?",
               "Разрешено использовать фото?", "Применимость проверена?",
               "Состояние / выдача / решение"]
    for j, name in enumerate(headers, 1):
        c = sheet.cell(4, j, name)
        c.fill = BLUE
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[4].height = 36
    for i, row in enumerate(rows, 5):
        product, url = row
        values = [
            i - 4, product["Группа"], product["Бренд"], product["Артикул"],
            product["Цена Авито"], product["Остаток РОССКО"],
            product.get("Применимость", ""), url, "", "Да (со слов продавца)", "",
            "Новое; выдача по адресу подтверждена продавцом, остатки обновляются",
        ]
        for j, value in enumerate(values, 1):
            c = sheet.cell(i, j, value)
            c.alignment = Alignment(vertical="top", wrap_text=j in (7, 8))
            if j >= 9:
                c.fill = YELLOW
    widths = [7, 22, 20, 18, 13, 18, 48, 52, 28, 30, 26, 35]
    for i, w in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(i)].width = w
    sheet.freeze_panes = "C5"
    sheet.auto_filter.ref = f"A4:L{sheet.max_row}"
    sheet.sheet_properties.tabColor = "C62828"


def populate_group(group, items, config):
    template = CONFIG_PATH.parent / text(config["avito"][GROUPS[group]["template_key"]])
    book = check_original_template(template, group)
    tab = book["Объявления"]
    address = text(config["avito"]["pickup_address"])
    for idx, (p, url) in enumerate(items, 5):
        # Data from Rossko is a candidate only, not fully verified metadata.
        candidate = {"fitment":text(p.get("Применимость")), "photo_urls":url, "oem_number":""}
        fields = make_fields(p, candidate, address)
        fields["Описание объявления"] = (
            f"{GROUPS[group]['name']} {p['Бренд']}, артикул {p['Артикул']}.\n"
            "Состояние: новое. Доступно к самовывозу в Иркутске.\n"
            "Адрес самовывоза: " + address + ".\n"
            "Пожалуйста, уточняйте наличие и совместимость по VIN перед покупкой."
        )
        # Seller confirmed "new" and immediate pickup for this 50-SKU pilot.
        # Each SKU is included only after a fresh Rossko local-stock check.
        # Avoid claims about inventory persisting after the timestamp of export.
        fields["Состояние"] = "Новое"
        fields["Доступность"] = "В наличии"
        for j, header in enumerate(HEADERS, 1):
            value=fields.get(header)
            if value not in ("", None):
                tab.cell(idx, j, value)
            if header in ("Ссылки на фото", "Авто для которых подходит запчасть", "Состояние", "Доступность"):
                tab.cell(idx, j).fill = YELLOW
        # Must not invent other template values or mark verification complete.
    add_qa_sheet(book, items)
    return book


def main():
    config = load_config(CONFIG_PATH)
    read_pilot_confirmations()
    allow = load_sku_whitelist(ALLOWLIST)
    if len(allow) != 50:
        raise RuntimeError(f"Expected exact 50 pinned SKU pairs, got {len(allow)}")
    photo_map = read_photo_map(CONFIG_PATH.parent / text(config.get("drom", {}).get("photo_map_path") or "input/photos.csv"))
    wb = load_fresh_price(config, CONFIG_PATH.parent, 2)
    try:
        candidates=select_rows(wb.active, config)
    finally:
        wb.close()
    chosen={key(p["Бренд"],p["Артикул"]):p for p in candidates if key(p["Бренд"],p["Артикул"]) in allow}
    if set(chosen)!=allow:
        missing=sorted(allow-set(chosen))
        raise RuntimeError(f"Some pinned SKUs are no longer available. No preview generated. Missing: {missing[:12]}")
    groups={name:[] for name in GROUPS}
    failures=[]
    for sku in sorted(chosen):
        item=chosen[sku]
        url=photo_map.get(sku,"")
        if not approved_url(url):
            failures.append((sku,"missing_or_disallowed_photo"))
            continue
        photo,status,width,height,digest=retrieve_image(url)
        if status!="available_unverified" or not digest:
            failures.append((sku,status))
            continue
        groups[item["Группа"]].append((item,url))
    if failures:
        raise RuntimeError(f"Photo validation failed: {failures[:12]}. No preview generated.")
    if [len(groups[n]) for n in GROUPS] != [25,25]:
        raise RuntimeError(f"Wrong category split: {dict((k,len(v)) for k,v in groups.items())}")
    OUT.mkdir(parents=True,exist_ok=True)
    for name,items in groups.items():
        items.sort(key=lambda r:(normalize_key(r[0]["Бренд"]),normalize_key(r[0]["Артикул"])))
        book=populate_group(name,items,config)
        fname=("PREVIEW_steering_25_NOT_FOR_UPLOAD.xlsx" if name=="Рулевые рейки" else "PREVIEW_brakes_25_NOT_FOR_UPLOAD.xlsx")
        book.save(OUT/fname)
        book.close()
        print("PREVIEW_GENERATED",name,len(items),str(OUT/fname),flush=True)
    with (OUT/"checklist_50.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.writer(fp,delimiter=";")
        writer.writerow(["Группа","Бренд","Артикул","Цена ₽","Остаток","Фото URL","Применимость РОССКО","Фото/артикул проверены?","Права на фото подтверждены?","Применимость проверена?","Новое и пункт выдачи подтверждены?","Можно публиковать?"])
        for name,items in groups.items():
            for p,url in items:
                writer.writerow([name,p["Бренд"],p["Артикул"],p["Цена Авито"],p["Остаток РОССКО"],url,p.get("Применимость",""),"","Да, со слов продавца","","Новое и самовывоз подтверждены продавцом",""])
    (OUT/"README_PREVIEW.txt").write_text(
        "ПРОВЕРОЧНЫЙ КОМПЛЕКТ, НЕ ДЛЯ ПУБЛИКАЦИИ.\n"
        "Два XLSX созданы на базе оригинальных шаблонов Авито от 13 октября 2026 года.\n"
        "50 артикулов присутствовали в свежем прайсе РОССКО и 50 фото технически открылись.\n"
        "Новое состояние, разрешение на фото РОССКО и возможность самовывоза подтверждены продавцом.\n"
        "Остатки проверяются по свежему прайсу перед экспортом. Применимость и соответствие фото артикулу требуют дополнительной сверки.\n"
        "Прежде чем публиковать, проверьте справочники Авито и все 50 строк чек-листа.\n"
        "Никакая автопубликация не включена.\n",
        encoding="utf-8",
    )
    print("PREFLIGHT_OK=50; seller_confirmed_condition=Новое; pickup_immediate_confirmed=true; availability=В наличии; publication_approvals=0",flush=True)


if __name__=="__main__":
    main()
