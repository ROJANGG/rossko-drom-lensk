"""Private merging: old successfully verified prices + new targeted retry prices.

Never confuse unverified API transport failures with a valid wholesale price.
"""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from rossko_category_retry_failed import identity
from rossko_category_wholesale_export import FIELDS,supplier_rows

def read(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter=";"))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--price",type=Path,required=True)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--retry-root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--shards",type=int,default=4)
    args=p.parse_args()
    all_products=supplier_rows(args.price)
    baseline=read(args.baseline)
    retries=list(args.retry_root.glob("**/category_retry_prices.csv"))
    reports=list(args.retry_root.glob("**/retry_summary.json"))
    result={identity(x):x for x in baseline}
    if len(result)!=len(baseline):
        raise ValueError("Baseline contains duplicates")
    attempted=0
    successful=0
    for file in retries:
        for row in read(file):
            key=identity(row)
            if key not in result or result[key]["status"]!="опт_Иркутск_подтвержден":
                result[key]=row
            attempted+=1
            if row["status"]=="опт_Иркутск_подтвержден":
                successful+=1
    meta=[json.loads(p.read_text(encoding="utf-8")) for p in reports]
    complete=(
        len(meta)==args.shards and {m["shard"] for m in meta}==set(range(args.shards))
        and sum(m["assigned"] for m in meta)==attempted
        and len(result)==len(all_products)
        and all(identity(r) in result for r in all_products)
    )
    output=args.out
    output.mkdir(parents=True,exist_ok=True)
    rows=[result[identity(p)] for p in all_products if identity(p) in result]
    rows.sort(key=lambda r:(r["category"],r["brand"].casefold(),r["article"].casefold()))
    with (output/"WHOLESALE_DISCS_RACKS_RECHECKED.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,delimiter=";")
        w.writeheader()
        w.writerows([{k:x.get(k,"") for k in FIELDS} for x in rows])
    states=Counter(x["status"] for x in rows)
    report={
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "complete_source_sku_coverage":complete,
        "source_category_skus":len(all_products),
        "rows_reported":len(rows),
        "baseline_confirmed":sum(x["status"]=="опт_Иркутск_подтвержден" for x in baseline),
        "retry_attempts":attempted,"new_confirmed_attempts":successful,
        "confirmed_prices":states["опт_Иркутск_подтвержден"],
        "not_confirmed":len(rows)-states["опт_Иркутск_подтвержден"],
        "by_category":dict(Counter(x["category"] for x in rows)),
        "confirmed_by_category":dict(Counter(x["category"] for x in rows
                          if x["status"]=="опт_Иркутск_подтвержден")),
        "states":dict(states),
        "published_to_drom":False,
        "published_to_avito":False
    }
    (output/"SUMMARY.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ROSSKO_RECHECK_MERGED",json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if complete else 3

if __name__=="__main__":
    raise SystemExit(main())
