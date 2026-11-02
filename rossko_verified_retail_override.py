#!/usr/bin/env python3
"""Replace public retail prices ONLY for exact-source-confirmed brands+SKUs.

Retail CSV contains no private purchase price. This script can be run after
the normal ROSSKO=>Drom exporter, and on a fully staged Avito XML candidate.
All other rows and IDs remain unchanged. No direct git or network I/O.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import Counter
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from xml.etree import ElementTree as ET
from openpyxl import load_workbook

from rossko_verified_price_release_plan import normalize, price_float, extract_title_key
from avito_pricing import progressive_price


def drom_baseline(cost):
    return int(((cost*Decimal("1.37"))/50).to_integral_value(rounding=ROUND_CEILING)*50)


def read_retail_map(path):
    prices={}
    with Path(path).open(encoding="utf-8-sig",newline="") as fp:
        for r in csv.DictReader(fp,delimiter=";"):
            key=(normalize(r.get("brand")),normalize(r.get("article")))
            if not all(key) or key in prices:
                raise ValueError("Empty or duplicate retail SKU key")
            c=price_float(r.get("supplier_price"))
            drom=int(r["drom_retail"])
            avito=int(r["avito_retail"])
            days=int(r["supplier_delivery_days"])
            if c is None or c<=0 or min(drom,avito)<=0 or days<0:
                raise ValueError("Invalid verified retail override")
            prices[key]={"source":c,"drom":drom,"avito":avito,"days":days}
    if len(prices)<100:
        raise ValueError("Too few validated retail price overrides")
    return prices


def apply_drom(path,retail):
    wb=load_workbook(path)
    ws=wb.active
    h={str(c.value or "").strip():i for i,c in enumerate(ws[1])}
    required=("Производитель","Артикул","Цена")
    if not set(required)<=set(h):
        raise ValueError("Drom export does not contain required columns")
    changed=[]
    for row in ws.iter_rows(min_row=2):
        k=(normalize(row[h["Производитель"]].value),normalize(row[h["Артикул"]].value))
        item=retail.get(k)
        if not item:continue
        old=int(row[h["Цена"]].value)
        expected=drom_baseline(item["source"])
        # Supplier price must remain unchanged from the validated API batch.
        if old!=expected:continue
        new=item["drom"]
        if new<=0:raise ValueError("Invalid new Drom price")
        if new!=old:
            row[h["Цена"]].value=new
            changed.append({"brand":str(row[h["Производитель"]].value),
                            "article":str(row[h["Артикул"]].value),
                            "old":old,"new":new})
    if len(changed)<100:
        raise ValueError("Too few Drom changes, check source/prices before release")
    wb.save(path)
    return changed


def apply_avito(path,retail):
    tree=ET.parse(path)
    root=tree.getroot()
    before_ids=[a.findtext("Id") for a in root.findall("Ad")]
    if len(before_ids)<100 or len(before_ids)!=len(set(before_ids)):
        raise ValueError("Unexpected Avito feed IDs")
    changed=[]
    for ad in root.findall("Ad"):
        k=extract_title_key(ad)
        item=retail.get(k) if k else None
        if not item or item["days"]!=0:
            continue
        old_el=ad.find("Price")
        if old_el is None or not old_el.text:
            raise ValueError("Missing Avito price")
        old=int(old_el.text)
        expected=progressive_price(item["source"])
        if old==item["avito"]:continue
        # Guard against unrelated manual price changes; allow small supplier drift.
        if abs(old-expected)/old>Decimal("0.1"):
            continue
        if abs(item["avito"]-old)/old>Decimal("0.4"):
            raise ValueError("More than 40% shift for Avito SKU")
        old_el.text=str(item["avito"])
        changed.append({"id":ad.findtext("Id"),"old":old,"new":item["avito"]})
    after_ids=[a.findtext("Id") for a in tree.getroot().findall("Ad")]
    if before_ids!=after_ids:
        raise ValueError("Avito ID changes prohibited")
    tree.write(path,encoding="utf-8",xml_declaration=True)
    return changed


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--retail-map",type=Path,required=True)
    p.add_argument("--drom",type=Path)
    p.add_argument("--avito",type=Path)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    if not args.drom and not args.avito:
        raise ValueError("No price files supplied")
    prices=read_retail_map(args.retail_map)
    changed_drom=apply_drom(args.drom,prices) if args.drom else []
    changed_avito=apply_avito(args.avito,prices) if args.avito else []
    args.report.parent.mkdir(parents=True,exist_ok=True)
    report={"retail_map_count":len(prices),
            "drom_repriced":len(changed_drom),"avito_repriced":len(changed_avito),
            "drom_examples":changed_drom[:10],"avito_examples":changed_avito[:10],
            "only_retail_data":True}
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("ROSSKO_RETAIL_OVERRIDE",json.dumps(report,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
