"""One-request diagnostic for Drom /verify page; no CAPTCHA bypass.
Stop if disallowed by robots; do not submit tokens, emulate browser or
attempt any security challenge.
"""
import json,re,urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urljoin
import requests

BASE="https://baza.drom.ru"
PATH="/verify?u=%2Fuser%2FROSSKOroznica%2Fsell_spare_parts%2F%3Fquery%3DSP1165"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; CatalogResearch/1.0; verify-inspection)"}
class Parse(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms=[]
        self.inputs=[]
        self.buttons=[]
        self.scripts=[]
        self.title=""
        self.intitle=False
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="form":
            self.forms.append({"action":d.get("action"),"method":d.get("method")})
        if tag=="input":
            self.inputs.append({"type":d.get("type"),"name":d.get("name"),"id":d.get("id")})
        if tag=="button":
            self.buttons.append({"type":d.get("type"),"text":d.get("aria-label","")})
        if tag=="script" and d.get("src") and len(self.scripts)<15:
            self.scripts.append(d.get("src")[:160])
        if tag=="title":self.intitle=True
    def handle_endtag(self,tag):
        if tag=="title":self.intitle=False
    def handle_data(self,value):
        if self.intitle:self.title+=value
try:
    r=requests.get(BASE+"/robots.txt",headers=HEADERS,timeout=(8,15))
    r.raise_for_status()
    robot=urllib.robotparser.RobotFileParser()
    robot.parse(r.text.splitlines())
    allowed=robot.can_fetch(HEADERS["User-Agent"],BASE+PATH)
    result={"robots_permits":allowed}
    if allowed:
        r=requests.get(BASE+PATH,headers=HEADERS,timeout=(8,20),allow_redirects=False)
        p=Parse()
        p.feed(r.text[:200000])
        result.update({"http":r.status_code,"title":p.title,
                       "forms":p.forms[:5],"inputs":p.inputs[:10],
                       "buttons":p.buttons[:10],"scripts":p.scripts[:10],
                       "has_captcha":bool(re.search("captcha|hcaptcha|recaptcha|smartcaptcha|провер.+робот|подтверди.+человек",r.text,re.I)),
                       "has_javascript":bool(p.scripts),
                       "redirect":r.headers.get("Location",""),
                       "brief_text_clue":re.findall(r"(?i).{0,65}(?:провер|защит|robot|captcha).{0,80}",re.sub("<[^>]+>"," ",r.text))[:5]})
    print("DROM_VERIFY_INSPECTION",json.dumps(result,ensure_ascii=False),flush=True)
except requests.RequestException as e:
    print("DROM_VERIFY_INSPECTION_ERROR",type(e).__name__,flush=True)
