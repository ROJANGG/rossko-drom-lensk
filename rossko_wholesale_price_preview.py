#!/usr/bin/env python3
"""REVIEW ONLY: proposed sale prices when exact IRKUTSK warehouse API price verified.

Does not edit source price file or public Drom/Avito feeds.
Emits private CSV with current public-price-calculator vs new wholesale-calculator
for each individually confirmed SKU. No averaging or guessed discounts.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from avito_pricing import progressive_price


def public_drom_price(cost):
    cost=Decimal(str(cost))
    if cost<=0:
        raise ValueError("invalid cost")
    n=cost*Decimal("1.37")
    return int((n/50).to_integral_value(rounding=ROUND_CEILING)*50)


def allowed_wholesale_row(row):
    """A price is usable only if API confirmed same warehouse city and days."""
    return (
        row.get("status")=="confirmed_irkutsk_matching_delivery"
        and row.get("supplier_price_comparable")=="True"
        and row.get("api_warehouse_city_verified")=="True"
        and row.get("api_matching_delivery_lowest_rub","").strip()!=""
    )


def make_proposal(row):
    if not allowed_wholesale_row(row):
        return None
    brand=row["brand"].strip()
    sku=row["article"].strip()
    before=Decimal(row["supplier_list_price_rub"])
    after=Decimal(row["api_matching_delivery_lowest_rub"])
    if not brand or not sku or before<=0 or after<=0:
        return None
    old_drom=public_drom_price(before)
    new_drom=public_drom_price(after)
    old_avito=progressive_price(before)
    new_avito=progressive_price(after)
    return {
        "brand":brand,"article":sku,"category":row.get("category",""),
        "supplier_list_price_rub":str(before),
        "verified_irkutsk_api_cost_rub":str(after),
        "supplier_delivery_days":row.get("supplier_delivery_days",""),
        "confirmed_irkutsk_stock_ids":row.get("api_irkutsk_stock_ids",""),
        "drom_current_formula_rub":old_drom,
        "drom_wholesale_formula_preview_rub":new_drom,
        "drom_price_delta_rub":new_drom-old_drom,
        "avito_current_formula_rub":old_avito,
        "avito_wholesale_formula_preview_rub":new_avito,
        "avito_price_delta_rub":new_avito-old_avito,
        "publish_permitted":"NO_REVIEW_ONLY"
    }


def run(source, output):
    output.mkdir(parents=True,exist_ok=True)
    with source.open(encoding="utf-8-sig",newline="") as fp:
        rows=list(csv.DictReader(fp,delimiter=";"))
    out=[]
    seen=set()
    for row in rows:
        item=make_proposal(row)
        if item:
            key=(item["brand"].casefold(),item["article"].casefold())
            if key in seen:
                raise ValueError("Duplicate API SKU in private check; abort")
            seen.add(key)
            out.append(item)
    fields=("brand","article","category","supplier_list_price_rub",
            "verified_irkutsk_api_cost_rub","supplier_delivery_days",
            "confirmed_irkutsk_stock_ids","drom_current_formula_rub",
            "drom_wholesale_formula_preview_rub","drom_price_delta_rub",
            "avito_current_formula_rub","avito_wholesale_formula_preview_rub",
            "avito_price_delta_rub","publish_permitted")
    with (output/"WHOLESALE_PRICING_REVIEW_ONLY.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=fields,delimiter=";")
        writer.writeheader()
        writer.writerows(out)
    print("ROSSKO_PRIVATE_PRICING_PREVIEW",{ "eligible_irkutsk_skus":len(out),
        "sample_rows":len(rows),"publish_permitted":False},flush=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--api-csv",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    run(args.api_csv,args.output)


if __name__=="__main__":
    main()
