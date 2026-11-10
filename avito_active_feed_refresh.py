#!/usr/bin/env python3
"""Avito-only live feed refresh: refresh VERIFIED wholesale-based prices + stock.

Retains original Avito IDs/OEM/photos/descriptions unchanged and NEVER adds
unreviewed SKUs. Fresh ROSSKO Irkutsk XLSX is mandatory. Missing SKUs are
independently rechecked in a second HTTPS supplier XLSX download before
a capped removal is permitted. No fixed-price discount or fallback to retail
supplier-price markup. No publication: workflow owns the git push.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import copy
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from openpyxl import load_workbook

from avito_irkutsk import load_fresh_price, select_rows
from update_prices import load_config, normalize_key


def key(brand, article):
    return normalize_key(brand), normalize_key(article)


def price_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (ValueError, InvalidOperation):
        return None


def seller_sku(ad):
    title = ad.findtext("Title", "")
    brand = ad.findtext("Brand", "")
    # Parse only explicit supported titles, including individually approved extensions.
    matched = re.fullmatch(
        r"(Тормозной диск|Рулевая рейка|Радиатор кондиционера|Колодки барабанные|Свеча накаливания|Свечи накала)\s+(.+)\s+([A-Za-z0-9.+/\-]+)\s+(новый|новые|новая)",
        title, flags=re.I,
    )
    if not matched or normalize_key(matched.group(2)) != normalize_key(brand):
        raise ValueError("Unrecognized existing Avito title for ID: " + str(ad.findtext("Id")))
    if matched.group(1).casefold().startswith("тормозной"):
        category = "Тормозные диски"
    elif matched.group(1).casefold().startswith("рулевая"):
        category = "Рулевые рейки"
    elif matched.group(1).casefold().startswith("радиатор"):
        category = "Радиаторы кондиционера"
    elif matched.group(1).casefold().startswith("колодки"):
        category = "Колодки барабанные"
    else:
        category = "Свечи накала"
    return key(brand, matched.group(3)), category


EXTRA_APPROVED_STOCK_CATEGORIES = {
    ("luzar", "lrac3034"): "Радиаторы кондиционера",
    ("luzar", "lrac3049"): "Радиаторы кондиционера",
}
_extension_path = Path(__file__).parent / "input/avito_verified_extension_evidence.json"
if _extension_path.exists():
    _manifest = json.loads(_extension_path.read_text(encoding="utf-8"))
    _scope = {key(x["brand"], x["article"]) for x in _manifest["scope_skus"]}
    for _record in _manifest["items"]:
        _k = key(_record["brand"], _record["article"])
        if (_k not in _scope or _record["category"] not in
                ("Колодки барабанные", "Радиаторы кондиционера", "Свечи накала")
                or not _record.get("exact_sku_verified")
                or not _record.get("oem") or not _record.get("fitment")
                or _record.get("photo_review") != "ACTUAL_EXACT_PRODUCT_PHOTO_VERIFIED"
                or not _record.get("images")):
            raise ValueError("Unverified extension in stock allowlist")
        if _k in EXTRA_APPROVED_STOCK_CATEGORIES:
            raise ValueError("Duplicate approved extension SKU")
        EXTRA_APPROVED_STOCK_CATEGORIES[_k] = _record["category"]
EXTRA_APPROVED_STOCK_SKUS = set(EXTRA_APPROVED_STOCK_CATEGORIES)


def supplier_products(book, config):
    items = select_rows(book.active, config)
    # Only individually OEM/photo-approved radiator SKUs, not the entire
    # new category. The same supplier zero-day/positive-stock rules apply.
    from avito_extra_categories_census import classify
    from update_prices import (
        read_header_map,get_cell,text,parse_stock_count,parse_decimal
    )
    from avito_irkutsk import zero_days
    h = read_header_map(book.active)
    for row in book.active.iter_rows(min_row=2):
        brand = text(get_cell(row,h,"Бренд"))
        article = text(get_cell(row,h,"Артикул"))
        k = key(brand,article)
        if k not in EXTRA_APPROVED_STOCK_SKUS:
            continue
        description = text(get_cell(row,h,"Описание"))
        category = EXTRA_APPROVED_STOCK_CATEGORIES[k]
        if classify(description) != category:
            continue
        cities=[c for c in ("Город склада","Склад отгрузки","Филиал","Город") if c in h]
        if cities and not any("иркутск" in text(get_cell(row,h,c)).casefold() for c in cities):
            continue
        if not zero_days(get_cell(row,h,"Срок поставки, дн.")):
            continue
        rawstock=text(get_cell(row,h,"Наличие"))
        stock=0 if rawstock.lstrip().startswith("-") else parse_stock_count(rawstock)
        price=parse_decimal(get_cell(row,h,"Цена, руб."))
        if stock<=0 or price is None or price<=0:
            continue
        items.append({
            "Группа":category,
            "Бренд":brand,"Артикул":article,
            "Остаток РОССКО":stock,
            "Срок поставки":0,
            "_source_list_price":price
        })
    found = {}
    for item in items:
        k = key(item["Бренд"], item["Артикул"])
        if k in found:
            raise ValueError("Duplicate supplier brand/article")
        if item["Группа"] not in ("Тормозные диски", "Рулевые рейки", "Радиаторы кондиционера", "Колодки барабанные", "Свечи накала"):
            raise ValueError("Unexpected supplier category")
        found[k] = item
    return found


def read_wholesale_retail(path):
    """Existing retail-only validated map, not private ROSSKO costs."""
    data = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        expected = {"brand", "article", "supplier_price", "supplier_delivery_days", "avito_retail"}
        if not expected <= set(reader.fieldnames or ()):
            raise ValueError("Missing verified wholesale retail map columns")
        for row in reader:
            k = key(row["brand"], row["article"])
            price = price_decimal(row["supplier_price"])
            new = price_decimal(row["avito_retail"])
            days = int(row["supplier_delivery_days"])
            if not all(k) or k in data or price is None or price <= 0 or new is None or new <= 0 or new % 50 != 0 or days < 0:
                raise ValueError("Invalid wholesale retail mapping for SKU " + str(k))
            data[k] = {"supplier_price": price, "avito_price": int(new), "days": days}
    if len(data) < 700:
        raise ValueError("Missing expected verified wholesale retail map")
    return data


def second_independent_stock_sample(config):
    """Download the supplier file AGAIN; no cross-run cached state."""
    conf = config.get("rossko", {})
    if conf.get("price_source") != "url":
        raise ValueError("Live stock must come from HTTPS supplier source")
    url = str(conf.get("price_url", ""))
    if not url.startswith("https://"):
        raise ValueError("Invalid source URL")
    response = requests.get(url, timeout=int(conf.get("download_timeout_seconds") or 120))
    response.raise_for_status()
    raw = response.content
    if len(raw) < 10000 or not raw.startswith(b"PK"):
        raise ValueError("Second supplier download is not a valid XLSX")
    book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        return supplier_products(book, config)
    finally:
        book.close()


def plan(old_xml, source, retail, *, second_stock=None, max_removed=12,
         require_second=True, min_ads=150, freshly_verified=None):
    root = ET.fromstring(old_xml)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Invalid existing XML structure")
    ads = root.findall("Ad")
    if not min_ads <= len(ads) <= 300:
        raise ValueError("Unusual live ad count; refuse to replace")
    ids = [ad.findtext("Id") for ad in ads]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        raise ValueError("Missing or duplicate current Avito IDs")
    matched_keys = set()
    product_map = {}
    for ad in ads:
        k, group = seller_sku(ad)
        if k in matched_keys:
            raise ValueError("Duplicate current supplier SKU")
        matched_keys.add(k)
        product_map[k] = (ad, group)

    absent = sorted(k for k in product_map if k not in source or
                    source[k]["Группа"] != product_map[k][1])
    if len(absent) > max_removed or len(absent) / len(ads) > 0.075:
        raise ValueError(f"Unusual stock removals {len(absent)} / {len(ads)}; manual review")
    if absent and require_second:
        if second_stock is None:
            raise ValueError("Second independently downloaded stock snapshot required")
        contradicted = [k for k in absent if k in second_stock and
                        second_stock[k]["Группа"] == product_map[k][1]]
        if contradicted:
            raise ValueError("Supplier snapshots disagree on SKU stock: " + str(contradicted))

    repriced, unchanged, missing_price, checked, obsolete = [], 0, [], 0, []
    for k, (ad, group) in product_map.items():
        if k in absent:
            obsolete.append({"id": ad.findtext("Id"),
                             "brand_article": "|".join(k), "reason": "not_in_fresh_Irkutsk_zero_day_stock"})
            root.remove(ad)
            continue
        item = source[k]
        qty = int(item["Остаток РОССКО"])
        if qty < 1 or item["Срок поставки"] != 0:
            raise ValueError("Selected supplier item is not in-stock zero-day")
        checked += 1
        current = int(ad.findtext("Price"))
        record = retail.get(k)
        if freshly_verified is not None and k not in freshly_verified:
            missing_price.append({"sku": "|".join(k), "reason": "current_personal_api_price_not_verified"})
            continue
        fresh_supplier = price_decimal(item.get("_source_list_price"))
        if record is None:
            missing_price.append({"sku": "|".join(k), "reason": "no_api_verified_retail_price"})
            continue
        # select_rows already computes list-based retail, which cannot be
        # inverted reliably. Direct exact list-price lookup is added below.
        if fresh_supplier is None or fresh_supplier != record["supplier_price"] or record["days"] != 0:
            missing_price.append({"sku": "|".join(k), "reason": "supplier_cost_or_delivery_changed"})
            continue
        new = record["avito_price"]
        if abs(new-current)*100/current > 40:
            raise ValueError("Excessive retail price change for " + str(ad.findtext("Id")))
        if current != new:
            ad.find("Price").text = str(new)
            repriced.append({"id": ad.findtext("Id"), "old": current, "new": new,
                             "brand_article": "|".join(k)})
        else:
            unchanged += 1

    kept_ids = [ad.findtext("Id") for ad in root.findall("Ad")]
    if kept_ids != [i for i in ids if i not in {r["id"] for r in obsolete}]:
        raise ValueError("Existing ID order changed unexpectedly")
    if len(kept_ids) < min_ads:
        raise ValueError("Resulting XML too small")
    ET.indent(root, space="  ")
    content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    check = ET.fromstring(content)
    if len(check.findall("Ad")) != len(kept_ids):
        raise ValueError("Output XML validation failed")
    report = {
        "stock_checked_ads": checked,
        "before": len(ads), "after": len(kept_ids),
        "removed_confirmed_no_stock": len(obsolete),
        "repriced": len(repriced),
        "price_unchanged_verified": unchanged,
        "price_kept_unverified": len(missing_price),
        "removed": obsolete,
        "price_not_refreshed": missing_price,
        "price_changes": repriced,
        "removed_independently_verified": bool(not absent or second_stock is not None),
        "source": "fresh ROSSKO Irkutsk zero-day supplier XLSX",
        "pricing_source": "source-price-matched verified personal wholesale retail map only",
        "no_new_ads": True,
        "non_price_fields_of_kept_ads_unchanged": True,
    }
    return content, report


def add_raw_source_costs(book, records):
    # Price exactly from the same workbook used for stock validation.
    ws = book.active
    h = {str(c.value or "").strip(): i for i, c in enumerate(ws[1])}
    for required in ("Бренд", "Артикул", "Цена, руб."):
        if required not in h:
            raise ValueError("Missing source price column")
    for r in ws.iter_rows(min_row=2, values_only=True):
        k = key(r[h["Бренд"]], r[h["Артикул"]])
        if k in records and "_source_list_price" not in records[k]:
            records[k]["_source_list_price"] = r[h["Цена, руб."]]


def reconstruct_approved_catalog(archive_xml, live_xml, source, verified, *, freshly_verified=None):
    """Retain ALL current ad content; permit restocks only from archived approved IDs.

    A restocked SKU is restored only when the account-specific wholesale
    price remains individually verified against the current supplier price.
    If not, it stays out until manually reviewed rather than falling back
    to the retail supplier price.
    """
    archive = ET.fromstring(archive_xml)
    live = ET.fromstring(live_xml)
    if archive.tag != "Ads" or live.tag != "Ads" or archive.attrib != live.attrib:
        raise ValueError("Mismatch between approved archive and live Avito feed")
    known = archive.findall("Ad")
    existing = live.findall("Ad")
    if not 150 <= len(known) <= 300 or not 150 <= len(existing) <= len(known):
        raise ValueError("Invalid approved archive or active listing count")
    known_by_id = {a.findtext("Id"): a for a in known}
    live_by_id = {a.findtext("Id"): a for a in existing}
    if None in known_by_id or None in live_by_id or len(known_by_id) != len(known) or len(live_by_id) != len(existing):
        raise ValueError("Missing/duplicate Avito IDs")
    if not set(live_by_id) <= set(known_by_id):
        raise ValueError("Unapproved ID in live feed")
    result = ET.Element("Ads", archive.attrib)
    restored = []
    for entry in known:
        id = entry.findtext("Id")
        k, group = seller_sku(entry)
        if id in live_by_id:
            current_key, current_group = seller_sku(live_by_id[id])
            if current_key != k or current_group != group:
                raise ValueError("Live ID source brand/article changed unexpectedly")
            result.append(copy.deepcopy(live_by_id[id]))
            continue
        product = source.get(k)
        trusted = verified.get(k)
        if not product or not trusted or product["Группа"] != group:
            continue
        if freshly_verified is not None and k not in freshly_verified:
            continue
        source_price = price_decimal(product.get("_source_list_price"))
        if (source_price is None or source_price != trusted["supplier_price"]
                or trusted["days"] != 0):
            continue
        proposed = copy.deepcopy(entry)
        proposed.find("Price").text = str(trusted["avito_price"])
        result.append(proposed)
        restored.append({"id": id, "brand_article": "|".join(k)})
    if len(restored) > 12:
        raise ValueError("Unexpected burst of returning Avito inventory")
    return ET.tostring(result, encoding="utf-8", xml_declaration=True), restored


def read_fresh_confirmed(path):
    """Only exact SKU keys with a fresh ROSSKO API confirmation this run."""
    keys = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not {"brand", "article"} <= set(reader.fieldnames or []):
            raise ValueError("Fresh API confirmation file lacks brand/article")
        for row in reader:
            k = key(row["brand"], row["article"])
            if not all(k) or k in keys:
                raise ValueError("Duplicate/invalid fresh API key")
            keys.add(k)
    if not 100 <= len(keys) <= 300:
        raise ValueError("Insufficient fresh API confirmations; refuse live feed update")
    return keys


def execute(current, config_path, verified_map, out, *, approved_catalog=None, max_removed=12, fresh_confirmations=None):
    config = load_config(config_path)
    book = load_fresh_price(config, config_path.parent, 2)
    try:
        products = supplier_products(book, config)
        add_raw_source_costs(book, products)
    finally:
        book.close()
    source_map = read_wholesale_retail(verified_map)
    fresh = read_fresh_confirmed(fresh_confirmations) if fresh_confirmations else None
    if fresh is not None and not fresh <= set(source_map):
        raise ValueError("Fresh confirmation is not part of verified retail map")
    previous_live_xml = current.read_bytes()
    approved_xml = approved_catalog.read_bytes() if approved_catalog else previous_live_xml
    universe, restocks = reconstruct_approved_catalog(
        approved_xml, previous_live_xml, products, source_map,
        freshly_verified=fresh)
    # First pass: count differences without publishing or additional requests.
    _, initial = plan(universe, products, source_map,
                      max_removed=max_removed, require_second=False,
                      freshly_verified=fresh)
    second = None
    if initial["removed_confirmed_no_stock"] or restocks:
        second = second_independent_stock_sample(config)
        for restored in restocks:
            brand,article = restored["brand_article"].split("|",1)
            k = (brand,article)
            if k not in second or second[k]["Группа"] != products[k]["Группа"]:
                raise ValueError("Supplier snapshots disagree on returned stock")
    result, report = plan(universe, products, source_map,
                          second_stock=second, max_removed=max_removed,
                          freshly_verified=fresh)
    result_ids = [a.findtext("Id") for a in ET.fromstring(result).findall("Ad")]
    prev_root = ET.fromstring(previous_live_xml)
    previous_ads = prev_root.findall("Ad")
    previous_ids = [a.findtext("Id") for a in previous_ads]
    previous_by_id = {a.findtext("Id"):a for a in previous_ads}
    new_by_id = {a.findtext("Id"):a for a in ET.fromstring(result).findall("Ad")}
    added_ids = sorted(set(result_ids) - set(previous_ids))
    removed_ids = sorted(set(previous_ids) - set(result_ids))
    if set(added_ids) != {r["id"] for r in restocks}:
        raise ValueError("Unexpected newly added feed IDs")
    if len(removed_ids) > max_removed or len(removed_ids) / len(previous_ids) > 0.075:
        raise ValueError("Unexpected previously active ad removals")
    # Current ads may change PRICE only; old photos, OEMs and all other fields
    # must remain byte-for-byte-equivalent after XML parsing.
    for id in set(previous_ids) & set(result_ids):
        old = copy.deepcopy(previous_by_id[id])
        new = copy.deepcopy(new_by_id[id])
        old.remove(old.find("Price"))
        new.remove(new.find("Price"))
        if ET.tostring(old) != ET.tostring(new):
            raise ValueError("Unexpected non-price field difference for ID "+str(id))
    report["current_api_verified_skus"] = len(fresh) if fresh is not None else None
    report["current_live_before"] = len(previous_ids)
    report["restocked_approved_ads"] = added_ids
    report["removed_from_previous_live_feed"] = removed_ids
    report["restock_supplier_double_checked"] = bool(not restocks or second is not None)
    report["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / "AVITO_ACTIVE_PRICES_STOCK_CANDIDATE.xml").write_bytes(result)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n",
                                     encoding="utf-8")
    # only public retail prices, no purchase costs, API secrets or raw XLSX
    print("AVITO_ACTIVE_REFRESH", json.dumps(
        {k:v for k,v in report.items() if not isinstance(v,list)}, ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--approved-catalog", type=Path)
    parser.add_argument("--verified-retail-map", type=Path, required=True)
    parser.add_argument("--fresh-api-confirmations", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-removals", type=int, default=12)
    args = parser.parse_args()
    execute(args.previous, args.config, args.verified_retail_map,
            args.out, approved_catalog=args.approved_catalog,
            max_removed=args.max_removals,
            fresh_confirmations=args.fresh_api_confirmations)


if __name__=="__main__":
    main()

