#!/usr/bin/env python3
"""Release-prep of TWO verified first-party LUZAR condenser ads; no implicit git writes.

Only manufacturer-backed exact articles LRAC3034 + LRAC3049; original
OEM+fitment+2 exact-product photos per SKU, pinned SHA256; ROSSKO API
fresh personal wholesale price and explicit Irkutsk stock. Preserves all
186 active + 195 approved historic ads and never changes prior metadata.
A separate GitHub Actions workflow uploads photos FIRST and verifies CDN
availability before publishing any XML, fail closed throughout.
"""
from __future__ import annotations
import argparse,csv,copy,hashlib,io,json,os,re,sys,urllib.robotparser
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
import requests
from bs4 import BeautifulSoup
from PIL import Image
from avito_active_feed_refresh import (
    supplier_products,add_raw_source_costs,read_wholesale_retail,key,price_decimal
)
from avito_irkutsk import load_fresh_price
from avito_pricing import progressive_price
from rossko_category_wholesale_export import audit_one
from rossko_wholesale_private_audit import rpc,zeep_client,choose_delivery,retry_transient
from update_prices import load_config

OWNER_REPO="ROJANGG/rossko-drom-lensk"
LIVE_BRANCH="avito-irkutsk-feed"
SPARE_PART_TYPE="Система охлаждения"
PHOTO_COLUMNS=("brand","article","supplier_price","supplier_delivery_days","drom_retail","avito_retail")

def stable_id(group,brand,article):
    return "irk-"+hashlib.sha256(
        f"{group}|{brand.casefold()}|{article.casefold()}".encode("utf-8")).hexdigest()[:22]

def validate_product_source(session,record,robot):
    page=record["manufacturer_page"]
    if not page.startswith("https://luzar.ru/") or not robot.can_fetch(session.headers["User-Agent"],page):
        raise ValueError("Manufacturer product source not allowed")
    r=session.get(page,timeout=(8,24))
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    text=soup.get_text(" ",strip=True)
    article=record["article"]
    if not re.search(article[:4]+r"\s*-?\s*"+article[4:],title,re.I):
        raise ValueError("Manufacturer article mismatch")
    p=text.find("OEM-номера")
    if p<0 or record["oem"] not in text[p:p+500]:
        raise ValueError("Original manufacturer OEM evidence changed")
    available=set()
    for tag in soup.find_all("img"):
        u=tag.get("src") or tag.get("data-src") or ""
        if u.startswith("https://cdn.carvilleshop.ru/upload/") and article.lower() in u.lower():
            available.add(u)
    for picture in record["images"][:2]:
        if picture["url"] not in available:
            raise ValueError("Pinned photo no longer on exact manufacturer product page")

def download_images(session,item,place):
    photos=[]
    for i,img in enumerate(item["images"][:2],1):
        url=img["url"]
        if (not url.startswith("https://cdn.carvilleshop.ru/upload/resize_1000/")
                or item["article"].lower() not in url.lower() or not url.lower().endswith(".jpg")):
            raise ValueError("Unexpected source for exact manufacturer photo")
        response=session.get(url,timeout=(8,25))
        response.raise_for_status()
        raw=response.content
        if not 7000 < len(raw) < 8_000_000 or raw[:3]!=b"\xff\xd8\xff":
            raise ValueError("Photo magic/size check failed")
        sha=hashlib.sha256(raw).hexdigest()
        if sha!=img["sha256"]:
            raise ValueError("Manufacturer photo bytes unexpectedly changed")
        pic=Image.open(io.BytesIO(raw));pic.load()
        if pic.format!="JPEG" or min(pic.size)<650:
            raise ValueError("Manufacturer image geometry unacceptable")
        filename=f"{stable_id(item['category'],item['brand'],item['article'])}-{sha[:12]}.jpg"
        (place/filename).write_bytes(raw)
        live=f"https://raw.githubusercontent.com/{OWNER_REPO}/{LIVE_BRANCH}/avito-images/{filename}"
        photos.append({"filename":filename,"sha256":sha,"public_url":live})
    if len({x["sha256"] for x in photos})!=2:
        raise ValueError("Manufacturer photos are duplicates")
    return photos

