#!/usr/bin/env python3
"""Independently verify stock, exact SKU and personal API delivery for Startvolt.

No price values, API credentials or raw supplier records are written or logged.
Read-only diagnostic; no live feed or publication.
"""
import json,os,time
from pathlib import Path
from datetime import datetime,timezone
from update_prices import load_config,read_header_map,get_cell,text,normalize_key,parse_stock_count,parse_decimal
from avito_irkutsk import load_fresh_price,zero_days
from rossko_wholesale_private_audit import zeep_client,rpc,choose_delivery,retry_transient
from rossko_category_wholesale_export import audit_one

TARGET=("GLSP508","GLSP516")
def main():
  config_path=Path("code/config.json")
  c=load_config(config_path)
  book=load_fresh_price(c,config_path.parent,2)
  try:
    ws=book.active; h=read_header_map(ws); products={}
    for row in ws.iter_rows(min_row=2):
      brand=text(get_cell(row,h,"Бренд"));sku=text(get_cell(row,h,"Артикул"))
      if normalize_key(brand)!="startvolt" or sku not in TARGET:continue
      if sku in products:raise ValueError("Duplicate exact target SKU in source")
      rawstock=text(get_cell(row,h,"Наличие"))
      products[sku]={
        "brand":brand,"article":sku,
        "stock":0 if rawstock.lstrip().startswith("-") else parse_stock_count(rawstock),
        "list_price":parse_decimal(get_cell(row,h,"Цена, руб.")),
        "source_zero_days":zero_days(get_cell(row,h,"Срок поставки, дн.")),
        "description":text(get_cell(row,h,"Описание"))
      }
  finally:book.close()
  if set(products)!=set(TARGET):raise ValueError("SKU absent from supplier XLSX: "+str(set(TARGET)-set(products)))
  creds={x:(os.environ.get("ROSSKO_API_"+x) or "").strip() for x in ("KEY1","KEY2")}
  if not all(creds.values()):raise RuntimeError("Required ROSSKO secrets absent")
  checkout=retry_transient(lambda:rpc(zeep_client("GetCheckoutDetails"),
                          "GetCheckoutDetails",creds),attempts=3,base_delay=1.5)
  delivery,mode=choose_delivery(checkout)
  if not delivery:raise RuntimeError("No account delivery mode")
  client=zeep_client("GetSearch")
  statuses={}
  for sku in TARGET:
    item=products[sku]
    if item["stock"]<1 or not item["source_zero_days"] or item["list_price"] is None or item["list_price"]<=0:
      statuses[sku]={"supplier_available_zero_day":False,"personal_api_status":"NOT_CHECKED_SOURCE_NOT_ELIGIBLE"}
      continue
    payload={"category":"Свечи накала","brand":item["brand"],"article":sku,
             "supplier_list_price_rub":str(item["list_price"]),
             "supplier_stock":item["stock"],"supplier_delivery_days":0}
    statuses[sku]={"supplier_available_zero_day":True}
    for attempt in range(3):
      response=audit_one(client,creds,delivery,payload)
      status=response.get("status","API_NO_STATUS")
      statuses[sku]["personal_api_status"]=status
      statuses[sku]["api_exact_irkutsk_same_day_confirmed"]=(
        status=="опт_Иркутск_подтвержден" and bool(response.get("api_irkutsk_stock_ids"))
        and bool(response.get("api_irkutsk_same_delivery_price_rub")))
      print("STARTVOLT_API_STATUS",sku,status,"attempt",attempt+1,
            "confirmed",statuses[sku]["api_exact_irkutsk_same_day_confirmed"],flush=True)
      if statuses[sku]["api_exact_irkutsk_same_day_confirmed"]:break
      if attempt<2:time.sleep(2*(attempt+1))
  result={"checked_at_utc":datetime.now(timezone.utc).isoformat(),
          "results":statuses,"no_prices_disclosed":True,"no_live_publication":True}
  print("STARTVOLT_API_FINAL",json.dumps(result,ensure_ascii=False),flush=True)
  Path("status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__":main()
