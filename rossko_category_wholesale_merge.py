#!/usr/bin/env python3
"""Merge category-only private API shard CSVs and summarize coverage.

Never interpret missing response/no warehouse as known wholesale prices.
"""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from rossko_category_wholesale_export import FIELDS

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--shard-count",type=int,required=True)
    args=parser.parse_args()
    paths=sorted(args.source.glob("**/category_wholesale_prices.csv"))
    meta_paths=sorted(args.source.glob("**/summary.json"))
    args.output.mkdir(parents=True,exist_ok=True)
    merged={}
    for path in paths:
        with path.open(encoding="utf-8-sig",newline="") as fp:
            rows=csv.DictReader(fp,delimiter=";")
            if set(FIELDS)-set(rows.fieldnames or []):
                raise ValueError("Incompatible private result columns")
            for r in rows:
                k=(r["brand"].casefold(),r["article"].casefold())
                if k in merged:
                    raise ValueError("Duplicate article in merged shard results")
                merged[k]=r
    metas=[json.loads(p.read_text(encoding="utf-8")) for p in meta_paths]
    expected=set(range(args.shard_count))
    observed={m["shard"] for m in metas}
    all_sizes={m["all_category_skus"] for m in metas}
    complete=(observed==expected and len(all_sizes)==1
              and sum(m["assigned"] for m in metas)==len(merged)
              and len(merged)==next(iter(all_sizes),None))
    rows=sorted(merged.values(),key=lambda r:(r["category"],r["brand"].casefold(),r["article"].casefold()))
    with (args.output/"WHOLESALE_DISCS_RACKS_ALL.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=FIELDS,delimiter=";")
        writer.writeheader()
        writer.writerows([{k:r.get(k,"") for k in FIELDS} for r in rows])
    counts=Counter(r["status"] for r in rows)
    cats=Counter(r["category"] for r in rows)
    confirmed=[r for r in rows if r["status"]=="опт_Иркутск_подтвержден"]
    summary={
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "scope":"supplier in-stock brake discs and steering racks, private only",
        "expected_shards":args.shard_count,"found_shards":len(observed),
        "complete_sku_scan":complete,
        "source_unique_brakes_racks":next(iter(all_sizes),None) if len(all_sizes)==1 else None,
        "rows_attempted":len(rows),
        "confirmed_irkutsk_wholesale_prices":len(confirmed),
        "not_confirmed":len(rows)-len(confirmed),
        "by_category":dict(cats),
        "confirmed_by_category":dict(Counter(r["category"] for r in confirmed)),
        "status_counts":dict(counts),
        "price_source":"ROSSLKO authorized API; exact brand+article and Irkutsk warehouse + same delivery days",
        "warning":"No price for unconfirmed SKU. Do not assume supplier list price has a fixed discount",
        "changed_live_drom":False,"changed_live_avito":False
    }
    (args.output/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ROSSKO_CATEGORY_WHOLESALE_SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if complete else 3
if __name__=="__main__":
    raise SystemExit(main())
