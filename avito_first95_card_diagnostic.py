#!/usr/bin/env python3
"""Read-only 3-item probe of first-party ROSSKO product card paths and images.
No secrets logged. Robots permission checked before any card HTTP fetch.
No new live feed files or product images published.
"""
from __future__ import annotations
import json,os,re,sys,urllib.robotparser
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from rossko_wholesale_private_audit import rpc,zeep_client,choose_delivery,retry_transient,findnode,aslist,norm

EXAMPLES=[("LYNXauto","BS6307"),("Luzar","LRAC3034"),("Bosch","0250201055")]
def run():
    creds={name:(os.environ.get("ROSSKO_API_"+name) or "").strip() for name in ("KEY1","KEY2")}
    if any(not v for v in creds.values()):
        raise RuntimeError("Missing ROSSKO API secrets")
    ch=rpc(zeep_client("GetCheckoutDetails"),"GetCheckoutDetails",creds)
    delivery,mode=choose_delivery(ch)
    if not delivery:raise RuntimeError("No account fulfillment")
    session=requests.Session()
    session.headers.update({"User-Agent":"RosskoCatalogPublicCardResearch/1.0"})
    robots=session.get("https://rossko.ru/robots.txt",timeout=(8,15))
    print("ROBOTS_HTTP",robots.status_code,robots.headers.get("Content-Type",""))
    if robots.status_code!=200:raise RuntimeError("Cannot fetch robots, no product card access")
    parser=urllib.robotparser.RobotFileParser()
    parser.parse(robots.text.splitlines())
    client=zeep_client("GetSearch")
    data=[]
    for brand,article in EXAMPLES:
        result=rpc(client,"GetSearch",{**creds,**delivery,"text":brand+" "+article})
        root=findnode(result,["PartsList"]) or {}
        matches=[x for x in aslist((root.get("PartsList") or {}).get("Part"))
                 if isinstance(x,dict) and norm(x.get("brand"))==norm(brand)
                  and norm(str(x.get("partnumber") or "").split("@")[0])==norm(article)]
        guid=str(matches[0].get("guid") or "") if matches else ""
        print("PART",brand,article,"exact",len(matches),
              "guid_format",bool(re.fullmatch("[A-Z0-9]{8,25}",guid,re.I)))
        if not re.fullmatch(r"[A-Z0-9]{8,25}",guid,re.I):continue
        slug=re.sub(r"[^a-z0-9\-]+","",brand.casefold())
        article_slug=re.sub(r"[^a-z0-9\-]+","",article.casefold())
        uri=f"https://rossko.ru/card/{slug}-{article_slug}-{guid.lower()}/"
        allowed=parser.can_fetch(session.headers["User-Agent"],uri)
        if not allowed:
            print("CARD",brand,article,"ROBOTS_FORBIDDEN")
            continue
        try:
            r=session.get(uri,timeout=(8,25),allow_redirects=True)
            body=r.text[:3000000]
            soup=BeautifulSoup(body,"html.parser")
            heading=(soup.find("h1") or soup.title)
            title=heading.get_text(" ",strip=True)[:160] if heading else ""
            words=soup.get_text(" ",strip=True)
            near_oem=re.search(r"(?:\bOEM\b|ОЕМ(?:-номер)?|Оригинальн\w+\s+номер\w*)",words,re.I)
            snippet=words[near_oem.start():near_oem.start()+220] if near_oem else ""
            imgs=[(tag.get("src") or tag.get("data-src") or "") for tag in soup.find_all("img")]
            imgs=[x[:180] for x in imgs if "http" in x or "/NSI" in x.upper()][:12]
            og=[t.get("content","")[:200] for t in soup.find_all("meta",property="og:image")][:8]
            print("CARD",brand,article,json.dumps({
                "http":r.status_code,"actual_url":r.url,
                "bytes":len(r.content),"title":title,
                "has_brand":brand.casefold() in words.casefold(),
                "has_article":norm(article) in norm(words),
                "oem_excerpt":snippet,
                "inline_img_urls":imgs[:6],
                "og_image":og[:4],
                "schema_product":bool(soup.find("script",type="application/ld+json")),
                "has_captcha_or_challenge":bool(re.search("captcha|sentinel|cloudflare challenge",words,re.I))
            },ensure_ascii=False))
        except Exception as exc:
            print("CARD",brand,article,"error_class",type(exc).__name__)
    return 0
if __name__=="__main__":
    sys.exit(run())
