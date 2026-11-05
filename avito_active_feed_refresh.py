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
    # All 195 existing titles obey this template; refuse unrecognized ones
    # instead of guessing which article an ad represents.
    matched = re.fullmatch(
        r"(Тормозной диск|Рулевая рейка)\s+(.+)\s+([A-Za-z0-9.+/\-]+)\s+новый",
        title, flags=re.I,
    )
    if not matched or normalize_key(matched.group(2)) != normalize_key(brand):
        raise ValueError("Unrecognized existing Avito title for ID: " + str(ad.findtext("Id")))
    if matched.group(1).casefold().startswith("тормозной"):
        category = "Тормозные диски"
    else:
        category = "Рулевые рейки"
    return key(brand, matched.group(3)), category


def supplier_products(book, config):
    items = select_rows(book.active, config)
    found = {}
    for item in items:
        k = key(item["Бренд"], item["Артикул"])
        if k in found:
            raise ValueError("Duplicate supplier brand/article")
        if item["Группа"] not in ("Тормозные диски", "Рулевые рейки"):
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
         require_second=True, min_ads=150):
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


def execute(current, config_path, verified_map, out, *, max_removed=12):
    config = load_config(config_path)
    book = load_fresh_price(config, config_path.parent, 2)
    try:
        products = supplier_products(book, config)
        add_raw_source_costs(book, products)
    finally:
        book.close()
    source_map = read_wholesale_retail(verified_map)
    old_xml = current.read_bytes()
    # Before paying for a second request, inspect missing SKU count against
    # strict limit. If mismatched too many, fail without touching XML.
    _, initial = plan(old_xml, products, source_map, max_removed=max_removed,
                      require_second=False)
    second = None
    if initial["removed_confirmed_no_stock"]:
        second = second_independent_stock_sample(config)
    result, report = plan(old_xml, products, source_map, second_stock=second,
                          max_removed=max_removed)
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
    parser.add_argument("--verified-retail-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-removals", type=int, default=12)
    args = parser.parse_args()
    execute(args.previous, args.config, args.verified_retail_map,
            args.out, max_removed=args.max_removals)


if __name__=="__main__":
    main()
