#!/usr/bin/env python3
"""Exact manufacturer evidence for 13 individual Startvolt glow plugs (review).

Manufacturer page must have the exact GLSP SKU in title, an OEM field,
and a JPEG whose manufacturer CDN filename contains the same exact SKU.
No guessing OEM maker: manufacturer OEM number may include aftermarket
crossrefs; each number still requires OE maker vetting before publish.
No API costs, no publication, no unapproved SKU images.
"""
import hashlib,io,json,re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from collections import Counter
import requests
from bs4 import BeautifulSoup
from PIL import Image

SKUS=["GLSP003","GLSP010","GLSP014","GLSP015","GLSP022",
      "GLSP025","GLSP026","GLSP028","GLSP035","GLSP043",
      "GLSP048","GLSP058","GLSP066"]
ROOTS=[
 "https://startvolt.com/catalogue/detali-sistemy-zazhiganiya-i-nakalivaniya/svechi-nakalivaniya/",
 "https://startvolt.com/catalogue/svechi/svechi-nakalivaniya/renault/",
 "https://startvolt.com/catalogue/svechi/svechi-nakalivaniya/"
]
HEAD={"User-Agent":"RosskoAvitoManufacturerProductReview/1.0"}
def exact(sku,body):
  return bool(re.search(r"(?<![a-z0-9])"+re.escape(sku[:4])+r"[\s\-]*"+re.escape(sku[4:])+r"(?![a-z0-9])",body,re.I))
def original_oem_area(soup):
  nodes=soup.find_all(string=re.compile(r"OEM[\s-]*номер",re.I))
  texts=[]
  for node in nodes:
    ctx=node.parent.parent if node.parent and node.parent.parent else node.parent
    if ctx:
      texts.append(ctx.get_text(" ",strip=True)[:750])
  # On manufacturer page, contain all labeled OEM entries; flag manual
  # original-maker verification instead of accepting unknown crossrefs.
  return texts[:5]
def main():
  s=requests.Session();s.headers.update(HEAD)
  out=Path("manufacturer_items");out.mkdir(exist_ok=True)
  candidates={k:[] for k in SKUS}
  for root in ROOTS:
    for idx in range(1,5):
      url=root if idx==1 else root+("?PAGEN_1="+str(idx))
      try:
        r=s.get(url,timeout=(8,22))
        if r.status_code!=200:continue
        soup=BeautifulSoup(r.text,"html.parser")
        for a in soup.find_all("a",href=True):
          u=urljoin(url,a["href"])
          if (not u.startswith("https://startvolt.com/catalogue/")
               or not re.search(r"glsp[\-_]\d{3,}",u,re.I)):continue
          for sku in SKUS:
            if exact(sku,u) and u not in candidates[sku]:
              candidates[sku].append(u)
      except requests.RequestException:
        continue
    print("STARTVOLT_DISCOVERY_CHECKPOINT",root,{k:len(v) for k,v in candidates.items() if v},flush=True)
  rows=[]
  for sku in SKUS:
    row={"brand":"STARTVOLT","article":sku,"manufacturer_page":"","sku_exact":False,
         "OEM_excerpt":"","original_OE_maker_verified":False,
         "photo_files":[],"status":"NOT_FOUND"}
    for page in candidates[sku][:6]:
      try:
        r=s.get(page,timeout=(8,24))
        r.raise_for_status()
        soup=BeautifulSoup(r.text,"html.parser")
        title=(soup.title.get_text(" ",strip=True) if soup.title else "")
        if not exact(sku,title):continue
        row["manufacturer_page"]=page
        row["sku_exact"]=True
        oems=original_oem_area(soup)
        row["OEM_excerpt"]=" | ".join(oems)[:800]
        if not oems:
          row["status"]="MANUFACTURER_PAGE_WITHOUT_OEM"
          break
        photos=[]
        for img in soup.find_all("img"):
          url=urljoin(page,img.get("src") or img.get("data-src") or "")
          if (url.startswith("https://s3.carvilleshop.ru/upload/resize_1000/")
              and exact(sku,url) and url.lower().endswith((".jpg",".jpeg"))
              and url not in photos):
            photos.append(url)
        for url in photos[:2]:
          resp=s.get(url,timeout=(8,20));resp.raise_for_status()
          raw=resp.content
          if not 7000<len(raw)<10_000_000 or raw[:3]!=b"\xff\xd8\xff":continue
          im=Image.open(io.BytesIO(raw));im.load()
          if im.format!="JPEG" or min(im.size)<400:continue
          digest=hashlib.sha256(raw).hexdigest()
          filename=f"{sku}-{digest[:12]}.jpg"
          (out/filename).write_bytes(raw)
          row["photo_files"].append({"file":filename,"sha256":digest,"url":url,
                                      "size":list(im.size)})
        row["status"]="OEM_AND_REAL_SKU_IMAGE_CANDIDATE" if row["photo_files"] else "OEM_BUT_NO_USABLE_PHOTO"
        break
      except Exception as ex:
        row["status"]="SOURCE_ERROR_"+type(ex).__name__
    rows.append(row)
    print("STARTVOLT_EVIDENCE",sku,row["status"],len(row["photo_files"]),flush=True)
  (out/"manufacturer_evidence.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
  summary={"checked":len(rows),"statuses":dict(Counter(r["status"] for r in rows)),
           "real_images_not_yet_OE_original_verified":sum(r["status"]=="OEM_AND_REAL_SKU_IMAGE_CANDIDATE" for r in rows),
           "publish":False}
  (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
  print("STARTVOLT_13_EVIDENCE_SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=="__main__":
  main()
