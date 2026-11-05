"""Read-only first-party Luzar product page/photo source feasibility."""
import re,json,urllib.robotparser,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
url="https://luzar.ru/catalogue/radiatory/radiatory-konditsionera-kondensery/radiator-konditsionera-dlya-avtomobiley-jetour-dashing-22-1-5t-1-6t-lrac-3034/"
session=requests.Session()
session.headers["User-Agent"]="RosskoAvitoFirstPartyManufacturerPhotoResearch/1.0"
robots=session.get("https://luzar.ru/robots.txt",timeout=(8,20))
print("ROBOTS",robots.status_code,robots.headers.get("Content-Type",""),len(robots.content))
if robots.status_code!=200 or not robots.headers.get("Content-Type","").lower().startswith("text/plain"):
    raise SystemExit("Robots unavailable/invalid; no crawling")
robot=urllib.robotparser.RobotFileParser()
robot.parse(robots.text.splitlines())
if not robot.can_fetch(session.headers["User-Agent"],url):
    raise SystemExit("Robots forbids page; stop")
r=session.get(url,timeout=(8,30))
print("WEB",r.status_code,r.url,len(r.content),r.headers.get("Content-Type",""))
if r.status_code!=200:raise SystemExit("Page unavailable")
soup=BeautifulSoup(r.text,"html.parser")
title=soup.title.get_text(" ",strip=True)[:150] if soup.title else ""
text=soup.get_text(" ",strip=True)
print("TITLE",title)
print("ARTICLE_CONFIRMED",bool(re.search(r"LRAC[\s-]*3034",text,re.I)))
i=text.find("OEM-номера")
print("OEM_EXCERPT",text[i:i+130] if i>=0 else "not found")
imgs=[]
for img in soup.find_all("img"):
    src=img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
    alt=img.get("alt","")
    if not src:continue
    imgs.append({"url":urljoin(url,src)[:250],"alt":alt[:150]})
oimgs=[x for x in imgs if "3034" in (x["url"]+" "+x["alt"]).casefold()]
print("IMG",json.dumps(imgs[:30],ensure_ascii=False))
print("ARTICLE_IMG",json.dumps(oimgs[:20],ensure_ascii=False))
print("META_IMG",json.dumps([x.get("content","")[:250] for x in soup.find_all("meta",property="og:image")][:6],ensure_ascii=False))
