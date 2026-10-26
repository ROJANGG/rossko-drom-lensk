"""Limited, read-only discovery of public ROSSKO Drom seller-search access.

MAX 4 HTML requests in one execution, never sends ad, login or order actions.
Honors robots.txt. Report has only public metadata, no private credentials.
"""
from __future__ import annotations
import json
import re
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT="https://baza.drom.ru"
PATHS=[
    "/user/ROSSKOroznica/",
    "/user/ROSSKOroznica/sell_spare_parts/",
    "/user/ROSSKOroznica/?query=361366",
]

class Scanner(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms=[]
        self.links=[]
        self.inputs=[]
        self.current_form=None
        self.title=""
        self.in_title=False

    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="form":
            self.current_form={"action":a.get("action",""),"method":a.get("method","GET"),"fields":[]}
            self.forms.append(self.current_form)
        elif tag in ("input","select"):
            info={"name":a.get("name"),"placeholder":a.get("placeholder"),
                  "type":a.get("type"),"value":(a.get("value") or "")[:80]}
            if self.current_form is not None:
                self.current_form["fields"].append(info)
            self.inputs.append(info)
        elif tag=="a" and len(self.links)<400:
            if a.get("href"):
                self.links.append(a["href"])
        if tag=="title":
            self.in_title=True

    def handle_endtag(self, tag):
        if tag=="form":
            self.current_form=None
        if tag=="title":
            self.in_title=False

    def handle_data(self, data):
        if self.in_title:
            self.title+=data

def main():
    headers={"User-Agent":"Mozilla/5.0 (compatible; SellerProductComparison/1.0; single-page-research)"}
    session=requests.Session()
    report={"at_utc":datetime.now(timezone.utc).isoformat(),"pages":[],"request_limit":4}
    robot=None
    try:
        r=session.get(ROOT+"/robots.txt",timeout=(7,12),headers=headers)
        report["robots_status"]=r.status_code
        if r.ok:
            robot=urllib.robotparser.RobotFileParser()
            robot.parse(r.text.splitlines())
            report["robots_can_fetch_profile"]=robot.can_fetch(headers["User-Agent"],ROOT+PATHS[0])
            report["robots_can_fetch_spare_parts"]=robot.can_fetch(headers["User-Agent"],ROOT+PATHS[1])
    except requests.RequestException as e:
        report["robots_error"]=type(e).__name__
    if robot is None:
        # With unavailable robots, do not crawl.
        report["stopped"]="robots.txt not available"
        print("DROM_SELLER_RESEARCH",json.dumps(report,ensure_ascii=False),flush=True)
        return
    for path in PATHS:
        url=ROOT+path
        if not robot.can_fetch(headers["User-Agent"],url):
            report["pages"].append({"url":url,"result":"robots_disallow"})
            continue
        try:
            response=session.get(url,timeout=(7,16),headers=headers,allow_redirects=False)
            scan=Scanner()
            scan.feed(response.text[:1000000])
            candidates=[x for x in scan.links if
                        any(y in x.lower() for y in ("rossko","query=","search","sell_spare_parts","page="))]
            report["pages"].append({
                "url":url,
                "status":response.status_code,
                "html_bytes":len(response.content),
                "title":scan.title[:160],
                "location_header":response.headers.get("Location",""),
                "forms":scan.forms[:8],
                "interesting_inputs":scan.inputs[:30],
                "query_link_examples":candidates[:18],
                "item_count_excerpt":re.findall(r"[\d\s\xa0]{3,15}\s*(?:предложени[йяе]|объявлени[йяе])",response.text,re.I)[:6],
                "challenge_or_captcha":bool(re.search(r"captcha|access.denied|cloudflare|подтвердите.что.вы",response.text,re.I)),
            })
        except requests.RequestException as e:
            report["pages"].append({"url":url,"error":type(e).__name__,"detail":str(e)[:150]})
    Path("drom_seller_probe.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("DROM_SELLER_RESEARCH",json.dumps(report,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
