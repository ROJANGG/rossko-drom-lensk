#!/usr/bin/env python3
"""Read-only exact-SKU manufacturer OEM and image evidence audit for 95 Avito candidates.

Manufacturer page must contain exact SKUs; image URLs must decode to actual
specific product imagery. This is a RESEARCH REPORT, not publish approval.
Captures provenance for original OEM/fitment/photos; never guesses missing data.
"""
import argparse,csv,io,json,re,time,hashlib
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urljoin,urlparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
from PIL import Image

HEAD={"User-Agent":"Mozilla/5.0 (compatible; CatalogReview/1.0)"}
PAGE_ROOTS={
 "STARTVOLT":"https://startvolt.com/catalogue/detali-sistemy-zazhiganiya-i-nakalivaniya/svechi-nakalivaniya/",
 "Luzar":"https://luzar.ru/catalogue/radiatory/radiatory-konditsionera-kondensery/",
}
FIELDS=("category","brand","article","manufacturer_page","manufacturer_exact_sku",
        "oem_raw_from_manufacturer","oem_source_scope","fitment_from_manufacturer",
        "candidate_photo_url","photo_status","photo_dimensions","photo_sha256",
        "evidence_status","manual_review_required")

def canon(value):
    return re.sub(r"[^A-Z0-9]","",str(value or "").upper())

def get_text(url):
    response=requests.get(url,headers=HEAD,timeout=(8,25))
    response.raise_for_status()
    if len(response.content)>4_000_000:raise ValueError("Oversize page")
    return response.text

def discover_pages(brand, sku):
    url=PAGE_ROOTS.get(brand)
    if not url:return []
    pages=[]
    try:
        soup=BeautifulSoup(get_text(url),"html.parser")
        for a in soup.find_all("a",href=True):
            href=urljoin(url,a["href"])
            snippet=a.get_text(" ",strip=True)
            parent=a.parent.get_text(" ",strip=True) if a.parent else ""
            if (canon(sku) in canon(snippet) or canon(sku) in canon(parent[:500])
                or canon(sku) in canon(href)) and href.startswith(urlparse(url).scheme+"://"+urlparse(url).netloc+"/"):
                if href!=url and href not in pages:pages.append(href)
            if len(pages)>=6:break
    except requests.RequestException:
        pass
    return pages

def inspect_photo(image_url, article):
    if not image_url.startswith("https://"):
        return "invalid_url","",""
    try:
        response=requests.get(image_url,headers={**HEAD,"Referer":urlparse(image_url).scheme+"://"+urlparse(image_url).netloc+"/"},
                              timeout=(8,20))
        response.raise_for_status()
        data=response.content
        if len(data)>5_000_000 or len(data)<2000:return "not_product_image","",""
        img=Image.open(io.BytesIO(data))
        w,h=img.size
        if w<250 or h<200 or img.format not in ("JPEG","PNG","WEBP"):
            return "not_usable_product_photo",f"{w}x{h}",""
        return "valid_image_unreviewed",f"{w}x{h}",hashlib.sha256(data).hexdigest()
    except Exception as e:
        return "image_error_"+type(e).__name__,"",""

