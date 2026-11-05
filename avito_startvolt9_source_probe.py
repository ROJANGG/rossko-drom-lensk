#!/usr/bin/env python3
"""Direct official Startvolt exact-article source and product photo evidence.

Research only. No automatic release. Only publishes manifest for SKU
where manufacturer page + original OEM + genuine JPEG product photo have
all independently passed. Uses manufacturer-provided exact-SKU CDN photos.
"""
import io,json,re,hashlib,urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from PIL import Image

PRODUCTS=[
("GLSP003","1820A009","MITSUBISHI",
"https://startvolt.com/catalogue/svechi/svechi-nakalivaniya/svecha-nakalivaniya-dlya-avtomobiley-mitsubishi-l200-06-2-5d-glsp-003/"),
("GLSP010","A0011591701","MERCEDES-BENZ",
"https://startvolt.com/catalogue/svechi/svechi-nakalivaniya/svecha-nakalivaniya-dlya-avtomobiley-ssangyong-rexton-02-2-0td-glsp-010/"),
("GLSP014","19850-30010","TOYOTA",
"https://startvolt.com/catalogue/svechi/svechi-nakalivaniya/svecha-nakalivaniya-dlya-avtomobiley-toyota-land-cruiser-150-09-lc-prado-00-3-0td-glsp-014/"),
("GLSP022","1106500Q0C","NISSAN",
"https://startvolt.com/catalogue/svechi/svechi-nakalivaniya/renault/"), 
("GLSP026","4025139","FORD",
"https://startvolt.com/catalogue/detali-sistemy-zazhiganiya-i-nakalivaniya/svechi-nakalivaniya/svechi-nakalivaniya-/svecha-nakalivaniya-dlya-avtomobiley-ford-ranger-99-mazda-bt-50-06-2-5d-glsp-026/"),
("GLSP028","ME200970","MITSUBISHI",
"https://startvolt.com/catalogue/svechi/svechi-nakalivaniya/svecha-nakalivaniya-dlya-avtomobiley-mitsubishi-pajero-ii-94-2-8d-glsp-028/"),
("GLSP043","19850-54090","TOYOTA",
"https://startvolt.com/catalogue/detali-sistemy-zazhiganiya-i-nakalivaniya/svechi-nakalivaniya/svechi-nakalivaniya-/svecha-nakalivaniya-dlya-avtomobiley-toyota-land-cruiser-98-3-0d-4-2d-glsp-043/"),
("GLSP508","110654876R","RENAULT",
"https://startvolt.com/catalogue/detali-sistemy-zazhiganiya-i-nakalivaniya/svechi-nakalivaniya/komplekty-svechey-nakalivaniya/komplekt-svechey-nakalivaniya-4sht-dlya-avtomobiley-renault-duster-10-1-5dci-glsp-508/"),
("GLSP516","3770100-ED01","GREAT WALL",
"https://startvolt.com/catalogue/detali-sistemy-zazhiganiya-i-nakalivaniya/svechi-nakalivaniya/komplekty-svechey-nakalivaniya/komplekt-svechey-nakalivaniya-4sht-dlya-avtomobiley-great-wall-hover-h5-10-2-0d-glsp-516/"),
]
def canon(s):
    return re.sub(r"[^a-zA-Z0-9]","",s or "").upper()
