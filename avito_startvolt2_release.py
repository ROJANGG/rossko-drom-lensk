#!/usr/bin/env python3
"""Prepare 2 source-proven STARTVOLT 4pc glow plug kits for live Avito release.

No commit or publication here. Source: manufacturer's exact-SKU pages and
SHA-pinned genuine photos, ROSSKO fresh 0-day price/stock + account-specific
API quote. Existing live/approved IDs and contents preserved exactly.
"""
import argparse,csv,hashlib,io,json,os,re,copy,time
from pathlib import Path
from xml.etree import ElementTree as ET
from decimal import Decimal
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from PIL import Image

from avito_irkutsk import load_fresh_price, zero_days
from avito_pricing import progressive_price
from update_prices import load_config,read_header_map,get_cell,text,parse_decimal,parse_stock_count,normalize_key
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import zeep_client,rpc,choose_delivery,retry_transient

EXPECTED={
  "GLSP508":{"oem":"110654876R","make":"RENAULT","fitment":"Renault Duster (с 2010 г.), 1.5 dCi; комплект из 4 свечей"},
  "GLSP516":{"oem":"3770100-ED01","make":"GREAT WALL","fitment":"Great Wall Hover H5 (с 2010 г.), 2.0D; комплект из 4 свечей"}
}
GROUP="Свечи накала"
REPO="ROJANGG/rossko-drom-lensk"
BRANCH="avito-irkutsk-feed"
PICTURES="https://cdn.jsdelivr.net/gh/"+REPO+"@"+BRANCH+"/avito-images/"

def stable_id(brand,article):
    return "irk-"+hashlib.sha256((GROUP+"|"+brand.casefold()+"|"+article.casefold()).encode()).hexdigest()[:22]

def canon(s):
    return re.sub(r"[^A-Z0-9]","",str(s or "").upper())

