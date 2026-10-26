"""Manual sanity check of ROSSKO Drom SKU search results; 5 slow queries."""
import json,time,re
from bs4 import BeautifulSoup
import requests
BASE="https://baza.drom.ru/user/ROSSKOroznica/sell_spare_parts/"
SKUS=["NGN|362209","Allied Nippon|ADC0456V","Master KiT|77R015","SUFIX|SP1165","LYNXauto|BN1109"]
session=requests.Session()
for i,entry in enumerate(SKUS):
    brand,article=entry.split("|",1)
    try:
        r=session.get(BASE,params={"query":article},headers={"User-Agent":"Mozilla/5.0"},timeout=(8,25))
        soup=BeautifulSoup(r.text,"html.parser")
        title=soup.title.get_text(" ",strip=True) if soup.title else ""
        text=soup.get_text(" ",strip=True)
        alllinks=[a for a in soup.select('a[href]') if "/sell_spare_parts/" in a.get("href","") and re.search(r"-g?\d{6,}\.html",a.get("href",""))]
        clues=[]
        for p in ["ничего не найдено","не найдено","нет предложений","предложение","captcha","доступ ограничен","временно недоступно"]:
            pos=text.casefold().find(p)
            if pos!=-1: clues.append({"phrase":p,"text":text[max(0,pos-35):pos+85]})
        print("SKU_SEARCH_PROBE",json.dumps({"brand":brand,"article":article,
          "status":r.status_code,"response_url":r.url,"bytes":len(r.content),
          "title":title,"results_count":len(alllinks),
          "links":[{"text":a.get_text(" ",strip=True)[:120],"href":a.get("href","")} for a in alllinks[:4]],
          "clues":clues},ensure_ascii=False),flush=True)
    except requests.RequestException as e:
        print("SKU_SEARCH_PROBE_ERROR",article,type(e).__name__,flush=True)
    time.sleep(2)
