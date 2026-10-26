"""Guarded ROSSKO -> Avito expansion: 66 exact SKUs, no invented OEM and no publication here."""
from __future__ import annotations
import argparse,csv,json,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from avito_irkutsk import load_fresh_price,select_rows
from avito_xml_v3_diagnostic import build_xml
from avito_feed import stable_id
from avito_photo_check import approved_url
from update_prices import load_config,normalize_key,read_photo_map,read_header_map,get_cell,text

ROOT=Path(__file__).resolve().parent
CSV=ROOT/"input/avito_remaining67_oem_source_verified.csv"
PINS=ROOT/"input/avito_remaining_67_NOT_READY_FOR_UPLOAD.csv"
SKIP=("marshall","m2000666")

def key(b,a):
    return (normalize_key(b),normalize_key(a))

def evidence_map(csv_path=CSV,pins_path=PINS):
    with pins_path.open(encoding="utf-8-sig",newline="") as f:
        pinned=list(csv.DictReader(f,delimiter=";"))
    with csv_path.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f,delimiter=";"))
    allowed={key(r["brand"],r["article"]) for r in pinned}
    if len(pinned)!=67 or len(allowed)!=67 or len(rows)!=67:
        raise ValueError("Expected 67 unique pinned and verified evidence rows")
    result={}
    for row in rows:
        k=key(row["brand"],row["article"])
        oe=row["verified_original_oem"].strip().upper()
        url=row["source_url"].strip()
        if k in result or k not in allowed:
            raise ValueError("Unexpected or duplicate evidence SKU "+str(k))
        if not re.fullmatch(r"[A-Z0-9]{6,24}",oe) or oe==normalize_key(row["article"]).upper():
            raise ValueError("Invalid original OEM for "+str(k))
        u=urlsplit(url)
        if u.scheme!="https" or u.username or u.password or u.port not in (None,443):
            raise ValueError("Untrusted source URL")
        if k[0]=="ngn":
            expected=f"https://ngn-parts.com/{row['article'][:2]}-{row['article'][2:]}.html"
            if url!=expected or row["evidence_level"]!="MANUFACTURER_EXACT_SKU":
                raise ValueError("NGN manufacturer exact-SKU source mismatch")
        elif k[0]=="marshall":
            expected=f"https://cars.marshall.parts/product/{row['article'].lower()}/"
            if url!=expected or row["evidence_level"]!="MANUFACTURER_EXACT_SKU":
                raise ValueError("Marshall manufacturer exact-SKU source mismatch")
        elif k==("masterkit","77r072"):
            if url!="https://hyperauto.ru/product/reyka-rulevaya-master-kit-art-77r072-300815889/":
                raise ValueError("Wrong 77R072 source")
        elif k==("masterkit","77r097"):
            if url!="https://www.nissan-vsem.ru/articles/nissan_480014ba0a_646/":
                raise ValueError("Wrong 77R097 source")
        elif k==("fenox","tb217657"):
            if url!="https://autoprofi.bg/spirachen-disk-pr8360360.html":
                raise ValueError("Wrong Fenox source")
        else:
            raise ValueError("SKU not in supported categories")
        result[k]=row
    if set(result)!=allowed or result[SKIP]["publication_scope"]!="EXCLUDE_NO_CURRENT_ROSSKO_STOCK":
        raise ValueError("Missing source or wrong stock exclusion")
    if sum(v["publication_scope"]=="EXCLUDE_NO_CURRENT_ROSSKO_STOCK" for v in result.values())!=1:
        raise ValueError("Only missing-stock Marshall M2000666 may be excluded")
    return result

def approved_bulk_ids():
    return {stable_id("Рулевые рейки" if k[0]=="masterkit" else "Тормозные диски",v["brand"],v["article"])
            for k,v in evidence_map().items() if k!=SKIP}

