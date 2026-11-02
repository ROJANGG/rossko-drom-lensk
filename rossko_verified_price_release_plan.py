#!/usr/bin/env python3
"""Safe, read-only application plan for confirmed ROSSKO retail prices.

Private API cost CSV never goes into repo; only proposed PUBLIC selling
prices and article keys are written. Exact brand+SKU, unchanged list price,
Irkutsk warehouse and positive stock, source delivery time, 6-hour API
freshness. XML IDs, images, OEMs, and product titles stay untouched.
No publication in this script. A separate reviewed release must commit.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from avito_pricing import progressive_price

def normalize(s):
    return re.sub(r"[^0-9a-zа-я]+","",str(s or "").casefold())

def price_float(s):
    try:
        return Decimal(str(s or "").replace(",",".")) 
    except Exception:
        return None

def parse_stock(s):
    try: return int(float(str(s).replace(",", ".")))
    except Exception: return 0

def roundup(value):
    return int((value/Decimal("50")).to_integral_value(rounding=ROUND_CEILING)*50)

def read_source(path):
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        ws=wb.active
        h={str(c.value or "").strip():idx for idx,c in enumerate(ws[1])}
        columns=("Бренд","Артикул","Цена, руб.","Наличие","Срок поставки, дн.")
        if not set(columns)<=set(h):
            raise ValueError("Supplier price columns missing")
        result={}
        for row in ws.iter_rows(min_row=2,values_only=True):
            def field(name):
                return row[h[name]]
            brand,article=field("Бренд"),field("Артикул")
            if not brand or not article:continue
            key=(normalize(brand),normalize(article))
            if key not in result:
                result[key]={"cost":price_float(field("Цена, руб.")),
                             "stock":parse_stock(field("Наличие")),
                             "days":int(field("Срок поставки, дн.") or 0)}
        return result
    finally:
        wb.close()

def read_confirmed(path,now):
    rows={}
    with path.open("r",encoding="utf-8-sig",newline="") as fp:
        reader=csv.DictReader(fp,delimiter=";")
        for r in reader:
            if r["status"]!="опт_Иркутск_подтвержден" or r["api_irkutsk_warehouse_verified"]!="Да":
                continue
            key=(normalize(r["brand"]),normalize(r["article"]))
            checked=datetime.fromisoformat(r["api_result_time_utc"])
            if checked.tzinfo is None or checked>now+timedelta(minutes=2) or now-checked>timedelta(hours=6):
                continue
            price=price_float(r["api_irkutsk_same_delivery_price_rub"])
            old=price_float(r["supplier_list_price_rub"])
            if not price or price<=0 or not old or old<=0 or not r["api_irkutsk_stock_ids"]:
                continue
            if key in rows:
                raise ValueError("Duplicate wholesale SKU in private audit")
            rows[key]={"brand":r["brand"],"article":r["article"],
                       "wholesale":price,"supplier_price":old,
                       "days":int(r["supplier_delivery_days"]),
                       "category":r["category"]}
    return rows

def make_map(rows,supplier):
    approved={}
    rejected=Counter()
    for key,r in rows.items():
        src=supplier.get(key)
        if src is None:
            rejected["not_in_fresh_supplier"]=rejected["not_in_fresh_supplier"]+1
        elif src["stock"]<=0:
            rejected["no_fresh_stock"]+=1
        elif src["days"]!=r["days"]:
            rejected["supplier_delivery_changed"]+=1
        elif src["cost"] is None or abs(src["cost"]-r["supplier_price"])>Decimal("0.01"):
            rejected["supplier_list_cost_changed"]+=1
        else:
            approved[key]={**r,"drom":roundup(r["wholesale"]*Decimal("1.37")),
                           "avito":progressive_price(r["wholesale"]),
                           "stock":src["stock"]}
    return approved,rejected

def extract_title_key(element):
    title=element.findtext("Title") or ""
    brand=element.findtext("Brand") or ""
    if not brand or not title:
        return None
    # Title format: "Тормозной диск BRAND ARTICLE новый"; manufacturer
    # can contain spaces. No fuzzy or cross-match on article.
    m=re.fullmatch(r"(?:Тормозной диск|Рулевая рейка)\s+(.+)\s+([A-Za-z0-9.+\-/]+)\s+новый",title,re.I)
    if not m or normalize(m.group(1))!=normalize(brand):
        return None
    return normalize(brand),normalize(m.group(2))

def patch_avito(original,approved):
    tree=ET.parse(original)
    root=tree.getroot()
    ads=root.findall("Ad")
    ids=[ad.findtext("Id") for ad in ads]
    if not ads or len(set(ids))!=len(ids):
        raise ValueError("Avito XML must have nonempty unique IDs")
    changes=[]
    recognized=0
    for ad in ads:
        key=extract_title_key(ad)
        if key is None or key not in approved:
            continue
        item=approved[key]
        if item["days"]!=0:
            continue
        if (ad.findtext("Availability") or "")!="В наличии":
            continue
        p=ad.find("Price")
        if p is None or not p.text:
            raise ValueError("Missing Avito price")
        old=int(p.text)
        new=item["avito"]
        if old==new:
            recognized+=1
            continue
        if abs(old-new)*100/old >40:
            raise ValueError("Avito excessive price change for ID: "+str(ad.findtext("Id")))
        # XML must represent either current or recently stale retail
        # price; manual price overrides are not clobbered.
        expected=progressive_price(item["supplier_price"])
        if abs(old-expected)*100/max(old,1)>10:
            continue
        p.text=str(new)
        changes.append({"id":ad.findtext("Id"),"brand":item["brand"],
                        "article":item["article"],"old":old,"new":new})
        recognized+=1
    return tree,changes,len(ads),recognized

def build_plan(wholesale_csv,source_xlsx,xml,output,max_age_hours=6):
    now=datetime.now(timezone.utc)
    private=read_confirmed(wholesale_csv,now)
    fresh=read_source(source_xlsx)
    approved,rejected=make_map(private,fresh)
    tree,changes,ads,recognized=patch_avito(xml,approved)
    output.mkdir(parents=True,exist_ok=True)
    retail=output/"CONFIRMED_RETAIL_PRICE_MAP.csv"
    fields=("brand","article","supplier_price","supplier_delivery_days",
            "drom_retail","avito_retail")
    with retail.open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=fields,delimiter=";")
        writer.writeheader()
        for key in sorted(approved):
            r=approved[key]
            writer.writerow({"brand":r["brand"],"article":r["article"],
                             "supplier_price":str(r["supplier_price"]),
                             "supplier_delivery_days":r["days"],
                             "drom_retail":r["drom"],"avito_retail":r["avito"]})
    tree.write(output/"AVITO_CONFIRMED_WHOLESALE_PRICES_REVIEW.xml",encoding="utf-8",xml_declaration=True)
    with (output/"AVITO_CONFIRMED_PRICE_DIFF.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=("id","brand","article","old","new"),delimiter=";")
        writer.writeheader()
        writer.writerows(changes)
    info={"created_at_utc":now.isoformat(),
          "private_confirmed_accepted_by_freshness":len(private),
          "approved_against_supplier":len(approved),
          "source_rejection":dict(rejected),
          "avito_ads":ads,"avito_matched_to_approved":recognized,
          "avito_repriced":len(changes),
          "drom_eligible_for_repricing":len(approved),
          "publication":False,
          "note":"Retail-only map has no private API cost, but retail prices are derived from personal costs"}
    (output/"summary.json").write_text(json.dumps(info,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ROSSKO_APPLY_CONFIRMED_PREFLIGHT",json.dumps(info,ensure_ascii=False),flush=True)
    return info

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--wholesale",type=Path,required=True)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--avito",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    info=build_plan(args.wholesale,args.source,args.avito,args.out)
    if info["approved_against_supplier"]<100 or info["avito_repriced"]<10:
        raise RuntimeError("Not enough verified supplier matches / Avito price changes; no release")
if __name__=="__main__":
    main()
