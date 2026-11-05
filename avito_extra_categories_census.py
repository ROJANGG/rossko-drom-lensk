#!/usr/bin/env python3
"""Inventory census for new Avito Irkutsk categories, read-only.

Fresh ROSSKO XLSX from configured HTTPS supplier, NO personal pricing, no
Avito publication. Priority patterns avoid common crossed categories.
Counts distinct manufacturer+article and only 0-day positive Irkutsk stock.
"""
from __future__ import annotations
import argparse,csv,json,re,collections
from datetime import datetime,timezone
from pathlib import Path

from avito_irkutsk import load_fresh_price, zero_days
from update_prices import load_config,read_header_map,get_cell,normalize_key,text,parse_stock_count,parse_decimal

GROUPS=[
("Насос ГУР", r"(?:насос\s+(?:гур|гидроусилител\w*)|насос\s+рулевого\s+управлени\w*|гидроусилител\w*\s+насос)"),
("Генератор",r"(?:генератор(?:\s|$)|генератор\s+в\s+сборе)"),
("Рычаги подвески",r"(?:рычаг(?:и|а|ов)?\s+(?:подвеск\w*|передн\w*|задн\w*|нижн\w*|верхн\w*)|рычаг\s+"),
("Тяги рулевые",r"(?:тяга\s+рулева\w*|рулева\w*\s+тяга|тяга\s+рулевого)"),
("Рулевые наконечники",r"(?:наконечник\w*\s+рулев\w*|наконечник\w*\s+тяги\s+рулев\w*|рулев\w*\s+наконечник\w*)"),
("Колодки тормозные (дисковые)",r"(?:колодк\w*\s+тормозн\w*|тормозн\w*\s+колодк\w*)"),
("Ремни приводные",r"(?:ремень\s+(?:поликлинов\w*|приводн\w*|генератора|навесн\w*|клинов\w*)|ремень\s+ручейков\w*|поликлинов\w*\s+ремень)"),
("Комплекты цепи ГРМ",r"(?:комплект\s+(?:цеп\w*\s+грм|грм\s+цеп\w*|цепн\w*\s+привода\s+грм)|ремкомплект\s+(?:грм|цеп\w*\s+грм)|набор\s+цеп\w*\s+грм|комплект\s+грм\s+с\s+цеп\w*)"),
("Ремни ГРМ",r"(?:ремень\s+грм|ремень\s+газораспределител\w*|зубчат\w*\s+ремень\s+грм)"),
("Прокладки ГБЦ",r"(?:прокладк\w*\s+(?:гбц|головк\w*\s+блок\w*)|прокладк\w*\s+под\s+головк\w*\s+блок\w*)"),
("Свечи накала",r"(?:свеча\s+накала|свечи\s+накала|свеч\w*\s+накал\w*)"),
("Радиаторы охлаждения",r"(?:радиатор\s+(?:охлажден\w*|двигател\w*|водян\w*|основн\w*)|радиатор\s+систем\w*\s+охлажден\w*)"),
("Радиаторы кондиционера",r"(?:радиатор\s+кондиционер\w*|конденсер\s+кондиционер\w*|конденсатор\s+кондиционер\w*|конденсор\s+кондиционер\w*)"),
("Радиаторы печки",r"(?:радиатор\s+(?:печк\w*|отопител\w*|салонн\w*)|радиатор\s+систем\w*\s+отоплен\w*)"),
("ШРУС",r"(?:шрус(?:\s|$)|шарнир\s+равн\w*\s+углов\w*\s+скорост\w*)"),
("Стойки стабилизатора",r"(?:стойк\w*\s+стабилизатор\w*|стабилизатор\w*\s+стойк\w*)"),
("Стойки амортизатора",r"(?:стойк\w*\s+амортизатор\w*|амортизационн\w*\s+стойк\w*|амортизатор\s+стойк\w*|стойк\w*\s+подвеск\w*)"),
("Пружины подвески",r"(?:пружин\w*\s+(?:подвеск\w*|передн\w*|задн\w*|амортизатор\w*)|пружин\w*\s+винтов\w*)"),
("Колодки барабанные",r"(?:колодк\w*\s+(?:барабан\w*|задн\w*\s+барабан\w*)|тормозн\w*\s+колодк\w*\s+барабан\w*)"),
("Опоры двигателя",r"(?:опор\w*\s+(?:двигател\w*|двс)|подушк\w*\s+(?:двигател\w*|двс)|опор\w*\s+силов\w*\s+агрегат\w*)"),
("Ступичные подшипники",r"(?:подшипник\w*\s+(?:ступиц\w*|колесн\w*)|ступичн\w*\s+подшипник\w*)"),
("Форсунки топливные",r"(?:форсунк\w*\s+(?:топливн\w*|впрыск\w*|дизельн\w*)|форсунк\w*\s+двигател\w*)"),
]
COMPILED=[(g,re.compile(p,re.I)) for g,p in GROUPS]
STOP_WORDS=re.compile(r"(?:датчик|кронштейн|сальник|ремкомплект|пыльник|втулка|шкив|крышка|прокладка\s+насос|щеткодержатель|реле\s+генератора)",re.I)

