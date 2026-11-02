#!/usr/bin/env python3
"""Private, READ-ONLY ROSSKO wholesale API price validation.

GitHub Actions secrets only; never log auth values or raw SOAP payloads.
Checks 8 exact brand+SKU source-price lines, selects a valid checkout type,
and generates a PRIVATE artifact; never updates Drom/Avito files.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook
from zeep import Client, Settings
from zeep.exceptions import Fault, TransportError, ValidationError
from zeep.helpers import serialize_object
from zeep.transports import Transport
import requests

ROOT = "https://api.rossko.ru/service/v2.1"
CAT = {"brake_discs":3, "steering_racks":3, "other":2}
CSV_FIELDS = ("category", "brand", "article", "supplier_list_price_rub",
              "supplier_stock", "supplier_delivery_days",
              "api_search_success", "exact_match", "api_matched_part_count",
              "api_instock_offers", "api_lowest_instock_rub",
              "api_zero_day_lowest_rub", "api_matching_delivery_lowest_rub",
              "wholesale_vs_list_percent_for_matching_delivery",
              "api_price_is_lower_than_supplier_list", "status")


def aslist(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def norm(s):
    return re.sub(r"[^a-zа-я0-9]", "", str(s or "").casefold())


def decimal(value):
    try:
        return Decimal(str(value).replace(",", ".")) if value is not None else None
    except (InvalidOperation, ValueError):
        return None


def number(value, default=None):
    try:
        return int(float(str(value or "").replace(",", ".")))
    except (ValueError, TypeError, OverflowError):
        m = re.search(r"\d+", str(value))
        return int(m.group()) if m else default


def cat(description):
    t = (description or "").casefold()
    if re.search(r"\b(?:диск\s+тормозн\w*|тормозн\w*\s+диск\w*)\b",t):
        return "brake_discs"
    if re.search(r"\b(?:рейк\w*\s+рулев\w*|рулев\w*\s+рейк\w*)\b",t):
        return "steering_racks"
    return "other"


def select_examples(path):
    wb=load_workbook(path,read_only=True,data_only=True)
    ws=wb.active
    header={str(c.value or "").strip():i for i,c in enumerate(ws[1])}
    required=["Бренд","Артикул","Описание","Цена, руб.","Наличие","Срок поставки, дн."]
    if any(v not in header for v in required):
        raise ValueError("Source XLSX missing required columns")
    choices={k:[] for k in CAT}
    seen=set()
    for row in ws.iter_rows(min_row=2,values_only=True):
        def v(k):
            x=row[header[k]]
            return str(x).strip() if x is not None else ""
        brand,article,description=v("Бренд"),v("Артикул"),v("Описание")
        price=decimal(v("Цена, руб."))
        stock=number(v("Наличие"),0)
        days=number(v("Срок поставки, дн."),-1)
        identity=(norm(brand),norm(article))
        if not all(identity) or identity in seen or price is None or price<=0 or stock<=0 or days<0:
            continue
        seen.add(identity)
        group=cat(description)
        item={"category":group,"brand":brand,"article":article,
              "supplier_list_price_rub":str(price),
              "supplier_stock":stock,"supplier_delivery_days":days}
        choices[group].append(item)
    wb.close()
    rng=random.Random(981204)
    sample=[]
    for group,qty in CAT.items():
        pool=choices[group]
        if group=="brake_discs":
            pinned=[p for p in pool if norm(p["brand"])=="ngn" and norm(p["article"])=="361366"]
        else:
            pinned=[]
        chosen=pinned[:1]
        pool=[p for p in pool if p not in chosen]
        # Prefer local supplier items for apples-to-apples Avito zero-day prices.
        local=[p for p in pool if p["supplier_delivery_days"]==0]
        remote=[p for p in pool if p["supplier_delivery_days"]!=0]
        rng.shuffle(local)
        rng.shuffle(remote)
        chosen+=(local+remote)[:qty-len(chosen)]
        sample+=chosen
    return sample


def zeep_client(service):
    session=requests.Session()
    session.headers.update({"User-Agent":"RosskoWholesalePrivatePriceAudit/1.0"})
    return Client(
        wsdl=f"{ROOT}/{service}?wsdl",
        transport=Transport(session=session,timeout=25,operation_timeout=35),
        settings=Settings(strict=False,xml_huge_tree=False),
    )


def rpc(client,name,params):
    method=getattr(client.service,name)
    try:
        return serialize_object(method(**params),target_cls=dict)
    except (TypeError,ValidationError):
        # WSDL bindings sometimes require a single structured argument.
        return serialize_object(method(params),target_cls=dict)


def findnode(tree,required):
    if isinstance(tree,dict):
        if all(k in tree for k in required):
            return tree
        for val in tree.values():
            found=findnode(val,required)
            if found is not None:
                return found
    if isinstance(tree,list):
        for val in tree:
            found=findnode(val,required)
            if found is not None:
                return found
    return None


def choose_delivery(checkout):
    node=findnode(checkout,["DeliveryType"])
    if not node:
        return None,"checkout_response_missing_delivery_types"
    kinds=(node.get("DeliveryType") or {}).get("delivery")
    kinds=[x for x in aslist(kinds) if isinstance(x,dict)]
    pickup=[x for x in kinds if ("самовывоз" in str(x.get("name") or "").casefold()
                                 or "самовывоз" in str(x.get("id") or "").casefold())]
    if pickup:
        # Only codes returned by this user's checkout settings.
        return {"delivery_id":str(pickup[0]["id"])}, "account_pickup"
    addresses=(node.get("DeliveryAddress") or {}).get("address")
    for address in aslist(addresses):
        if not isinstance(address,dict) or "иркутск" not in str(address.get("city") or "").casefold():
            continue
        types=(address.get("Delivery") or {}).get("ids") or {}
        available=aslist(types.get("id"))
        acceptable={str(x.get("id")) for x in kinds}
        code=next((str(i) for i in available if str(i) in acceptable),None)
        if code:
            return {"delivery_id":code,"address_id":int(address["id"])},"irkutsk_delivery_address"
    return None,"no_approved_pickup_or_irkutsk_delivery_in_account"


def get_prices(client,credentials,delivery,items):
    rows=[]
    for product in items:
        row={**product, "api_search_success":"","exact_match":False,
             "api_matched_part_count":0,"api_instock_offers":0,
             "api_lowest_instock_rub":"","api_zero_day_lowest_rub":"",
             "api_matching_delivery_lowest_rub":"",
             "wholesale_vs_list_percent_for_matching_delivery":"",
             "api_price_is_lower_than_supplier_list":"","status":"not_checked"}
        try:
            query=f'{product["brand"]} {product["article"]}'
            data=rpc(client,"GetSearch",{**credentials,"text":query,**delivery})
            result=findnode(data,["PartsList"]) or findnode(data,["success"])
            if not result:
                row["status"]="api_no_structured_result"
                rows.append(row)
                continue
            row["api_search_success"]=str(result.get("success",result.get("Success","")))
            parts=(result.get("PartsList") or {}).get("Part",[])
            matches=[]
            for p in aslist(parts):
                if not isinstance(p,dict):
                    continue
                # Ignore vendor suffix @XXXX, NOT all analogs returned under crosses.
                exact_article=str(p.get("partnumber") or "").split("@")[0]
                if norm(p.get("brand"))==norm(product["brand"]) and norm(exact_article)==norm(product["article"]):
                    matches.append(p)
            row["exact_match"]=bool(matches)
            row["api_matched_part_count"]=len(matches)
            offers=[]
            for p in matches:
                for stock in aslist((p.get("stocks") or {}).get("stock")):
                    if not isinstance(stock,dict):
                        continue
                    cost=decimal(stock.get("price"))
                    qty=number(stock.get("count"),0)
                    days=number(stock.get("delivery"),None)
                    offer_type=number(stock.get("type"),None)
                    extra=number(stock.get("extra"),0)
                    if cost is None or cost<=0 or qty<=0 or days is None:
                        continue
                    # Only standard in-stock offers; skip damaged goods, extra warehouses.
                    if offer_type not in (0,1) or extra!=0:
                        continue
                    offers.append((cost,days))
            row["api_instock_offers"]=len(offers)
            if offers:
                best=min(p for p,d in offers)
                local=[p for p,d in offers if d==0]
                same=[p for p,d in offers if d==product["supplier_delivery_days"]]
                row["api_lowest_instock_rub"]=str(best)
                row["api_zero_day_lowest_rub"]=str(min(local)) if local else ""
                if same:
                    chosen=min(same)
                    row["api_matching_delivery_lowest_rub"]=str(chosen)
                    old=decimal(product["supplier_list_price_rub"])
                    row["wholesale_vs_list_percent_for_matching_delivery"]=str(
                        ((chosen-old)/old*100).quantize(Decimal("0.01")))
                    row["api_price_is_lower_than_supplier_list"]=chosen<old
                row["status"]="matched_offers" if same else "matched_but_delivery_differs"
            else:
                row["status"]="no_instock_exact_offers" if matches else "no_exact_brand_sku"
        except Exception as exc:
            # No exception messages! Some SOAP errors could contain auth-related data.
            row["status"]="api_error_"+type(exc).__name__
            rows.append(row)
            # Abort rather than consuming quota on repeated auth/network failures.
            break
        rows.append(row)
    return rows


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--price",required=True)
    ap.add_argument("--output",required=True)
    args=ap.parse_args()
    key1,key2=os.getenv("ROSSKO_API_KEY1","").strip(),os.getenv("ROSSKO_API_KEY2","").strip()
    if not key1 or not key2:
        print("ROSSKO_API_AUDIT",json.dumps({"status":"missing_github_secrets",
             "has_KEY1":bool(key1),"has_KEY2":bool(key2)}),flush=True)
        return 2
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=True)
    items=select_examples(Path(args.price))
    if len(items)!=sum(CAT.values()):
        print("ROSSKO_API_AUDIT",json.dumps({"status":"not_enough_source_items","sample_size":len(items)}))
        return 2
    creds={"KEY1":key1,"KEY2":key2}
    try:
        checkout=rpc(zeep_client("GetCheckoutDetails"),"GetCheckoutDetails",creds)
        delivery,method=choose_delivery(checkout)
    except Exception as exc:
        print("ROSSKO_API_AUDIT",json.dumps({"status":"checkout_api_error","error_class":type(exc).__name__}))
        return 2
    if not delivery:
        print("ROSSKO_API_AUDIT",json.dumps({"status":method}))
        return 2
    try:
        results=get_prices(zeep_client("GetSearch"),creds,delivery,items)
    except Exception as exc:
        print("ROSSKO_API_AUDIT",json.dumps({"status":"search_api_error","error_class":type(exc).__name__}))
        return 2
    with (output/"private_price_comparison.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=CSV_FIELDS,delimiter=";")
        writer.writeheader()
        for line in results:
            writer.writerow({name:line.get(name,"") for name in CSV_FIELDS})
    totals=Counter(x["status"] for x in results)
    lower=[x for x in results if x["api_price_is_lower_than_supplier_list"] is True]
    higher=[x for x in results if x["api_price_is_lower_than_supplier_list"] is False]
    report={"status":"completed","sample_count":len(items),"checked":len(results),
            "checkout_mode":method,"by_result":dict(totals),
            "api_cheaper_than_supplier_list_count":len(lower),
            "api_same_or_higher_than_supplier_list_count":len(higher),
            "relevant_matched_price_count":len(lower)+len(higher),
            "no_live_feed_changes":True,
            "checked_at_utc":datetime.now(timezone.utc).isoformat(),
            "important":"Checkout type verified for this account, but user's preferred fulfillment may differ"}
    (output/"private_summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("ROSSKO_API_AUDIT",json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if len(results)==len(items) and len(lower)+len(higher)>=1 else 3


if __name__=="__main__":
    sys.exit(main())
