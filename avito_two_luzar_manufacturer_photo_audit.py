#!/usr/bin/env python3
"""Two exact first-party Luzar radiator product-photo preflight; private only.

Download original manufacturer's SKU-labeled photos from its public catalogue.
Validate source article, genuine vehicle OEM in manufacturer page, image magic,
dimensions and per-SKU separation. Does not publish Avito XML.
"""
from __future__ import annotations
import hashlib,io,json,re,sys,urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image,ImageOps,ImageDraw
from bs4 import BeautifulSoup

SOURCES=[
 {"brand":"Luzar","article":"LRAC3034","OEM":"F20-8105010",
  "compat":"JETOUR DASHING (2022+), 1.5T/1.6T; VIN check required",
  "page":"https://luzar.ru/catalogue/radiatory/radiatory-konditsionera-kondensery/radiator-konditsionera-dlya-avtomobiley-jetour-dashing-22-1-5t-1-6t-lrac-3034/"},
 {"brand":"Luzar","article":"LRAC3049","OEM":"S203F051209-0100",
  "compat":"CHANGAN UNI-T (2020+), 1.5T; VIN check required",
  "page":"https://luzar.ru/catalogue/radiatory/radiatory-konditsionera-kondensery/radiator-konditsionera-dlya-avtomobiley-changan-uni-t-20-lrac-3049/"}
]
def main():
    out=Path("photo_evidence")
    out.mkdir(exist_ok=True)
    s=requests.Session()
    s.headers["User-Agent"]="RosskoAvitoManufacturerPhotoSourceAudit/1.0"
    rr=s.get("https://luzar.ru/robots.txt",timeout=(8,20))
    if rr.status_code!=200 or not rr.headers.get("Content-Type","").startswith("text/plain"):
        raise ValueError("Manufacturer robots not readable")
    robot=urllib.robotparser.RobotFileParser()
    robot.parse(rr.text.splitlines())
    records=[]
    portraits=[]
    for item in SOURCES:
        if not robot.can_fetch(s.headers["User-Agent"],item["page"]):
            raise RuntimeError("Not allowed by manufacturer's robots.txt")
        r=s.get(item["page"],timeout=(8,28))
        r.raise_for_status()
        soup=BeautifulSoup(r.text,"html.parser")
        title=soup.title.get_text(" ",strip=True) if soup.title else ""
        txt=soup.get_text(" ",strip=True)
        if not re.search(item["article"][:4]+r"\s*-?\s*"+item["article"][4:],title,re.I):
            raise ValueError("Wrong manufacturer page")
        at=txt.find("OEM-номера")
        if at<0 or item["OEM"] not in txt[at:at+500]:
            raise ValueError("Manufacturer OEM not present for exact part")
        photos=[]
        for tag in soup.find_all("img"):
            u=urljoin(item["page"],tag.get("src") or tag.get("data-src") or "")
            if (u.startswith("https://cdn.carvilleshop.ru/upload/")
                    and item["article"].lower() in u.lower()
                    and u.lower().endswith((".jpg",".jpeg"))):
                photos.append(u)
        photos=list(dict.fromkeys(photos))[:4]
        if len(photos)<2:raise ValueError("Insufficient exact-SKU manufacturer photos")
        imgs=[]
        for i,url in enumerate(photos):
            resp=s.get(url,timeout=(8,25))
            resp.raise_for_status()
            raw=resp.content
            if len(raw)<6000 or len(raw)>12_000_000 or raw[:3]!=b"\xff\xd8\xff":
                raise ValueError("Downloaded file is not JPEG")
            image=Image.open(io.BytesIO(raw))
            image.load()
            if image.format!="JPEG" or min(image.size)<400:
                raise ValueError("Low-quality exact-SKU manufacturer image")
            filename=f"{item['article']}_{i+1}.jpg"
            (out/filename).write_bytes(raw)
            imgs.append({"filename":filename,"url":url,"sha256":hashlib.sha256(raw).hexdigest(),
                         "bytes":len(raw),"width":image.width,"height":image.height})
            thumb=ImageOps.contain(image.convert("RGB"),(400,290))
            portraits.append((item["article"]+" #"+str(i+1),thumb))
        records.append({**item,"source_title":title[:170],"images":imgs,
                        "OEM_confirmation":"manufacturer primary catalogue",
                        "image_confirmation":"manufacturer CDN filename exact SKU"})
    if len({i["sha256"] for rec in records for i in rec["images"]})!=sum(len(rec["images"]) for rec in records):
        raise ValueError("Duplicate/cross-SKU image hashes")
    print("VERIFIED_LUZAR_IMAGES",json.dumps([{k:r[k] for k in ("brand","article","OEM","compat","page")}|
           {"images":len(r["images"]),"image_files":r["images"]} for r in records],ensure_ascii=False),flush=True)
    (out/"manifest.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    cw=440;ch=360
    canvas=Image.new("RGB",(cw*2,ch*((len(portraits)+1)//2)),(246,248,250))
    dr=ImageDraw.Draw(canvas)
    for i,(label,im) in enumerate(portraits):
        x=(i%2)*cw;y=(i//2)*ch
        canvas.paste(im,(x+(cw-im.width)//2,y+5))
        dr.text((x+10,y+306),label,fill=(0,0,0))
    canvas.save(out/"contact_sheet.jpg",quality=87)
if __name__=="__main__":
    sys.exit(main())