def inspect_manufacturer(s,product,img):
    page=product["manufacturer_page"]
    if not page.startswith("https://startvolt.com/"):
        raise ValueError("Unapproved manufacturer URL")
    response=s.get(page,timeout=(8,26));response.raise_for_status()
    soup=BeautifulSoup(response.text,"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    article=product["article"]
    if not re.search(r"GLSP[\s-]*"+article[4:]+r"\b",title,re.I):
        raise ValueError("Different manufacturer page article")
    plain=soup.get_text(" ",strip=True)
    at=plain.find("OEM номер")
    if at<0 or canon(product["OEM"]) not in canon(plain[at:at+650]):
        raise ValueError("Original OEM no longer on manufacturer page")
    official={
        tag.get("src") or tag.get("data-src")
        for tag in soup.find_all("img")
    }
    if img["url"] not in official:
        raise ValueError("Exact-SKU photo no longer part of manufacturer product page")

def run(config,live,archive,retail,evidence_folder,out):
    current=ET.parse(live).getroot()
    history=ET.parse(archive).getroot()
    if current.tag!="Ads" or history.tag!="Ads" or current.attrib!=history.attrib:
        raise ValueError("Wrong approved Avito feed")
    active=current.findall("Ad");hist=history.findall("Ad")
    if len(active)!=188 or len(hist)!=197:
        raise ValueError("Live or approved catalog changed; update plan before posting")
    original_xml=[ET.tostring(ad) for ad in active]
    oldids=[a.findtext("Id") for a in active]
    historicids=[a.findtext("Id") for a in hist]
    if not set(oldids)<=set(historicids) or len(set(oldids))!=188 or len(set(historicids))!=197:
        raise ValueError("Unapproved, duplicated or missing old IDs")
    manifest=json.loads((evidence_folder/"manifest.json").read_text())
    verified={x["article"]:x for x in manifest
              if x["article"] in EXPECTED and x.get("source_status")=="MANUFACTURER_SKU_OEM_IMAGE_EVIDENCE_CANDIDATE"}
    if set(verified)!=set(EXPECTED):
        raise ValueError("Both exact manufacturer OEM/photo sources are required")
    config_obj=load_config(config)
    book=load_fresh_price(config_obj,config.parent,2)
    found={}
    try:
        ws=book.active
        headers=read_header_map(ws)
        for row in ws.iter_rows(min_row=2):
            brand=text(get_cell(row,headers,"Бренд"))
            article=text(get_cell(row,headers,"Артикул"))
            if normalize_key(brand)!="startvolt" or article not in EXPECTED:
                continue
            if article in found:raise ValueError("Duplicate supplier source product")
            desc=text(get_cell(row,headers,"Описание"))
            price=parse_decimal(get_cell(row,headers,"Цена, руб."))
            rawstock=text(get_cell(row,headers,"Наличие"))
            stock=0 if rawstock.lstrip().startswith("-") else parse_stock_count(rawstock)
            if (price is None or price<=0 or stock<=0
                or not zero_days(get_cell(row,headers,"Срок поставки, дн."))
                or not re.search(r"(?:4\s*шт|4шт)",desc.casefold())
                or not re.search(r"(?:компл|кмпл)",desc.casefold())):
                continue
            found[article]={"brand":brand,"article":article,"description":desc,"price":price,"stock":stock}
    finally:
        book.close()
    if set(found)!=set(EXPECTED):
        raise ValueError("At least one exact 4pcs STARTVOLT SKU not in live ROSSKO 0-day stock")
    creds={"KEY1":(os.getenv("ROSSKO_API_KEY1") or "").strip(),
           "KEY2":(os.getenv("ROSSKO_API_KEY2") or "").strip()}
    if not all(creds.values()):raise RuntimeError("Missing ROSSKO API credentials in Actions secrets")
    checkout=retry_transient(lambda:rpc(zeep_client("GetCheckoutDetails"),
                              "GetCheckoutDetails",creds),attempts=3,base_delay=1.5)
    delivery,mode=choose_delivery(checkout)
    if not delivery:raise ValueError("No approved account pickup method")
    client=zeep_client("GetSearch")
    out.mkdir(parents=True,exist_ok=True)
    photosdir=out/"avito-images";photosdir.mkdir(exist_ok=True)
    session=requests.Session()
    session.headers["User-Agent"]="RosskoAvitoOfficialStartvoltKitRelease/1.0"
    additions=[]
    retailadd=[]
    for article,record in sorted(EXPECTED.items(),reverse=True):
        evidence=verified[article]
        images=evidence["image_urls"]
        if (evidence.get("manufacturer_confirmed")!=True
            or evidence.get("OEM_confirmed")!=True
            or evidence["OEM"]!=record["oem"]
            or evidence["original_maker"]!=record["make"]
            or len(images)!=1):
            raise ValueError("Manufacturer item OEM/photo evidence changed")
        item=found[article]
        payload={
            "brand":item["brand"],"article":article,"category":GROUP,
            "supplier_list_price_rub":str(item["price"]),
            "supplier_stock":item["stock"],"supplier_delivery_days":0
        }
        quote=None
        for attempt in range(3):
            quote=audit_one(client,creds,delivery,payload)
            if (quote["status"]=="опт_Иркутск_подтвержден"
                and quote.get("api_irkutsk_stock_ids")):
                break
            print("STARTVOLT_API_RETRY",article,quote.get("status","not_found"),
                  "attempt",attempt+1,flush=True)
            if attempt<2:
                time.sleep(2*(attempt+1))
                client=zeep_client("GetSearch")
        if (quote["status"]!="опт_Иркутск_подтвержден"
            or not quote.get("api_irkutsk_stock_ids")):
            raise ValueError("Personal API no verified Irkutsk price for "+article+
                             ": "+str(quote.get("status","unknown")))
        purchase=Decimal(quote["api_irkutsk_same_delivery_price_rub"])
        if purchase<=0 or purchase>item["price"]*2 or purchase<item["price"]/10:
            raise ValueError("Suspicious purchase price")
        img=images[0]
        filename=img["filename"]
        photo=evidence_folder/filename
        raw=photo.read_bytes()
        if len(raw)<6000 or hashlib.sha256(raw).hexdigest()!=img["sha256"] or raw[:3]!=b"\xff\xd8\xff":
            raise ValueError("Evidence photo checksum not verified")
        pic=Image.open(io.BytesIO(raw));pic.load()
        if pic.format!="JPEG" or min(pic.size)<500:
            raise ValueError("Unusable manufacturer product image")
        inspect_manufacturer(session,evidence,img)
        adid=stable_id(item["brand"],article)
        if adid in set(oldids)|set(historicids):raise ValueError("Duplicate approved Avito ID")
        target=f"{adid}-{img['sha256'][:12]}.jpg"
        (photosdir/target).write_bytes(raw)
        price=progressive_price(purchase)
        ad=ET.Element("Ad")
        fields=[
          ("Id",adid),("Category","Запчасти и аксессуары"),("GoodsType","Запчасти"),
          ("AdType","Товар приобретен на продажу"),("ProductType","Для автомобилей"),
          ("SparePartType","Электрооборудование"),
          ("OEM",record["oem"]),
          ("Title",f"Комплект свечей накаливания {item['brand']} {article} новый"),
          ("Description",f"Новый комплект из 4 свечей накаливания {item['brand']} {article}. "
            f"Применимость: {record['fitment']}. Оригинальный номер {record['make']}: {record['oem']}. "
            "Самовывоз: г. Иркутск, ул. Каховского, д. 11/1. "
            "Перед покупкой проверяйте совместимость по VIN."),
          ("Address","г. Иркутск, ул. Каховского, д. 11/1"),
          ("Price",str(price)),("Condition","Новое"),("Availability","В наличии"),
          ("Brand",item["brand"])
        ]
        for k,v in fields:ET.SubElement(ad,k).text=str(v)
        picnode=ET.SubElement(ad,"Images")
        ET.SubElement(picnode,"Image",{"url":PICTURES+target})
        current.append(copy.deepcopy(ad))
        history.append(copy.deepcopy(ad))
        retailadd.append({
            "brand":item["brand"],"article":article,
            "supplier_price":str(item["price"]),"supplier_delivery_days":0,
            "drom_retail":0,"avito_retail":price})
        additions.append({
            "article":article,"brand":item["brand"],"id":adid,
            "original_oem":record["oem"],"original_maker":record["make"],
            "source":evidence["manufacturer_page"],
            "image_file":target,"image_sha256":img["sha256"],
            "retail_price":price,"local_stock":item["stock"],
            "personal_api_source":mode
        })
    if len(current.findall("Ad"))!=190 or len(history.findall("Ad"))!=199:
        raise ValueError("Output size unexpected")
    if [ET.tostring(x) for x in current.findall("Ad")[:188]]!=original_xml:
        raise ValueError("Existing Avito ads changed")
    original_archive=[ET.tostring(x) for x in hist]
    if [ET.tostring(x) for x in history.findall("Ad")[:197]]!=original_archive:
        raise ValueError("Existing approved archive changed")
    ids=[a.findtext("Id") for a in current.findall("Ad")]
    if len(ids)!=len(set(ids)):
        raise ValueError("Repeated Avito ID")
    ET.ElementTree(current).write(out/"LIVE_WITH_STARTVOLT_TWO.xml",encoding="utf-8",xml_declaration=True)
    ET.ElementTree(history).write(out/"APPROVED_WITH_STARTVOLT_TWO.xml",encoding="utf-8",xml_declaration=True)
    with retail.open("r",encoding="utf-8-sig",newline="") as fp:
        original_rows=list(csv.DictReader(fp,delimiter=";"))
    prior={(normalize_key(x["brand"]),normalize_key(x["article"])) for x in original_rows}
    if len(prior)!=len(original_rows):
        raise ValueError("Duplicated retail entries")
    if any((normalize_key(x["brand"]),normalize_key(x["article"])) in prior for x in retailadd):
        raise ValueError("New STARTVOLT already exists in retail CSV")
    with (out/"avito-verified-retail-prices.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        columns=("brand","article","supplier_price","supplier_delivery_days","drom_retail","avito_retail")
        wr=csv.DictWriter(fp,fieldnames=columns,delimiter=";")
        wr.writeheader();wr.writerows(original_rows+retailadd)
    report={
        "before_live":188,"after_live":190,
        "before_approved":197,"after_approved":199,
        "new_items":additions,"new_count":2,
        "manufacturer_original_oem_verified":2,"exact_product_photos_sha_checked":2,
        "personal_irkutsk_api_prices_validated":2,
        "existing_ads_modified":0,"Drom_touched":False,
        "private_API_cost_persisted":False,
        "publish_ready":True}
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("STARTVOLT_RELEASE_TWO_PREFLIGHT",json.dumps(report,ensure_ascii=False),flush=True)

def main():
    p=argparse.ArgumentParser()
    for flag in ("config","live","archive","retail","evidence_folder","out"):
        p.add_argument("--"+flag.replace("_","-"),type=Path,required=True)
    args=p.parse_args()
    run(args.config,args.live,args.archive,args.retail,args.evidence_folder,args.out)
if __name__=="__main__":
    main()
