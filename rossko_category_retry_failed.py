"""Retry ONLY missing or failed ROSSKO wholesale SKU queries; keep valid private results.

Prior results are input from a private workflow artifact, NEVER checked into git.
We refuse merging if base supplier prices for previously verified SKUs changed.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from rossko_wholesale_private_audit import zeep_client, rpc, retry_transient, choose_delivery
from rossko_category_wholesale_export import supplier_rows, audit_one, FIELDS


def identity(row):
    from rossko_wholesale_private_audit import norm
    return norm(row["brand"])+"|"+norm(row["article"])


def targets_for_retry(source, baseline):
    current={identity(row):row for row in supplier_rows(source)}
    old={identity(row):row for row in baseline}
    if len(old)!=len(baseline):
        raise ValueError("Duplicate SKU key in private baseline")
    # Even one change in supplier price or days invalidates earlier comparison
    # when merging across two source XLSX snapshots.
    for k,v in old.items():
        if k not in current:
            raise ValueError("Supplier SKU disappeared; do not merge stale API data")
        src=current[k]
        if Decimal(str(src["supplier_list_price_rub"]))!=Decimal(str(v["supplier_list_price_rub"])) \
           or int(src["supplier_delivery_days"])!=int(v["supplier_delivery_days"]):
            raise ValueError("Supplier prices/delivery changed; cannot safely merge old snapshots")
    return current,old,[row for key,row in current.items()
                        if key not in old or old[key]["status"]!="опт_Иркутск_подтвержден"]


def fetch_retry_items(price,baseline_csv,shard_index,shard_count):
    with baseline_csv.open(encoding="utf-8-sig",newline="") as fp:
        rows=list(csv.DictReader(fp,delimiter=";"))
    src,prev,missing=targets_for_retry(price,rows)
    mine=[r for r in missing if int(hashlib.sha256(identity(r).encode()).hexdigest()[:12],16)%shard_count==shard_index]
    return len(src),len(missing),mine


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--price",type=Path,required=True)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--shard",type=int,required=True)
    p.add_argument("--shards",type=int,required=True)
    opt=p.parse_args()
    if opt.shards<1 or opt.shards>8 or not 0<=opt.shard<opt.shards:
        raise ValueError("Invalid shard")
    total,needed,mine=fetch_retry_items(opt.price,opt.baseline,opt.shard,opt.shards)
    if total<100 or total>5000 or needed<1 or needed>350:
        raise ValueError("Unsafe retry scope; expected 1-350 specific category SKUs")
    key1=os.getenv("ROSSKO_API_KEY1","").strip()
    key2=os.getenv("ROSSKO_API_KEY2","").strip()
    if not key1 or not key2:
        print("ROSSKO_RECHECK",json.dumps({"status":"missing_api_secrets","shard":opt.shard}))
        return 2
    creds={"KEY1":key1,"KEY2":key2}
    try:
        checkout=retry_transient(lambda: rpc(zeep_client("GetCheckoutDetails"),
            "GetCheckoutDetails",creds),attempts=4,base_delay=1.0)
        delivery,mode=choose_delivery(checkout)
        if not delivery:
            raise ValueError("No verified checkout delivery")
        client=zeep_client("GetSearch")
    except Exception as exc:
        print("ROSSKO_RECHECK",json.dumps({"status":"setup_failed",
              "error_class":type(exc).__name__,"shard":opt.shard}))
        return 2
    rows=[]
    for i,item in enumerate(mine):
        entry=audit_one(client,creds,delivery,item,sleeper=time.sleep)
        # Rate-limit friendly second attempt only when normal GET had transient
        # SSL / connection failure. Do not retry unknown SOAP or authorization faults.
        if entry["status"].startswith("сбой_API_"):
            time.sleep(1.5)
            second=audit_one(client,creds,delivery,item,sleeper=time.sleep)
            if not second["status"].startswith("сбой_API_"):
                entry=second
        rows.append(entry)
        if (i+1)%20==0:
            print("ROSSKO_RECHECK_PROGRESS",json.dumps({
                "shard":opt.shard,"queried":i+1,"shard_total":len(mine),
                "confirmed":sum(v["status"]=="опт_Иркутск_подтвержден" for v in rows)
            },ensure_ascii=False),flush=True)
        if i<len(mine)-1:
            time.sleep(0.8)
    opt.out.mkdir(parents=True,exist_ok=True)
    with (opt.out/"category_retry_prices.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,delimiter=";")
        w.writeheader()
        w.writerows([{col:r.get(col,"") for col in FIELDS} for r in rows])
    report={
        "run_checked_utc":datetime.now(timezone.utc).isoformat(),
        "total_category_source_items":total,"retry_candidates":needed,
        "shard":opt.shard,"shards":opt.shards,"assigned":len(mine),
        "retried":len(rows),
        "confirmed":sum(v["status"]=="опт_Иркутск_подтвержден" for v in rows),
        "states":dict(Counter(v["status"] for v in rows)),
        "published":False
    }
    (opt.out/"retry_summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("ROSSKO_RECHECK",json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if len(rows)==len(mine) else 3

if __name__=="__main__":
    sys.exit(main())
