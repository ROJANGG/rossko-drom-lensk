"""Read-only visual QA contact sheet for 16 hinted supplier images.

All inputs are exact URL hints from the private API-reviewed shortlist;
no web scraping/discovery, no publication to Avito or Github branches.
"""
import argparse,csv,hashlib,io,json,time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image,ImageOps,ImageDraw,ImageFont

FIELDS=("category","brand","article","photo_url_hint","status",
        "pixel_width","pixel_height","bytes","sha256")
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--candidate-csv",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    with args.candidate_csv.open(encoding="utf-8-sig",newline="") as fp:
        items=[r for r in csv.DictReader(fp,delimiter=";") if r.get("photo_hint_unverified")]
    if not 1<=len(items)<=25: raise ValueError("Unexpected supplier hint count")
    args.out.mkdir(parents=True,exist_ok=True)
    out=[]
    previews=[]
    session=requests.Session()
    session.headers["User-Agent"]="RosskoStockPhotoAccuracyReview/1.0"
    for r in items:
        url=r["photo_hint_unverified"]
        parsed=urlparse(url)
        if parsed.scheme!="https" or parsed.netloc!="imgs.rossko.ru" or "/NSI" not in parsed.path:
            raise ValueError("Unexpected image source; refuse untrusted host")
        rec={"category":r["category"],"brand":r["brand"],"article":r["article"],
             "photo_url_hint":url,"status":"FETCH_FAILED","pixel_width":"",
             "pixel_height":"","bytes":"","sha256":""}
        try:
            response=session.get(url,timeout=(8,18))
            response.raise_for_status()
            raw=response.content
            if len(raw)>12000000 or len(raw)<1500:raise ValueError("Suspicious image size")
            with Image.open(io.BytesIO(raw)) as img:
                img.load()
                if img.format not in ("JPEG","PNG","WEBP"):raise ValueError("Unsupported image")
                w,h=img.size
                if not 250<=w<=6000 or not 250<=h<=6000:raise ValueError("Unusable dimensions")
                thumb=ImageOps.contain(img.convert("RGB"),(320,225))
            rec.update(status="IMAGE_LOADED_NEEDS_HUMAN_REVIEW",pixel_width=w,pixel_height=h,
                       bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            previews.append((r,thumb))
        except Exception as exc:
            rec["status"]="ERROR_"+type(exc).__name__
        out.append(rec)
        time.sleep(0.2)
    cols=4
    rows=(len(items)+cols-1)//cols
    canvas=Image.new("RGB",(cols*352,rows*300),(245,247,250))
    draw=ImageDraw.Draw(canvas)
    font=ImageFont.load_default()
    for i,(r,thumb) in enumerate(previews):
        x=(i%cols)*352;y=(i//cols)*300
        canvas.paste(thumb,(x+(352-thumb.width)//2,y+8))
        draw.text((x+9,y+235),f'{r["brand"]} {r["article"]}',font=font,fill=(20,35,45))
        draw.text((x+9,y+254),r["category"][:35],font=font,fill=(50,70,80))
    canvas.save(args.out/"PHOTO_CONTACT_SHEET_NEEDS_HUMAN_REVIEW.jpg",quality=87)
    with (args.out/"photo_http_and_dimensions.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=FIELDS,delimiter=";")
        writer.writeheader()
        writer.writerows(out)
    summary={"images_hinted":len(items),"images_fetched":len(previews),
             "image_unique_hashes":len(set(x["sha256"] for x in out if x["sha256"])),
             "statuses":dict(Counter(r["status"] for r in out)),
             "final_photo_approval_count":0,
             "no_publication":True}
    (args.out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("AVITO_PHOTO_HINT_REVIEW",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