def main():
    sess=requests.Session()
    sess.headers["User-Agent"]="RosskoAvitoManufacturerPhotoSourceAudit/1.0"
    out=Path("manufacturer_proof");out.mkdir(exist_ok=True)
    records=[]
    try:
        rr=sess.get("https://startvolt.com/robots.txt",timeout=(8,18))
        print("ROBOTS",rr.status_code,rr.headers.get("Content-Type",""),len(rr.content),flush=True)
        if rr.status_code not in (200,404):raise RuntimeError("Cannot confirm manufacturer's robots")
        robot=urllib.robotparser.RobotFileParser()
        robot.parse(rr.text.splitlines() if rr.status_code==200 else [])
    except Exception as e:
        print("ROBOTS_ERROR",type(e).__name__,flush=True)
        robot=None
    for article,oem,maker,url in PRODUCTS:
        result={"article":article,"OEM":oem,"original_maker":maker,
                "manufacturer_page":url,"manufacturer_confirmed":False,
                "OEM_confirmed":False,"photo_status":"","image_urls":[],
                "source_status":"NOT_RESEARCHED","requires_manual_review":True}
        if robot is None or not robot.can_fetch(sess.headers["User-Agent"],url):
            result["source_status"]="ROBOTS_NOT_VERIFIABLE"
            records.append(result)
            continue
        try:
            resp=sess.get(url,timeout=(8,24))
            result["http"]=resp.status_code
            resp.raise_for_status()
            soup=BeautifulSoup(resp.text,"html.parser")
            title=soup.title.get_text(" ",strip=True) if soup.title else ""
            txt=soup.get_text(" ",strip=True)
            result["manufacturer_confirmed"]=bool(re.search(
                r"\bGLSP[\s-]*"+re.escape(article[4:])+r"\b",title,re.I))
            at=txt.find("OEM номер")
            if at<0:at=txt.find("OEM НОМЕР")
            result["OEM_confirmed"]=(at>=0 and canon(oem) in canon(txt[at:at+650]))
            print("STARTVOLT_PAGE",article,resp.status_code,
                  "title_article",result["manufacturer_confirmed"],
                  "OE",result["OEM_confirmed"],"images",len(soup.find_all("img")),flush=True)
            if not result["manufacturer_confirmed"] or not result["OEM_confirmed"]:
                result["source_status"]="SKU_OR_OEM_NOT_ON_EXACT_MANUFACTURER_PAGE"
                records.append(result);continue
            urls=[]
            for img in soup.find_all("img"):
                candidate=urljoin(url,img.get("src") or img.get("data-src") or "")
                if candidate.startswith("https://cdn.carvilleshop.ru/upload/") and article.casefold() in candidate.casefold() and candidate.lower().endswith((".jpg",".jpeg")):
                    urls.append(candidate)
            urls=list(dict.fromkeys(urls))[:3]
            if not urls:
                print('STARTVOLT_RAW_ASSET_DIAG',article,json.dumps({
                    'images':[(im.get('src') or im.get('data-src') or '')[:180] for im in soup.find_all('img')[-12:]],
                    'jpg_paths':list(dict.fromkeys(re.findall(r'''(?:https?://[^\s"'<>]+|/[^\s"'<>]+)\.(?:jpg|jpeg|webp)''',resp.text,re.I)))[:8],
                    'photo_refs':[x[:140] for x in re.findall(r'''[^\n]{0,100}GLSP[\s_-]*'''+article[4:]+r'''[^\n]{0,140}''',resp.text,re.I)[:2]]
                },ensure_ascii=False),flush=True)
            if not urls:
                print('STARTVOLT_IMG_DIAG',article,json.dumps([
                    {'src':(im.get('src') or im.get('data-src') or '')[:210],
                     'alt':im.get('alt','')[:90]}
                    for im in soup.find_all('img')[:18]
                ],ensure_ascii=False),flush=True)
            for photo in urls:
                try:
                    rr=sess.get(photo,timeout=(8,22))
                    rr.raise_for_status()
                    blob=rr.content
                    if len(blob)<6000 or len(blob)>10_000_000 or blob[:3]!=b"\xff\xd8\xff":continue
                    image=Image.open(io.BytesIO(blob));image.load()
                    if image.format!="JPEG" or min(image.size)<400:continue
                    sha=hashlib.sha256(blob).hexdigest()
                    dest=f"{article}-{sha[:12]}.jpg"
                    (out/dest).write_bytes(blob)
                    result["image_urls"].append({"url":photo,"filename":dest,"sha256":sha,
                       "width":image.width,"height":image.height})
                except Exception as e:
                    result["photo_status"]="IMAGE_"+type(e).__name__
            result["photo_status"]="JPEG_EXACT_MANUFACTURER_SKU" if result["image_urls"] else "NO_VALID_PRODUCT_PHOTO"
            result["source_status"]="MANUFACTURER_SKU_OEM_IMAGE_EVIDENCE_CANDIDATE" if result["image_urls"] else "NO_VALID_PRODUCT_PHOTO"
        except Exception as e:
            result["source_status"]="HTTP_OR_PARSE_"+type(e).__name__
        records.append(result)
    (out/"manifest.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    stats={"total":len(records),"sku_oem_and_exact_images":sum(x["source_status"]=="MANUFACTURER_SKU_OEM_IMAGE_EVIDENCE_CANDIDATE" for x in records),
           "statuses":{str(s):sum(x["source_status"]==s for x in records) for s in set(x["source_status"] for x in records)},
           "for_review_only":True}
    print("STARTVOLT_9_SOURCE_EVIDENCE",json.dumps(stats,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