def classify(description):
    s=re.sub(r"[-_/(),;]+"," ",str(description or "").casefold()).strip()
    if not s:
        return None
    found=[g for g,regex in COMPILED if regex.search(s)]
    # Specific rules trump generic ones (drum vs discs, kit vs belt).
    if "Колодки барабанные" in found and "Колодки тормозные (дисковые)" in found:
        found.remove("Колодки тормозные (дисковые)")
    if "Комплекты цепи ГРМ" in found and "Ремни ГРМ" in found:
        found.remove("Ремни ГРМ")
    # An exact single category is required, so ambiguous names are not counted twice
    if len(found)!=1:
        return ("AMBIGUOUS",tuple(found)) if found else None
    name=found[0]
    if name=="Колодки тормозные (дисковые)" and re.search(r"барабан|ручн\w*\s+тормоз|стояночн\w*\s+тормоз",s):
        return ("AMBIGUOUS",("колодки барабанные или стояночные",))
    if name=="Рычаги подвески" and re.search(r"щетк\w*|рычаг\s+сцеплен|рычаг\s+короб|рычаг\s+кпп",s):
        return None
    if name=="Форсунки топливные" and re.search(r"омывател|водян|адблю|мочевин|a(?:d|d)blue",s):
        return None
    if name=="Генератор" and re.search(r"ремень|шкив|муфта|реле|щетк\w*|подшипник|креплен|диодн",s):
        return None
    if name=="Насос ГУР" and re.search(r"шкив|ремкомплект|бачок|реле|сальник",s):
        return None
    return name

def inventory(config_path, output):
    cfg=load_config(config_path)
    book=load_fresh_price(cfg,config_path.parent,2)
    try:
        ws=book.active
        headers=read_header_map(ws)
        keys=("Бренд","Артикул","Описание","Цена, руб.","Наличие","Срок поставки, дн.")
        if not set(keys)<=set(headers):raise ValueError("Missing source columns")
        city_cols=[c for c in ("Город склада","Склад отгрузки","Филиал","Город") if c in headers]
        stats={name:{"all_skus":set(),"positive_stock":set(),"irkutsk_zero_day":set(),"examples":[],"eligible":[]} for name,_ in GROUPS}
        ambiguous=collections.Counter()
        total=0
        for row in ws.iter_rows(min_row=2):
            total+=1
            raw=text(get_cell(row,headers,"Описание"))
            match=classify(raw)
            if match is None:continue
            if isinstance(match,tuple):
                ambiguous[str(match[1])]+=1
                continue
            group=match
            brand=text(get_cell(row,headers,"Бренд"))
            article=text(get_cell(row,headers,"Артикул"))
            k=normalize_key(brand)+"|"+normalize_key(article)
            if not normalize_key(brand) or not normalize_key(article):continue
            bucket=stats[group]
            bucket["all_skus"].add(k)
            if len(bucket["examples"])<8 and raw not in bucket["examples"]:
                bucket["examples"].append(raw[:180])
            stock_raw=text(get_cell(row,headers,"Наличие"))
            stock=0 if stock_raw.lstrip().startswith("-") else parse_stock_count(stock_raw)
            cost=parse_decimal(get_cell(row,headers,"Цена, руб."))
            if stock<=0 or cost is None or cost<=0:continue
            bucket["positive_stock"].add(k)
            if city_cols and not any("иркутск" in text(get_cell(row,headers,col)).casefold() for col in city_cols):
                continue
            if not zero_days(get_cell(row,headers,"Срок поставки, дн.")):
                continue
            if k in bucket["irkutsk_zero_day"]:continue
            bucket["irkutsk_zero_day"].add(k)
            bucket["eligible"].append({"category":group,"brand":brand,"article":article,
                                       "description":raw[:500],"supplier_stock":stock,
                                       "supplier_list_price_rub":str(cost),
                                       "source_days":0,
                                       "review_oem":"","review_photo":"","review_fitment":"",
                                       "review_api_cost":"","review_status":"NOT_APPROVED"})
    finally:
        book.close()
    summary=[]
    all_candidates=[]
    for group,_ in GROUPS:
        s=stats[group]
        summary.append({"category":group,"all_skus":len(s["all_skus"]),
                        "with_any_stock":len(s["positive_stock"]),
                        "irkutsk_zero_day":len(s["irkutsk_zero_day"]),
                        "sample_descriptions":s["examples"]})
        all_candidates.extend(s["eligible"])
    summary.sort(key=lambda x:(x["irkutsk_zero_day"],x["all_skus"]))
    output.mkdir(parents=True,exist_ok=True)
    with (output/"category_counts.csv").open("w",newline="",encoding="utf-8-sig") as fp:
        writer=csv.DictWriter(fp,fieldnames=("category","all_skus","with_any_stock","irkutsk_zero_day"),delimiter=";")
        writer.writeheader()
        for row in summary:
            writer.writerow({k:row[k] for k in writer.fieldnames})
    fields=("category","brand","article","description","supplier_stock",
            "supplier_list_price_rub","source_days","review_oem",
            "review_photo","review_fitment","review_api_cost","review_status")
    with (output/"candidates_NEVER_PUBLISH.csv").open("w",newline="",encoding="utf-8-sig") as fp:
        writer=csv.DictWriter(fp,fieldnames=fields,delimiter=";")
        writer.writeheader()
        writer.writerows(all_candidates)
    report={"checked_at_utc":datetime.now(timezone.utc).isoformat(),
            "source":"fresh ROSSKO HTTPS pricelist","source_rows":total,
            "city_columns":city_cols,
            "counts_sorted_smallest_first":summary,
            "candidates_total":len(all_candidates),
            "ambiguity_samples":dict(ambiguous.most_common(12)),
            "no_avito_publication":True}
    (output/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_CATEGORY_CENSUS",json.dumps({
        "source_rows":total,"city_columns":city_cols,
        "counts":[{k:v for k,v in t.items() if k!="sample_descriptions"} for t in summary],
        "ambiguous_rows":sum(ambiguous.values()),"no_publication":True},ensure_ascii=False),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--config",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    inventory(a.config,a.out)
