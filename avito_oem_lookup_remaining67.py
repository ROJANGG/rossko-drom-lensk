"""Read-only manufacturer OEM research for all 67 additional Avito candidates.

Never publishes listings and never turns aftermarket analogs into original OEM.
Verified page SKU and original vehicle maker are both mandatory for auto-confirmation.
"""
from __future__ import annotations

import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from update_prices import normalize_key

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "input/avito_remaining_67_NOT_READY_FOR_UPLOAD.csv"
OUT = ROOT / "output/avito_remaining67_oem_research"

# Original equipment VEHICLE manufacturers only; do not treat ATE/BOSCH/CTR as OEM.
CAR_MAKERS = {
    "VAG", "VW", "VOLKSWAGEN", "AUDI", "SKODA", "SEAT", "BMW", "MINI",
    "MERCEDES-BENZ", "MERCEDES BENZ", "MERCEDES", "SMART", "FORD", "VOLVO",
    "NISSAN", "INFINITI", "RENAULT", "RENAULT TRUCKS", "DACIA", "TOYOTA",
    "LEXUS", "HYUNDAI", "KIA", "HYUNDAI / KIA", "HONDA", "ACURA",
    "MITSUBISHI", "MAZDA", "SUBARU", "SUZUKI", "OPEL", "VAUXHALL",
    "GM", "GENERAL MOTORS", "CHEVROLET", "CITROEN", "PEUGEOT", "PSA",
    "FIAT", "LANCIA", "ALFA ROMEO", "LAND ROVER", "JAGUAR", "PORSCHE",
    "CHRYSLER", "DODGE", "JEEP", "SAAB", "LADA", "ВАЗ", "GAZ", "ГАЗ",
    "CHERY", "GEELY", "GREAT WALL", "HAVAL", "JETOUR", "BYD", "CHANGAN",
    "CHERY/JETOUR", "SSANGYONG", "ISUZU", "DAEWOO", "HOLDEN",
}
MAKER_PATTERN = "|".join(re.escape(x) for x in sorted(CAR_MAKERS, key=len, reverse=True))
ITEM_PATTERN = re.compile(r"(?<![A-Z0-9])([A-Z0-9][A-Z0-9 .\-/]{4,30}[A-Z0-9])(?=\s*$)", re.I)
FORWARD_PATTERN = re.compile(r"^(" + MAKER_PATTERN + r")\s+([A-Z0-9][A-Z0-9 .\-/]{4,32})$", re.I)
REVERSE_PATTERN = re.compile(r"^([A-Z0-9][A-Z0-9 .\-/]{4,32})\s+(" + MAKER_PATTERN + r")$", re.I)


def normalized_oem(value: str, own_part: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]", "", value.upper())
    if not 6 <= len(cleaned) <= 24 or sum(c.isdigit() for c in cleaned) < 4:
        return ""
    if cleaned == re.sub(r"[^A-Z0-9]", "", own_part.upper()):
        return ""
    return cleaned


def pairs_from_manufacturer_html(html: str, brand: str, article: str):
    soup = BeautifulSoup(html, "html.parser")
    for unwanted in soup(["script", "style", "noscript", "footer"]):
        unwanted.decompose()
    title = soup.find("h1")
    headline = title.get_text(" ", strip=True) if title else ""
    if brand == "NGN":
        # The supplier SKU omits hyphen, official NGN uses 36-1431.
        expected = article[:2] + "-" + article[2:]
        if not re.search(r"\bNGN\s+" + re.escape(expected) + r"\b", headline, re.I):
            return [], "article_mismatch"
    elif brand == "Marshall":
        page_text = soup.get_text(" ", strip=True)
        if not re.search(r"\bАртикул\s*:\s*" + re.escape(article) + r"\b", page_text, re.I):
            return [], "article_mismatch"
    else:
        return [], "unsupported_brand"
    snippets = list(soup.stripped_strings)
    if brand == "NGN":
        start = next((i+1 for i,v in enumerate(snippets) if v.strip().casefold()=="analogs"), None)
        if start is None:
            return [], "missing_analogs_section"
        last = next((i for i in range(start,len(snippets))
                     if snippets[i].strip().casefold() in ("model", "engine") or "Model  Engine" in snippets[i]),len(snippets))
    else:
        # Marshall OE numbers are after vehicle fitment and before recommendations.
        start = next((i for i,v in enumerate(snippets) if re.search(r"Артикул\s*:\s*"+re.escape(article),v,re.I)),0)
        last = next((i for i in range(start+1,len(snippets)) if snippets[i].strip().casefold()=="описание"),len(snippets))
    strings = snippets[start:last]
    found = []
    for i,value in enumerate(strings):
        s = re.sub(r"\s+", " ", value.strip())
        maker,code = None,None
        if i and s.upper() in CAR_MAKERS:
            maker,code=s.upper(),strings[i-1]
        elif i+1<len(strings) and strings[i+1].strip().upper() in CAR_MAKERS:
            maker,code=strings[i+1].strip().upper(),s
        else:
            m=FORWARD_PATTERN.fullmatch(s)
            if m:
                maker,code=m.group(1).upper(),m.group(2)
            else:
                m=REVERSE_PATTERN.fullmatch(s)
                if m:
                    maker,code=m.group(2).upper(),m.group(1)
        if maker and code:
            norm=normalized_oem(code,article)
            if norm and (maker,norm) not in found:
                found.append((maker,norm))
    return found[:80], "maker_labeled_cross_references" if found else "no_original_maker_pairs"