def assemble(previous, products, photos, nomenclatures, evidence, *, max_missing=0):
    root=ET.fromstring(previous)
    if root.tag!="Ads" or root.get("formatVersion")!="3":
        raise ValueError("Not Avito XML v3")
    original=root.findall("Ad")
    ids={a.findtext("Id") for a in original}
    if len(original)<72 or len(ids)!=len(original) or None in ids:
        raise ValueError("Base listings missing or duplicate")
    permit={k:r for k,r in evidence.items() if k!=SKIP}
    product_map={key(p["Бренд"],p["Артикул"]):p for p in products if key(p["Бренд"],p["Артикул"]) in permit}
    missing=sorted(set(permit)-set(product_map))
    if len(missing)>max_missing:
        raise ValueError("Too many parts unavailable in current Irkutsk supplier stock "+str(missing))
    additions=[]
    for k in sorted(product_map):
        p=product_map[k]
        category="Рулевые рейки" if k[0]=="masterkit" else "Тормозные диски"
        photo=photos.get("|".join(k),"")
        nom=nomenclatures.get(k,"")
        if p["Группа"]!=category or int(p["Цена Авито"])<=0 or int(p["Остаток РОССКО"])<=0:
            raise ValueError("Wrong category, price, or stock for "+str(k))
        if not approved_url(photo) or not nom or "/"+nom.casefold()+"/" not in photo.casefold():
            raise ValueError("Supplier image nomenclature mismatch "+str(k))
        if stable_id(category,p["Бренд"],p["Артикул"]) in ids:
            raise ValueError("Bulk item already exists in current Avito feed")
        additions.append({"Группа":category,"Бренд":p["Бренд"],"Артикул":p["Артикул"],
                          "Цена ₽":p["Цена Авито"],"Остаток":p["Остаток РОССКО"],
                          "Фото URL":photo,"Применимость РОССКО":""})
    oem={"|".join(k):v["verified_original_oem"] for k,v in permit.items()}
    generated=ET.fromstring(build_xml(additions,verified_extra_oems=oem))
    for item in generated.findall("Ad"):
        ident=item.findtext("Id")
        if not ident or ident in ids:
            raise ValueError("Repeated new ID")
        ids.add(ident)
        root.append(item)
    ET.indent(root,space="  ")
    return ET.tostring(root,encoding="utf-8",xml_declaration=True),{
      "base":len(original),"added":len(additions),"total":len(ids),
      "unavailable":["|".join(k) for k in missing],
      "extra_ids":[a.findtext("Id") for a in generated.findall("Ad")]
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-xml",required=True)
    ap.add_argument("--out",default="output/avito_bulk66_review")
    ap.add_argument("--live-candidate",action="store_true")
    ap.add_argument("--allow-small-stock-removals",action="store_true")
    args=ap.parse_args()
    config=load_config(ROOT/"config.json")
    if config.get("rossko",{}).get("price_source")!="url":
        raise ValueError("Supplier prices must be live HTTPS data")
    oems=evidence_map()
    photos=read_photo_map(ROOT/text(config.get("drom",{}).get("photo_map_path") or "input/photos.csv"))
    book=load_fresh_price(config,ROOT,2)
    try:
        products=select_rows(book.active,config)
        headers=read_header_map(book.active)
        wanted=set(oems)-{SKIP}
        noms={}
        for r in book.active.iter_rows(min_row=2):
            k=key(text(get_cell(r,headers,"Бренд")),text(get_cell(r,headers,"Артикул")))
            if k in wanted and k not in noms:
                noms[k]=text(get_cell(r,headers,"Номенклатура"))
    finally:
        book.close()
    xml,audit=assemble(Path(args.base_xml).read_bytes(),products,photos,noms,oems,
                       max_missing=2 if args.allow_small_stock_removals else 0)
    path=ROOT/args.out
    path.mkdir(parents=True,exist_ok=True)
    filename="AVITO_BULK66_LIVE_CANDIDATE.xml" if args.live_candidate else "AVITO_BULK66_REVIEW_NOT_LIVE.xml"
    (path/filename).write_bytes(xml)
    audit.update(checked_at_utc=datetime.now(timezone.utc).isoformat(),
                 publication_state="LIVE_CANDIDATE_NOT_UPLOADED" if args.live_candidate else "PRIVATE_PREVIEW_ONLY")
    (path/"summary.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_BULK66_PREFLIGHT",json.dumps(audit,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
