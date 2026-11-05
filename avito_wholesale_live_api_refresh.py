#!/usr/bin/env python3
"""Private API-based refresh of *only* the preapproved Avito brake/rack SKUs.

Reads a current ROSSKO XLSX, then GetSearch only for the approved exact
brand/article entries with positive local 0-day stock. Keeps private API costs
off GitHub; the output is a retail-only map for the current workflow execution.

Security: API keys only via Actions Secrets; never in stdout, files, or Git.
Fail closed if API success rate is too low or delivery mode is unverified.
No Drom output or Drom publishing.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_active_feed_refresh import (
    seller_sku, key, price_decimal, supplier_products, add_raw_source_costs,
    read_wholesale_retail,
)
from avito_irkutsk import load_fresh_price
from avito_pricing import progressive_price
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import (
    zeep_client, rpc, choose_delivery, retry_transient,
)
from update_prices import load_config

RETAIL_COLUMNS = (
    "brand","article","supplier_price",
    "supplier_delivery_days","drom_retail","avito_retail"
)
FRESH_COLUMNS = ("brand","article")


def list_approved(archive_xml):
    """All 195 owner-approved IDs; only two categories and no duplicates."""
    root = ET.fromstring(archive_xml)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Approved XML version mismatch")
    items = root.findall("Ad")
    if not 150 <= len(items) <= 300:
        raise ValueError("Unexpected number of approved Avito listings")
    keys, ids, output = set(), set(), []
    for ad in items:
        id = ad.findtext("Id")
        k, group = seller_sku(ad)
        if not id or id in ids or k in keys:
            raise ValueError("Duplicate/invalid approved Avito SKU")
        if group not in ("Тормозные диски", "Рулевые рейки", "Радиаторы кондиционера"):
            raise ValueError("Unexpected category in approved Avito feed")
        keys.add(k)
        ids.add(id)
        output.append((k,group,ad.findtext("Brand")))
    return output


def read_previous_mapping(path):
    """Preserve existing validated retail prices and display-name spelling."""
    base = read_wholesale_retail(path)
    full = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp, delimiter=";")
        for row in reader:
            k = key(row["brand"], row["article"])
            if k not in base or k in full:
                raise ValueError("Invalid or duplicated persisted price map")
            full[k] = {**base[k], "brand": row["brand"], "article": row["article"],
                       "drom": int(row.get("drom_retail") or 0)}
    if set(full) != set(base):
        raise ValueError("Missing persisted retail rows")
    return full


def compare_and_build(approved, supplier, original, search_fn, *,
                      min_success_rate=0.70, max_api_requests=225, sleeper=time.sleep):
    """Pure coordination, inject search_fn for tests; never guesses wholesale."""
    valid = []
    for k, category, brand in approved:
        stock = supplier.get(k)
        if (stock is None or stock["Группа"] != category
                or int(stock["Остаток РОССКО"]) <= 0
                or int(stock["Срок поставки"]) != 0):
            continue
        supplier_price = price_decimal(stock.get("_source_list_price"))
        if supplier_price is None or supplier_price <= 0:
            continue
        valid.append((k,category,brand,stock,supplier_price))
    if len(valid) > max_api_requests:
        raise ValueError("Exceeded strict approved Avito-only API request cap")
    if not 110 <= len(valid) <= len(approved):
        raise ValueError("Unexpectedly few available, approved Irkutsk Avito SKUs")
    current = dict(original)
    updated = set()
    failures = Counter()
    for i,(k,category,brand,item,source_price) in enumerate(valid):
        result = search_fn(brand,item["Артикул"],category,
                           source_price,int(item["Остаток РОССКО"]))
        if result["status"] != "опт_Иркутск_подтвержден":
            failures[result["status"]] += 1
        else:
            actual = price_decimal(result.get("api_irkutsk_same_delivery_price_rub"))
            stock_ids = result.get("api_irkutsk_stock_ids","")
            if actual is None or actual<=0 or not stock_ids:
                failures["api_price_or_stock_id_invalid"] += 1
            elif price_decimal(result.get("supplier_list_price_rub")) != source_price:
                failures["api_source_cost_mismatch"] += 1
            elif actual < source_price/Decimal("10") or actual > source_price*Decimal("2"):
                failures["api_price_outside_plausible_range"] += 1
            else:
                sale_price = progressive_price(actual)
                # Persist no personal buying cost, only approved retail price.
                current[k] = {
                    "brand":brand,"article":item["Артикул"],
                    "supplier_price":source_price,
                    "days":0,"drom":current.get(k,{}).get("drom",0),
                    "avito_price":sale_price
                }
                updated.add(k)
        if (i+1)%35==0:
            print("AVITO_PRIVATE_API_CHECKPOINT",json.dumps({
                "processed":i+1,"selected_approved":len(valid),
                "confirmed":len(updated)}),flush=True)
        if i+1<len(valid):
            sleeper(0.45)
    rate = len(updated)/len(valid)
    report = {
        "time_utc":datetime.now(timezone.utc).isoformat(),
        "approved_total":len(approved),
        "available_approved_zero_day":len(valid),
        "api_requests_attempted":len(valid),
        "api_wholesale_confirmed":len(updated),
        "api_not_confirmed":len(valid)-len(updated),
        "success_rate":round(rate,4),
        "failures":dict(failures),
        "legacy_verified_retail_map_entries":len(original),
        "runtime_retail_map_entries":len(current),
        "min_acceptable_success_rate":min_success_rate,
        "no_private_buying_cost_written":True,
        "no_drom_files_written":True,
        "publish_directly":False,
    }
    if rate < min_success_rate:
        raise RuntimeError("Private API success rate insufficient: "
                           f"{len(updated)} of {len(valid)}")
    return current,updated,report


def render_results(out, retail, fresh, report):
    out.mkdir(parents=True,exist_ok=True)
    # Existing legacy map can contain non-Avito SKUs; retain it for backward
    # compatibility but NEVER send non-approved SKUs to GetSearch.
    with (out/"runtime_verified_retail_only.csv").open(
            "w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=RETAIL_COLUMNS,delimiter=";")
        writer.writeheader()
        for k in sorted(retail):
            r=retail[k]
            writer.writerow({
                "brand":r["brand"],"article":r["article"],
                "supplier_price":str(r["supplier_price"]),
                "supplier_delivery_days":r["days"],
                # Not used by Avito. Preserve older mapping's public retail
                # if supplied rather than changing Drom logic.
                "drom_retail":r.get("drom",0),
                "avito_retail":r["avito_price"]
            })
    with (out/"fresh_api_confirmed_skus.csv").open(
            "w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=FRESH_COLUMNS,delimiter=";")
        writer.writeheader()
        for k in sorted(fresh):
            writer.writerow({"brand":k[0],"article":k[1]})
    (out/"api_summary.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def run(config_path, approved_xml, retail_map, out, sample_limit=None):
    config=load_config(config_path)
    book=load_fresh_price(config,config_path.parent,2)
    try:
        supplier=supplier_products(book,config)
        add_raw_source_costs(book,supplier)
    finally:
        book.close()
    approved=list_approved(approved_xml.read_bytes())
    if sample_limit is not None:
        if not 1 <= sample_limit <= 24:
            raise ValueError("Test sample must be 1..24")
        approved=approved[:sample_limit]
    original=read_previous_mapping(retail_map)
    key1,key2=(os.environ.get("ROSSKO_API_KEY1") or "").strip(),(
        os.environ.get("ROSSKO_API_KEY2") or "").strip()
    if not key1 or not key2:
        raise RuntimeError("Required API GitHub Secrets not available")
    credentials={"KEY1":key1,"KEY2":key2}
    checkout=retry_transient(lambda: rpc(zeep_client("GetCheckoutDetails"),
                                "GetCheckoutDetails",credentials),attempts=3,
                             base_delay=1.5)
    delivery, mode=choose_delivery(checkout)
    if not delivery:
        raise RuntimeError("No approved ROSSKO checkout fulfillment option")
    search_client=zeep_client("GetSearch")

    def search(brand, article, group, source_cost, quantity):
        item={
            "category":group,"brand":brand,"article":article,
            "description":group,"supplier_list_price_rub":str(source_cost),
            "supplier_stock":quantity,"supplier_delivery_days":0,
        }
        return audit_one(search_client,credentials,delivery,item)

    if sample_limit is not None:
        # Sample verifies live API connectivity, without building a release.
        selected=[]
        for t in approved:
            k,group,brand=t
            if k in supplier and int(supplier[k]["Срок поставки"])==0:
                selected.append(t)
        if not selected:
            raise RuntimeError("Sample contains no in-stock approved SKUs")
        for k,group,brand in selected:
            item=supplier[k]
            result=search(brand,item["Артикул"],group,
                          price_decimal(item["_source_list_price"]),
                          int(item["Остаток РОССКО"]))
            print("AVITO_API_SAMPLE",json.dumps({
                "group":group,"brand":brand,"article":item["Артикул"],
                "status":result["status"],"personal_cost_obtained":bool(
                  result.get("api_irkutsk_same_delivery_price_rub"))},
                ensure_ascii=False),flush=True)
        return
    result,fresh,summary=compare_and_build(approved,supplier,original,search)
    summary["checkout_mode"]=mode
    render_results(out,result,fresh,summary)
    print("AVITO_WHOLESALE_API_REFRESH",json.dumps(summary,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",type=Path,required=True)
    p.add_argument("--approved-catalog",type=Path,required=True)
    p.add_argument("--retail-map",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--sample-limit",type=int)
    a=p.parse_args()
    run(a.config,a.approved_catalog,a.retail_map,a.out,a.sample_limit)


if __name__=="__main__":
    main()