def extract_page(url, brand,sku):
    soup=BeautifulSoup(get_text(url),"html.parser")
    title=soup.find("h1")
    title_text=title.get_text(" ",strip=True) if title else ""
    page=soup.get_text(" ",strip=True)
    # Only accept exact SKU from article labels / headings or product code cells.
    exact=(canon(sku) in canon(title_text) or
           any(canon(sku) in canon(s.get_text(" ",strip=True)[:80])
               for s in soup.find_all(string=re.compile(r"(?:Артикул|Код товара)",re.I))
               if s.parent and s.parent.parent))
    # Stronger: scope to its own product detail page, not a 100 item catalog
    is_listing=len(soup.find_all("a",href=True))>120
    if is_listing and canon(sku) not in canon(title_text):
        # May still be real product page with navigation, allow if exact item code
        pass
    meta=soup.find("meta",property="og:image")
    imgs=[]
    for img in soup.find_all("img"):
        src=img.get("data-src") or img.get("src") or ""
        alt=img.get("alt") or img.get("title") or ""
        if ("картинка номер" in alt.casefold() or
            "свеча накаливан" in alt.casefold() or
            "радиатор кондицион" in alt.casefold()):
            if canon(sku) in canon(alt) or canon(sku) in canon(page[:1500]):
                imgs.append(urljoin(url,src))
    if meta and meta.get("content"):imgs.append(urljoin(url,meta["content"]))
    imgs=list(dict.fromkeys(x for x in imgs if x.startswith("https://")))
    # Extract only OEM label from this exact manufacturer product detail.
    oem=""
    for node in soup.find_all(string=re.compile(r"^\s*(?:OEM.номера|OEM.номер|ОЕМ.номер|OEM номер|OEM-номера)\s*$",re.I)):
        parent=node.parent
        chunks=[]
        n=parent
        for i in range(5):
            n=n.find_next_sibling() if n else None
            if not n:break
            segment=n.get_text(" ",strip=True)
            if len(segment)>1400:break
            chunks.append(segment)
            if len(" ".join(chunks))>800:break
        if chunks:
            oem=" | ".join(chunks)[:900]
            break
    # Secondary exact-page parsing: product pages often give 'OEM номер' and
    # adjacent literal list before price, avoid lifting cross product page text.
    if not oem:
        txt=page
        matches=list(re.finditer(r"\b(?:OEM.?номера?|ОЕМ.?номера?)\b",txt,re.I))
        if len(matches)==1:
            tail=txt[matches[0].end():matches[0].end()+350]
            oem=re.split(r"(?:В наличии|В корзину|₽|Руб\.|Применяемость|Отзывы)",tail)[0].strip()
    fitment=""
    if title_text and exact:
        fitment=title_text[:220]
    photo_url=imgs[0] if imgs else ""
    photo_status,dimensions,digest=inspect_photo(photo_url,sku) if photo_url else ("not_found","","")
    return {"manufacturer_page":url,"manufacturer_exact_sku":exact,
            "oem_raw_from_manufacturer":oem if exact else "",
            "oem_source_scope":"manufacturer_product_detail_label_not_verified_OE_maker" if oem and exact else "",
            "fitment_from_manufacturer":fitment,
            "candidate_photo_url":photo_url,"photo_status":photo_status,
            "photo_dimensions":dimensions,"photo_sha256":digest}

def research(row):
    brand=row["brand"].strip()
    sku=row["article"].strip()
    rec={f:"" for f in FIELDS}
    for f in ("category","brand","article"):
        rec[f]=row[f]
    rec["evidence_status"]="NO_EXACT_MANUFACTURER_PAGE"
    rec["manual_review_required"]="YES"
    if brand not in PAGE_ROOTS:return rec
    pages=discover_pages(brand,sku)
    # Expected to include an exact code; never assume first URL is exact
    for page in pages[:4]:
        try:
            data=extract_page(page,brand,sku)
        except Exception:
            continue
        if not data["manufacturer_exact_sku"]:continue
        rec.update(data)
        rec["evidence_status"]=(
            "EXACT_MANUFACTURER_PAGE_OEM_AND_IMAGE_CANDIDATE"
            if data["oem_raw_from_manufacturer"] and data["photo_status"]=="valid_image_unreviewed"
            else "EXACT_MANUFACTURER_PAGE_NEEDS_EVIDENCE")
        break
    return rec

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    with open(args.source,encoding="utf-8-sig",newline="") as fp:
        records=list(csv.DictReader(fp,delimiter=";"))
    if len(records)!=95:raise ValueError("Expected exactly 95 approved review candidates")
    with ThreadPoolExecutor(max_workers=5) as executor:
        results=list(executor.map(research,records))
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    with (out/"MANUFACTURER_EVIDENCE_REVIEW_95.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=FIELDS,delimiter=";")
        writer.writeheader();writer.writerows(results)
    summary={"as_of_utc":datetime.now(timezone.utc).isoformat(),
             "checked":len(results),
             "status_counts":dict(Counter(x["evidence_status"] for x in results)),
             "manufacturer_exact_sku_pages":sum(str(x["manufacturer_exact_sku"])=="True" for x in results),
             "usable_image_candidates_not_yet_product_approved":sum(x["photo_status"]=="valid_image_unreviewed" for x in results),
             "OEM_candidates_not_yet_OE_verified":sum(bool(x["oem_raw_from_manufacturer"]) for x in results),
             "published":False}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_95_MANUFACTURER_EVIDENCE",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
