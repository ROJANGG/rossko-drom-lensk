#!/usr/bin/env python3
"""READ ONLY: Personal ROSSKO prices for in-stock brake discs and steering racks.

ROSSLKO API KEY1/KEY2 are GitHub secrets, never saved or logged. Uses an
account-allowed fulfillment option and requires the API stock.description to
explicitly name Irkutsk. No guessing a fixed wholesale discount. The audit
never changes Avito or Drom XML/XLSX or commits price data to GitHub.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests
from openpyxl import load_workbook

from rossko_wholesale_private_audit import (
    zeep_client, rpc, norm, decimal, number, calculate_offer, choose_delivery,
    findnode, aslist, retry_transient,
)
from avito_pricing import progressive_price

EXCLUDED = re.compile(
    r"ремкомплект|ремкомпл|тяга|наконечник|пыльник|колодк|суппорт|"
    r"диск сцепления|втулк|болт|подшипник|щиток", re.I)
RACK = re.compile(r"^(?:рулев\w*\s+рейк\w*|рейк\w*\s+рулев\w*)\b", re.I)
DISC = re.compile(r"^(?:тормозн\w*\s+диск\w*|диск\w*\s+тормозн\w*)\b", re.I)

FIELDS = (
    "category","brand","article","description",
    "supplier_list_price_rub","supplier_stock","supplier_delivery_days",
    "api_irkutsk_stock_price_rub","api_irkutsk_zero_day_price_rub",
    "api_irkutsk_same_delivery_price_rub","wholesale_discount_percent",
    "api_irkutsk_stock_ids","api_irkutsk_warehouse_verified",
    "drom_preview_rub","avito_preview_rub",
    "status","api_result_time_utc"
)

def category(desc):
    s=re.sub(r"[-_/(),;]+"," ",str(desc or "").casefold()).strip()
    if EXCLUDED.search(s):
        return None
    if DISC.search(s):
        return "Тормозные диски"
    if RACK.search(s):
        return "Рулевые рейки"
    return None

def supplier_rows(path):
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        ws=wb.active
        idx={str(c.value or "").strip():i for i,c in enumerate(ws[1])}
        required=("Бренд","Артикул","Описание","Цена, руб.","Наличие","Срок поставки, дн.")
        missing=[x for x in required if x not in idx]
        if missing:
            raise ValueError("Missing source headers: "+",".join(missing))
        found={}
        for row in ws.iter_rows(min_row=2,values_only=True):
            def val(col):
                a=row[idx[col]]
                return str(a).strip() if a is not None else ""
            brand,article,description=val("Бренд"),val("Артикул"),val("Описание")
            group=category(description)
            if not group or not norm(brand) or not norm(article):
                continue
            list_price=decimal(val("Цена, руб."))
            stock=number(val("Наличие"),0)
            days=number(val("Срок поставки, дн."),-1)
            if list_price is None or list_price<=0 or stock<=0 or days<0:
                continue
            key=norm(brand)+"|"+norm(article)
            # Same source exporter logic: first valid unique brand+article entry.
            if key in found:
                continue
            found[key]={
                "category":group,"brand":brand,"article":article,
                "description":description[:500],
                "supplier_list_price_rub":str(list_price),
                "supplier_stock":stock,"supplier_delivery_days":days,
            }
        return [found[k] for k in sorted(found)]
    finally:
        wb.close()

def make_price_preview(cost):
    """Identical current sale-price policies, preview only."""
    from decimal import ROUND_CEILING
    d=decimal(cost)
    if d is None or d<=0:
        raise ValueError("Invalid verified API price")
    drom=(d*Decimal("1.37")/50).to_integral_value(rounding=ROUND_CEILING)*50
    return int(drom), progressive_price(d)

def audit_one(client,creds,delivery,item,sleeper=time.sleep):
    out={**item,"api_irkutsk_stock_price_rub":"",
         "api_irkutsk_zero_day_price_rub":"",
         "api_irkutsk_same_delivery_price_rub":"",
         "wholesale_discount_percent":"",
         "api_irkutsk_stock_ids":"",
         "api_irkutsk_warehouse_verified":"Нет",
         "drom_preview_rub":"","avito_preview_rub":"",
         "status":"not_checked",
         "api_result_time_utc":datetime.now(timezone.utc).isoformat()}
    params={**creds,"text":item["brand"]+" "+item["article"],**delivery}
    try:
        data=retry_transient(lambda: rpc(client,"GetSearch",params),attempts=2,
                             base_delay=0.7,sleep=sleeper)
        root=findnode(data,["PartsList"]) or findnode(data,["success"])
        if not isinstance(root,dict):
            out["status"]="api_no_structured_response"
            return out
        matches=[]
        for p in aslist((root.get("PartsList") or {}).get("Part")):
            if not isinstance(p,dict):
                continue
            partnumber=str(p.get("partnumber") or "").split("@")[0]
            if norm(p.get("brand"))==norm(item["brand"]) and norm(partnumber)==norm(item["article"]):
                matches.append(p)
        if not matches:
            out["status"]="exact_sku_not_found"
            return out
        stocks=[]
        for p in matches:
            for stock in aslist((p.get("stocks") or {}).get("stock")):
                if isinstance(stock,dict):
                    stocks.append(stock)
        price=calculate_offer(stocks,item["supplier_delivery_days"],
                              decimal(item["supplier_list_price_rub"]))
        out["api_irkutsk_warehouse_verified"]="Да" if price["city_verified"] else "Нет"
        out["api_irkutsk_stock_ids"]=",".join(price["stock_ids"])
        # min_irkutsk_zero explicitly verified by supplier stock description
        if price["min_irkutsk_zero"] is not None:
            out["api_irkutsk_zero_day_price_rub"]=str(price["min_irkutsk_zero"])
        if price["same"] is not None:
            source=decimal(item["supplier_list_price_rub"])
            cost=price["same"]
            out["api_irkutsk_stock_price_rub"]=str(cost)
            out["api_irkutsk_same_delivery_price_rub"]=str(cost)
            out["wholesale_discount_percent"]=str(
                ((source-cost)/source*100).quantize(Decimal("0.01")))
            drom,avito=make_price_preview(cost)
            out["drom_preview_rub"]=drom
            out["avito_preview_rub"]=avito
            out["status"]="опт_Иркутск_подтвержден"
        elif price["city_verified"]:
            out["status"]="Иркутск_есть_иной_срок"
        else:
            out["status"]="склад_Иркутск_не_подтвержден"
    except (requests.exceptions.RequestException, ConnectionError, TimeoutError) as exc:
        out["status"]="сбой_API_"+type(exc).__name__
    except Exception as exc:
        # Exception messages can disclose auth tokens; log only class name.
        out["status"]="ошибка_ответа_"+type(exc).__name__
    return out

def output_rows(output,rows,meta):
    output.mkdir(parents=True,exist_ok=True)
    with (output/"category_wholesale_prices.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=FIELDS,delimiter=";")
        writer.writeheader()
        writer.writerows([{x:r.get(x,"") for x in FIELDS} for r in rows])
    (output/"summary.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--price",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--shard-index",type=int,required=True)
    ap.add_argument("--shard-count",type=int,required=True)
    opts=ap.parse_args()
    if opts.shard_count<1 or opts.shard_count>12 or not 0<=opts.shard_index<opts.shard_count:
        raise ValueError("Invalid shards")
    items=supplier_rows(opts.price)
    if len(items)<100 or len(items)>5000:
        raise ValueError("Unexpected category SKU count. Refuse accidental bulk-API scan.")
    mine=[item for item in items if int(hashlib.sha256(
          (norm(item["brand"])+"|"+norm(item["article"])).encode()).hexdigest()[:12],16)
          %opts.shard_count==opts.shard_index]
    key1,key2=os.getenv("ROSSKO_API_KEY1","").strip(),os.getenv("ROSSKO_API_KEY2","").strip()
    if not key1 or not key2:
        print("ROSSKO_CATEGORY_API",json.dumps({"state":"missing_secrets","shard":opts.shard_index}),flush=True)
        return 2
    creds={"KEY1":key1,"KEY2":key2}
    # Abort any unsafe pricing if checkout method cannot be verified.
    try:
        details=retry_transient(lambda: rpc(zeep_client("GetCheckoutDetails"),
                 "GetCheckoutDetails",creds),attempts=3,base_delay=1.5)
        delivery,method=choose_delivery(details)
        if not delivery:
            print("ROSSKO_CATEGORY_API",json.dumps({"state":"no_authorized_delivery",
                "reason":method,"shard":opts.shard_index}),flush=True)
            return 2
        client=zeep_client("GetSearch")
    except Exception as exc:
        print("ROSSKO_CATEGORY_API",json.dumps({"state":"api_setup_unavailable",
           "shard":opts.shard_index,"error_class":type(exc).__name__}),flush=True)
        return 2
    rows=[]
    for i,item in enumerate(mine):
        rows.append(audit_one(client,creds,delivery,item))
        if (i+1)%30==0:
            print("ROSSKO_CATEGORY_PROGRESS",json.dumps({"shard":opts.shard_index,
                  "done":i+1,"assigned":len(mine),
                  "validated":sum(x["status"]=="опт_Иркутск_подтвержден" for x in rows)},ensure_ascii=False),flush=True)
        if i+1<len(mine):
            time.sleep(0.3)
    counts=Counter(x["status"] for x in rows)
    report={
        "source":"ROSSLKO main/input/rossko_price.xlsx on workflow commit",
        "scope":"only available brake discs and steering racks",
        "shard":opts.shard_index,"shard_count":opts.shard_count,
        "all_category_skus":len(items),"assigned":len(mine),
        "checked":len(rows),"categories":dict(Counter(x["category"] for x in rows)),
        "status_counts":dict(counts),
        "success_count":counts["опт_Иркутск_подтвержден"],
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "account_delivery":method,"published":False,
    }
    output_rows(opts.out,rows,report)
    print("ROSSKO_CATEGORY_API",json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if len(rows)==len(mine) else 3

if __name__=="__main__":
    sys.exit(main())
