"""Read-only bounded SKU audit: supplier ROSSKO XLSX vs public Drom ROSSKOroznica search.

Checks ONLY a deterministic 48-item SKU sample. Does not infer that a missing
first-page search result means the seller never published the product.
Honors robots.txt, uses sequential requests with delay and stops on throttling.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
import urllib.parse
import urllib.robotparser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from rossko_vs_drom_audit import classify, header_records, norm, positive_price, stock_count

BASE="https://baza.drom.ru"
SELLER="/user/ROSSKOroznica/sell_spare_parts/"
FIELDS=("Бренд","Артикул","Описание","Категория","Поиск Дром","Предложений по запросу",
        "Найден точный бренд+артикул","Найден в Иркутске","Доказательства URL","Статус","Ошибка")


def sample_suppliers(price: Path, per_discs=16, per_racks=12, other=20):
    chosen={"Тормозные диски":[],"Рулевые рейки":[],"Прочее":[]}
    keys=set()
    for product in header_records(price,("Бренд","Артикул","Описание","Наличие","Цена, руб.")):
        brand,article,desc=product["Бренд"],product["Артикул"],product["Описание"]
        key=(norm(brand),norm(article))
        if not all(key) or key in keys:
            continue
        keys.add(key)
        if not desc or stock_count(product["Наличие"])<=0 or not positive_price(product["Цена, руб."]):
            continue
        group=classify(desc)
        chosen[group].append({"Бренд":brand,"Артикул":article,"Описание":desc,"Категория":group})
    rng=random.Random(531986)
    answer=[]
    for group,count in (("Тормозные диски",per_discs),("Рулевые рейки",per_racks),("Прочее",other)):
        products=chosen[group]
        answer.extend(rng.sample(products,min(count,len(products))))
    return answer,{k:len(v) for k,v in chosen.items()}


def extract_cards(html,article,brand):
    soup=BeautifulSoup(html,"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    raw_text=soup.get_text(" ",strip=True)
    totalmatch=re.search(r"(\d[\d \xa0]{0,14})\s+предложени(?:е|я|й)",raw_text,re.I)
    total=int(re.sub(r"[^0-9]","",totalmatch.group(1))) if totalmatch else None
    result=[]
    sku=norm(article)
    brand_norm=norm(brand)
    unique=set()
    # The seller's search may include substitute OEMs or competitor analogs;
    # count only the actual title containing brand AND exact article token.
    for a in soup.select("a[href]"):
        href=a.get("href","")
        if not re.search(r"/sell_spare_parts/.*?-g?\d{6,}\.html",href,re.I):
            continue
        link=urllib.parse.urljoin(BASE,href)
        if link in unique:
            continue
        unique.add(link)
        name=a.get_text(" ",strip=True)
        compact=norm(name)
        if not compact or not sku or sku not in compact or brand_norm not in compact:
            continue
        # Ensure query appears as a complete alphanumeric token, not a substring
        # e.g. article "12A" must not be inferred from title "012AB".
        if not re.search(r"(?<![a-zа-я0-9])"+re.escape(article)+r"(?![a-zа-я0-9])",name,re.I):
            # When a title joins maker and article without whitespace, require
            # a delimiter + exact article to avoid false positive.
            if not re.search(r"[\s/\[\](),;:-]"+re.escape(article)+r"(?![a-zа-я0-9])",name,re.I):
                continue
        result.append({"city":"Иркутск" if "/irkutsk/" in link.lower() else "иной город",
                       "url":link,"title":name[:240]})
    return total,title,result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--price",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--limit",type=int,default=48)
    args=ap.parse_args()
    if not 1<=args.limit<=48:
        raise ValueError("Sample limits must be in 1..48")
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    candidates,available=sample_suppliers(Path(args.price))
    candidates=candidates[:args.limit]
    session=requests.Session()
    headers={"User-Agent":"Mozilla/5.0 (compatible; CatalogResearch/1.0; read-only sampling)"}
    rp=urllib.robotparser.RobotFileParser()
    response=session.get(BASE+"/robots.txt",headers=headers,timeout=(7,15))
    response.raise_for_status()
    rp.parse(response.text.splitlines())
    rows=[]
    stopped=None
    for i,prod in enumerate(candidates):
        article,brand=prod["Артикул"],prod["Бренд"]
        url=BASE+SELLER+"?"+urllib.parse.urlencode({"query":article})
        if not rp.can_fetch(headers["User-Agent"],url):
            stopped="robots_disallow"
            break
        item={**prod,"Поиск Дром":url,"Предложений по запросу":"",
              "Найден точный бренд+артикул":"Нет подтверждения",
              "Найден в Иркутске":"Нет подтверждения","Доказательства URL":"",
              "Статус":"НЕ ПРОВЕРЕНО","Ошибка":""}
        try:
            response=session.get(url,headers=headers,timeout=(8,22),allow_redirects=False)
            if response.status_code in (429,403,503):
                stopped=f"restricted_http_{response.status_code}"
                item["Статус"]="ОГРАНИЧЕНИЕ ДРОМА"
                item["Ошибка"]=str(response.status_code)
                rows.append(item)
                break
            response.raise_for_status()
            if "/verify" in urllib.parse.urlsplit(response.url).path:
                stopped="Drom requires interactive verification"
                item["Статус"]="ДРОМ ТРЕБУЕТ ПРОВЕРКУ, НЕТ ДАННЫХ"
                item["Ошибка"]="redirected_to_verify"
                rows.append(item)
                break
            total,title,found=extract_cards(response.text,article,brand)
            item["Предложений по запросу"]=total if total is not None else ""
            item["Найден точный бренд+артикул"]="Да" if found else "Не найден на странице"
            irkutsk=[x for x in found if x["city"]=="Иркутск"]
            item["Найден в Иркутске"]="Да" if irkutsk else "Нет подтверждения"
            item["Доказательства URL"]=" | ".join(x["url"] for x in found[:3])
            item["Статус"]="ТОЧНОЕ СОВПАДЕНИЕ" if found else (
                "ПОИСК НОЛЬ" if total==0 else "НЕТ ТОЧНОГО СОВПАДЕНИЯ НА 1-Й СТРАНИЦЕ")
        except requests.RequestException as exc:
            item["Статус"]="ОШИБКА ДОСТУПА"
            item["Ошибка"]=type(exc).__name__
        rows.append(item)
        # Avoid hammering the merchant's high-volume search endpoint.
        if i<len(candidates)-1:
            time.sleep(1.0)

    with (out/"sample_rossko_vs_real_drom.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=FIELDS,delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    summary={"checked_utc":datetime.now(timezone.utc).isoformat(),
             "seller":BASE+SELLER,
             "scope":"48-item stratified sample of currently in-stock supplier SKUs",
             "supplier_eligible_by_category":available,
             "sample_size":len(candidates),"checked":len(rows),
             "stopped":stopped,
             "confirmed_listing_match":sum(x["Статус"]=="ТОЧНОЕ СОВПАДЕНИЕ" for x in rows),
             "confirmed_listing_in_irkutsk":sum(x["Найден в Иркутске"]=="Да" for x in rows),
             "search_zero":sum(x["Статус"]=="ПОИСК НОЛЬ" for x in rows),
             "unconfirmed_first_page":sum(x["Статус"]=="НЕТ ТОЧНОГО СОВПАДЕНИЯ НА 1-Й СТРАНИЦЕ" for x in rows),
             "by_status":dict(Counter(x["Статус"] for x in rows)),
             "not_found_means_unlisted":False,
             "complete_supplier_catalog_checked":False}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ROSSKO_PUBLIC_DROM_SAMPLE",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