def build(config,live_xml,archive_xml,retail_csv,evidence,out):
    root=ET.parse(live_xml).getroot()
    historic=ET.parse(archive_xml).getroot()
    if root.attrib!=historic.attrib or root.tag!="Ads" or historic.tag!="Ads":
        raise ValueError("Avito XML structure mismatch")
    prev=root.findall("Ad");prior=historic.findall("Ad")
    if len(prev)!=186 or len(prior)!=195:
        raise ValueError("Unexpected starting live/approved SKU counts; no publication")
    ids={a.findtext("Id") for a in prev}
    old_ids=[a.findtext("Id") for a in prev]
    archive_ids={a.findtext("Id") for a in prior}
    if len(ids)!=186 or len(archive_ids)!=195 or not ids<=archive_ids:
        raise ValueError("Duplicate/unapproved existing Avito IDs")
    manifest=json.loads(evidence.read_text(encoding="utf-8"))
    records=manifest["items"]
    if (len(records)!=2 or {(r["brand"],r["article"]) for r in records}
            !={("Luzar","LRAC3034"),("Luzar","LRAC3049")}):
        raise ValueError("Refuse unreviewed extension")
    c=load_config(config)
    book=load_fresh_price(c,config.parent,2)
    try:
        products=supplier_products(book,c)
        add_raw_source_costs(book,products)
    finally:
        book.close()
    key1=(os.getenv("ROSSKO_API_KEY1") or "").strip()
    key2=(os.getenv("ROSSKO_API_KEY2") or "").strip()
    if not key1 or not key2:raise RuntimeError("Missing GitHub Actions API secrets")
    credentials={"KEY1":key1,"KEY2":key2}
    response=retry_transient(lambda:rpc(zeep_client("GetCheckoutDetails"),
            "GetCheckoutDetails",credentials),attempts=3,base_delay=1.3)
    delivery,mode=choose_delivery(response)
    if not delivery:raise RuntimeError("No account-approved pickup delivery")
    api=zeep_client("GetSearch")
    retail=read_wholesale_retail(retail_csv)
    out.mkdir(parents=True,exist_ok=True)
    photo_dir=out/"avito-images"
    photo_dir.mkdir(exist_ok=True)
    s=requests.Session()
    s.headers["User-Agent"]="RosskoAvitoOfficialLuzarCatalogRelease/1.0"
    robots=s.get("https://luzar.ru/robots.txt",timeout=(8,20))
    if robots.status_code!=200 or not robots.headers.get("Content-Type","").startswith("text/plain"):
        raise ValueError("Cannot confirm Luzar robots policy")
    robot=urllib.robotparser.RobotFileParser()
    robot.parse(robots.text.splitlines())
    added=[];photos=[]
    for record in records:
        k=key(record["brand"],record["article"])
        item=products.get(k)
        if item is None or item["Группа"]!="Радиаторы кондиционера":
            raise ValueError("Not in-stock Irkutsk 0-day manufacturer SKU")
        cost=price_decimal(item.get("_source_list_price"))
        if cost is None or cost<=0:
            raise ValueError("Invalid new supplier list price")
        a={
          "category":"Радиаторы кондиционера","brand":record["brand"],
          "article":record["article"],"description":record["vehicle"],
          "supplier_list_price_rub":str(cost),"supplier_stock":int(item["Остаток РОССКО"]),
          "supplier_delivery_days":0
        }
        quote=audit_one(api,credentials,delivery,a)
        if (quote.get("status")!="опт_Иркутск_подтвержден"
                or not quote.get("api_irkutsk_stock_ids")
                or quote.get("api_irkutsk_same_delivery_price_rub") in ("",None)):
            raise ValueError("No fresh API proof of exact Irkutsk SKU and personal wholesale cost")
        buying_price=price_decimal(quote["api_irkutsk_same_delivery_price_rub"])
        if buying_price is None or buying_price<=0 or buying_price>cost*Decimal("1.5"):
            raise ValueError("Personal purchasing cost untrusted")
        validate_product_source(s,record,robot)
        images=download_images(s,record,photo_dir)
        adid=stable_id(record["category"],record["brand"],record["article"])
        if adid in ids or adid in archive_ids or k in retail:
            raise ValueError("Would duplicate existing Avito ID/SKU")
        ad=ET.Element("Ad")
        values=(
          ("Id",adid),("Category","Запчасти и аксессуары"),
          ("GoodsType","Запчасти"),("AdType","Товар приобретен на продажу"),
          ("ProductType","Для автомобилей"),("SparePartType",SPARE_PART_TYPE),
          ("OEM",record["oem"]),
          ("Title",f"Радиатор кондиционера {record['brand']} {record['article']} новый"),
          ("Description",
             f"Новый радиатор кондиционера {record['brand']} {record['article']}. "
             f"Применимость: {record['vehicle']}. Оригинальный номер: {record['oem']}. "
             "Самовывоз: г. Иркутск, ул. Каховского, д. 11/1. "
             "Перед покупкой уточняйте наличие и совместимость по VIN."),
          ("Address","г. Иркутск, ул. Каховского, д. 11/1"),
          ("Price",str(progressive_price(buying_price))),
          ("Condition","Новое"),("Availability","В наличии"),
          ("Brand",record["brand"])
        )
        for name,value in values:
            ET.SubElement(ad,name).text=value
        images_field=ET.SubElement(ad,"Images")
        for picture in images:
            ET.SubElement(images_field,"Image",{"url":picture["public_url"]})
        root.append(copy.deepcopy(ad))
        historic.append(copy.deepcopy(ad))
        retail[k]={"supplier_price":cost,
                   "avito_price":progressive_price(buying_price),"days":0}
        photos+=images
        added.append({"id":adid,"brand":record["brand"],"article":record["article"],
                      "category":record["category"],"oem":record["oem"],
                      "manufacturer_page":record["manufacturer_page"],
                      "photo_files":[p["filename"] for p in images],
                      "public_price":progressive_price(buying_price),
                      "quantity":int(item["Остаток РОССКО"]),"delivery_days":0})
    if len(root.findall("Ad"))!=188 or len(historic.findall("Ad"))!=197:
        raise ValueError("Unexpected final feed or approved archive counts")
    if [x.findtext("Id") for x in root.findall("Ad")[:186]]!=old_ids:
        raise ValueError("Old ad IDs order or count changed")
    # Validate semantic identity for all 186 old ads.
    for old,new in zip(prev,root.findall("Ad")[:186]):
        if ET.tostring(old)!=ET.tostring(new):
            raise ValueError("Old ad XML unexpectedly altered")
    all_ids=[a.findtext("Id") for a in root.findall("Ad")]
    if len(set(all_ids))!=188:
        raise ValueError("Duplicate release IDs")
    ET.ElementTree(root).write(out/"AVITO_LIVE_WITH_LUZAR_TWO.xml",encoding="utf-8",xml_declaration=True)
    ET.ElementTree(historic).write(out/"AVITO_APPROVED_WITH_LUZAR_TWO.xml",encoding="utf-8",xml_declaration=True)
    with (out/"avito-verified-retail-prices.csv").open("w",newline="",encoding="utf-8-sig") as fp:
        fieldnames=list(PHOTO_COLUMNS)
        writer=csv.DictWriter(fp,fieldnames=fieldnames,delimiter=";")
        writer.writeheader()
        # Read existing original retail CSV unchanged and append only 2 new SKUs.
        with retail_csv.open("r",encoding="utf-8-sig",newline="") as inp:
            base=list(csv.DictReader(inp,delimiter=";"))
        writer.writerows(base)
        for info in added:
            k=key(info["brand"],info["article"]);r=retail[k]
            writer.writerow({"brand":info["brand"],"article":info["article"],
                             "supplier_price":str(r["supplier_price"]),
                             "supplier_delivery_days":0,"drom_retail":0,
                             "avito_retail":r["avito_price"]})
    report={
      "old_ad_count":186,"new_ad_count":188,"old_approved_count":195,
      "new_approved_count":197,"new_ids":[r["id"] for r in added],
      "new_items":added,"confirmed_api_price_and_irkutsk_stock":2,
      "photos_unique_verified":len(photos),
      "manufacturer_OEM_verified":2,
      "private_personal_purchase_prices_logged":False,
      "only_new_ad_fields_changed":True,
      "publisher_note":"Only two officially evidenced Luzar condensers, not all first95"
    }
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_LUZAR_TWO_RELEASE_PREPARED",json.dumps(report,ensure_ascii=False),flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",type=Path,required=True)
    p.add_argument("--live",type=Path,required=True)
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--retail",type=Path,required=True)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    build(args.config,args.live,args.archive,args.retail,args.evidence,args.output)
if __name__=="__main__":
    sys.exit(main())
