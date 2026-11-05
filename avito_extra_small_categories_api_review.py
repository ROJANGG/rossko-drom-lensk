#!/usr/bin/env python3
"""API verify only first 3 smallest populated new Avito categories.

Independent exact brand+SKU checks, confirmed ROSSKO Irkutsk stock descriptions,
personal buying prices, optional supplier photo hints, no inferred OEM, no
Avito XML or Drom modifications. API credentials are only GitHub Secrets.
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
from pathlib import Path

from avito_extra_categories_census import classify
from avito_irkutsk import load_fresh_price,zero_days
from update_prices import (
    load_config, get_cell, read_header_map, normalize_key, read_photo_map,
    text, parse_stock_count, parse_decimal,
)
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import rpc,zeep_client,choose_delivery,retry_transient

TARGETS=("Колодки барабанные","Радиаторы кондиционера","Свечи накала")
FIELDS=("category","brand","article","description","supplier_stock",
        "supplier_list_price_rub","supplier_delivery_days",
        "api_wholesale_price_rub","avito_calculated_retail_rub",
        "api_stock_ids","api_status","photo_hint_unverified",
        "manufacturer_oem_verified","compatibility_verified","photo_verified",
        "READY_FOR_AVITO_PUBLICATION")

def collect(config_path):
    config=load_config(config_path)
    wsbook=load_fresh_price(config,config_path.parent,2)
    try:
        ws=wsbook.active
        h=read_header_map(ws)
        for col in ("Бренд","Артикул","Описание","Цена, руб.","Наличие","Срок поставки, дн."):
            if col not in h:
                raise ValueError("Missing fresh ROSSKO source column")
        cities=[c for c in ("Город склада","Склад отгрузки","Филиал","Город") if c in h]
        result={}
        for row in ws.iter_rows(min_row=2):
            desc=text(get_cell(row,h,"Описание"))
            group=classify(desc)
            if group not in TARGETS:
                continue
            brand=text(get_cell(row,h,"Бренд"))
            article=text(get_cell(row,h,"Артикул"))
            k=(normalize_key(brand),normalize_key(article))
            if not all(k) or k in result:
                continue
            if cities and not any("иркутск" in text(get_cell(row,h,c)).casefold() for c in cities):
                continue
            if not zero_days(get_cell(row,h,"Срок поставки, дн.")):
                continue
            rawstock=text(get_cell(row,h,"Наличие"))
            stock=0 if rawstock.lstrip().startswith("-") else parse_stock_count(rawstock)
            price=parse_decimal(get_cell(row,h,"Цена, руб."))
            if stock<=0 or price is None or price<=0:
                continue
            result[k]={"category":group,"brand":brand,"article":article,
                "description":desc[:450],"supplier_stock":stock,
                "supplier_list_price_rub":str(price),"supplier_delivery_days":0}
    finally:
        wsbook.close()
    if not 60 <= len(result) <= 130:
        raise ValueError("Unexpected first-three category count; refuse unexpected API usage")
    return config,result


def run(config_path,output):
    config,products=collect(config_path)
    key1,key2=(os.getenv("ROSSKO_API_KEY1") or "").strip(),(
        os.getenv("ROSSKO_API_KEY2") or "").strip()
    if not key1 or not key2:
        raise RuntimeError("Required ROSSKO API Github Secrets missing")
    credentials={"KEY1":key1,"KEY2":key2}
    # Identify a valid delivery mode for this account. Never guess ID.
    checkout=retry_transient(lambda: rpc(zeep_client("GetCheckoutDetails"),
        "GetCheckoutDetails",credentials),attempts=3,base_delay=1.3)
    delivery,method=choose_delivery(checkout)
    if not delivery:
        raise RuntimeError("No account-approved checkout delivery type")
    client=zeep_client("GetSearch")
    supplier_photos=read_photo_map(config_path.parent/str(
        config.get("drom",{}).get("photo_map_path","input/photos.csv")))
    rows=[]
    counter=Counter()
    for i,(k,p) in enumerate(sorted(products.items(),key=lambda x:
                              (TARGETS.index(x[1]["category"]),x[1]["brand"],x[1]["article"]))):
        result=audit_one(client,credentials,delivery,p)
        good=result["status"]=="опт_Иркутск_подтвержден"
        # A URL in the supplier photo map is NOT considered a photo verification.
        row={**p,
            "api_wholesale_price_rub":result.get("api_irkutsk_same_delivery_price_rub","") if good else "",
            "avito_calculated_retail_rub":result.get("avito_preview_rub","") if good else "",
            "api_stock_ids":result.get("api_irkutsk_stock_ids","") if good else "",
            "api_status":result["status"],
            "photo_hint_unverified":supplier_photos.get("|".join(k),""),
            "manufacturer_oem_verified":"",
            "compatibility_verified":"",
            "photo_verified":"",
            "READY_FOR_AVITO_PUBLICATION":"NO",
        }
        if good and not row["api_stock_ids"]:
            raise ValueError("Irkutsk warehouse IDs not explicitly evidenced")
        rows.append(row)
        counter[(p["category"],result["status"])]+=1
        if (i+1)%20==0:
            print("AVITO_NEW_CATEGORIES_PILOT_PROGRESS",json.dumps({
                "checked":i+1,"target":len(products),
                "confirmed_irkutsk":sum(v for (g,status),v in counter.items()
                    if status=="опт_Иркутск_подтвержден")},ensure_ascii=False),flush=True)
        if i+1<len(products):
            time.sleep(0.4)
    output.mkdir(parents=True,exist_ok=True)
    with (output/"FIRST_3_CATEGORIES_PERSONAL_PRICE_AND_OEM_PHOTO_REVIEW.csv").open(
            "w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=FIELDS,delimiter=";")
        writer.writeheader()
        writer.writerows([{f:r.get(f,"") for f in FIELDS} for r in rows])
    report={
        "as_of_utc":datetime.now(timezone.utc).isoformat(),
        "target_categories":list(TARGETS),
        "candidate_count":len(rows),
        "confirmed_irkutsk_api":sum(r["api_status"]=="опт_Иркутск_подтвержден" for r in rows),
        "confirmed_by_category":dict(Counter(r["category"] for r in rows
                    if r["api_status"]=="опт_Иркутск_подтвержден")),
        "candidates_by_category":dict(Counter(r["category"] for r in rows)),
        "photo_hints_unverified":sum(bool(r["photo_hint_unverified"]) for r in rows),
        "actual_manufacturer_oem_confirmed":0,
        "actual_photos_confirmed":0,
        "publishable_avito_ads":0,
        "run_kind":"PRIVATE REVIEW, NEVER PUBLICATION",
        "api_checkout_mode":method,
        "nonconfirmations":dict(Counter(r["api_status"] for r in rows
                              if r["api_status"]!="опт_Иркутск_подтвержден"))
    }
    (output/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                                          encoding="utf-8")
    print("AVITO_NEW_CATEGORIES_PILOT_AUDIT",json.dumps(report,ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    opts=parser.parse_args()
    sys.exit(run(opts.config,opts.out))