def manufacturer_url(brand: str, article: str) -> str:
    if brand=="NGN" and re.fullmatch(r"36\d{4}", article):
        return "https://ngn-parts.com/" + article[:2] + "-" + article[2:] + ".html"
    if brand=="Marshall" and re.fullmatch(r"M\d{7}", article):
        return "https://cars.marshall.parts/product/"+article.lower()+"/"
    return ""


def download(url):
    error = "not_requested"
    for attempt in range(2):
        try:
            r=requests.get(url,timeout=(6,18),headers={"User-Agent":"Mozilla/5.0 (compatible; OEM-cross-ref-review/1.0)"},allow_redirects=False)
            if r.status_code == 200 and len(r.content) > 500:
                return r.text,"http_200"
            error="http_"+str(r.status_code)
            if r.status_code in (404,410):
                break
        except requests.RequestException as exc:
            error=type(exc).__name__
        if attempt==0:
            time.sleep(0.5)
    return "",error


def lookup(row):
    brand,article = row["brand"],row["article"]
    source=manufacturer_url(brand,article)
    out={"brand":brand,"article":article,"proposed_original_oem":"",
         "oem_vehicle_brand":"","other_maker_oe_candidates":"",
         "source_url":source,"source_level":"manufacturer_exact_article" if source else "needs_separate_source",
         "lookup_status":"","publication_permission":"NO","note":""}
    if source:
        html,status=download(source)
        if html:
            pairs,reason=pairs_from_manufacturer_html(html,brand,article)
            out["lookup_status"]=reason
            if pairs:
                out["oem_vehicle_brand"],out["proposed_original_oem"]=pairs[0]
                out["other_maker_oe_candidates"]="|".join(f"{maker}:{code}" for maker,code in pairs[1:30])
                out["note"]="Manufacturer catalog OE/interchange table; review fitment, SKU and photo before Avito."
            else:
                out["note"]="No clear exact-SKU original vehicle-maker OEM on product page."
        else:
            out["lookup_status"]=status
    elif brand=="Master KiT" and article=="77R072":
        out.update(proposed_original_oem="MR554233",oem_vehicle_brand="MITSUBISHI",
                   source_url="https://hyperauto.ru/product/reyka-rulevaya-master-kit-art-77r072-300815889/",
                   source_level="retailer_cross_reference",lookup_status="needs_further_fitment_check",
                   note="Prior documented OEM interchange, must independently verify fitment.")
    elif brand=="Master KiT" and article=="77R097":
        out.update(proposed_original_oem="480014BA0A",oem_vehicle_brand="NISSAN",
                   source_url="https://baza.drom.ru/g16549459203.html",
                   source_level="supplier_interchange",lookup_status="needs_original_oe_confirmation",
                   note="ROSSKO part-interchange listing; correct Nissan OE also appears elsewhere.")
    elif brand=="Fenox" and article=="TB217657":
        out.update(proposed_original_oem="4351212270",oem_vehicle_brand="TOYOTA",
                   source_url="https://rossko.ru/card/fenox-tb217657-nsii0001425111/",
                   source_level="rossko_exact_item_oem_section",lookup_status="needs_source_recheck",
                   note="Supplier exact-item OEM section shows Toyota OE. Manual fitment confirmation still required.")
    else:
        out["lookup_status"]="unsupported_brand"
    return out


def main():
    with MANIFEST.open(encoding="utf-8-sig", newline="") as handle:
        items=list(csv.DictReader(handle,delimiter=";"))
    ids={(normalize_key(r["brand"]),normalize_key(r["article"])) for r in items}
    if len(items)!=67 or len(ids)!=67:
        raise ValueError("Expected 67 unique pinned supplier brand and article pairs")
    with ThreadPoolExecutor(max_workers=7) as executor:
        rows=list(executor.map(lookup,items))
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/"AVITO_REMAINING67_OEM_SOURCE_RESEARCH.csv").open("w",encoding="utf-8-sig",newline="") as file:
        writer=csv.DictWriter(file,delimiter=";",fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts={}
    for r in rows:
        counts[r["lookup_status"]]=counts.get(r["lookup_status"],0)+1
    summary={
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "candidates":len(rows),
        "manufacturer_exact_item_oem_found":sum(r["source_level"]=="manufacturer_exact_article" and bool(r["proposed_original_oem"]) for r in rows),
        "other_source_oem_candidates":sum(r["source_level"]!="manufacturer_exact_article" and bool(r["proposed_original_oem"]) for r in rows),
        "no_oem_recovered":sum(not r["proposed_original_oem"] for r in rows),
        "statuses":counts,
        "new_ads_published":0,
        "important":"Candidates are manufacturer/source cross references; fitment/photo/stock checks required before publication."
    }
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("AVITO_REMAINING67_OEM_RESEARCH",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
