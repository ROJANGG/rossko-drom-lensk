"""Preflight for remaining eleven CTR Avito brake discs.

Inputs: current published Avito XML and fresh Rossko Irkutsk stock.
Output: a PRIVATE expanded candidate XML and JSON report; never commits to feed
or uploads to Avito. Publication requires separate Avito moderation evidence.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_irkutsk import load_fresh_price, select_rows
from avito_photo_check import approved_url, retrieve_image
from avito_xml_v3_diagnostic import build_xml
from avito_feed import stable_id
from update_prices import get_cell, load_config, normalize_key, read_header_map, read_photo_map, text

EXTRA_ARTICLES = ("GD0180", "GD0185", "GD0186", "GD0188", "GD0194", "GD0196", "GD0197", "GD0240", "GD0242", "GD0275", "GD0152")
EXTRA = {("ctr", article.casefold()) for article in EXTRA_ARTICLES}
GROUP = "Тормозные диски"

def approved_fourth_eleven_ids() -> set[str]:
    """Fixed, explicit stable IDs allowed for the next eleven CTR items only."""
    return {stable_id(GROUP, "CTR", article) for article in EXTRA_ARTICLES}



def sku(brand, article):
    return normalize_key(brand), normalize_key(article)


def read_evidence(path: Path) -> dict[str, str]:
    result = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        required = {"brand", "article", "proposed_original_oem", "source", "verification_status"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Missing manufacturer evidence columns")
        for row in reader:
            key = sku(row["brand"], row["article"])
            if key not in EXTRA:
                continue
            oem = text(row["proposed_original_oem"]).upper().replace("-", "")
            if key in result or not 5 <= len(oem) <= 32 or not oem.isalnum():
                raise ValueError("Malformed or duplicate sourced original OEM for " + str(key))
            if row["source"] != "https://ctr.co.ru/catalog/" + row["article"].upper():
                raise ValueError("Wrong supplier catalog article URL for " + str(key))
            if row["verification_status"] != "MANUFACTURER_OEM_CATALOG_REVIEW":
                raise ValueError("Manufacturer OEM source is not in the reviewed list")
            if oem == row["article"].upper():
                raise ValueError("Part's own aftermarket article cannot be OEM")
            result["|".join(key)] = oem
    if set(result) != {"|".join(x) for x in EXTRA}:
        raise ValueError("Not all eleven exact-part OEMs have manufacturer references")
    return result


def assemble(base_xml: bytes, products: list[dict], photos: dict[str, str],
             nomenclatures: dict[tuple[str, str], str], oems: dict[str, str],
             image_check=None, *, allow_small_stock_removals: bool = False) -> tuple[bytes, dict]:
    root = ET.fromstring(base_xml)
    if root.tag != "Ads" or root.get("formatVersion") != "3":
        raise ValueError("Previous feed not Avito XML v3")
    old_ads = root.findall("Ad")
    ids = [x.findtext("Id") for x in old_ads]
    if len(ids) < 40 or len(set(ids)) != len(ids) or any(not s for s in ids):
        raise ValueError("Existing catalog incomplete or duplicated; no next batch")
    existing = set(ids)
    matches = {sku(p["Бренд"], p["Артикул"]):p for p in products if sku(p["Бренд"],p["Артикул"]) in EXTRA}
    missing = sorted(EXTRA - set(matches))
    if missing and (not allow_small_stock_removals or len(missing) > 2):
        raise ValueError("Some eleven CTR SKUs are not in freshly verified Irkutsk stock")
    new = []
    for brand, article in sorted(EXTRA):
        if (brand,article) not in matches:
            continue  # Local zero stock: omit this previously approved ad on refresh.
        p = matches[(brand,article)]
        catalog_number = nomenclatures.get((brand,article), "")
        link = photos.get(brand + "|" + article, "")
        sid = stable_id(GROUP,p["Бренд"],p["Артикул"])
        if sid in existing:
            raise ValueError("New product already exists in public Avito feed")
        if p["Группа"] != GROUP or p["Остаток РОССКО"] <= 0 or p["Цена Авито"] <= 0:
            raise ValueError("Invalid selected item category/price/stock")
        if not approved_url(link) or not catalog_number or ("/" + catalog_number.casefold() + "/") not in link.casefold():
            raise ValueError("Photo filename does not map to supplier article")
        if image_check is not None:
            if not image_check(link):
                raise ValueError("Photo image bytes failed validation for " + article)
        new.append({
            "Группа":GROUP,"Бренд":p["Бренд"],"Артикул":p["Артикул"],
            "Цена ₽":p["Цена Авито"],"Остаток":p["Остаток РОССКО"],
            "Фото URL":link,"Применимость РОССКО":""
        })
    add_root = ET.fromstring(build_xml(new, verified_extra_oems=oems))
    for ad in add_root.findall("Ad"):
        ident = ad.findtext("Id")
        if ident in existing:
            raise ValueError("Duplicate listing ID")
        existing.add(ident)
        root.append(ad)
    ET.indent(root,space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), {
        "previous":len(old_ads), "new":len(new), "total":len(root.findall("Ad")),
        "added_ids":sorted(set(existing)-set(ids)),
        "omitted_for_local_stock":["|".join(k) for k in missing],
        "new_prices_rub":{p["Артикул"]:p["Цена ₽"] for p in new},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-xml",required=True)
    parser.add_argument("--out",default="output/avito_fourth_eleven_review")
    parser.add_argument("--config",default="config.json")
    parser.add_argument("--evidence",default="input/avito_ctr_33_oem_REVIEW.csv")
    parser.add_argument("--live-candidate",action="store_true",help="Stage approved release; still does NOT upload by itself")
    parser.add_argument("--allow-small-stock-removals",action="store_true",help="On recurring refresh only, omit up to 2 unavailable CTR SKUs")
    args=parser.parse_args()
    cfg_path=Path(args.config).resolve()
    project=cfg_path.parent
    cfg=load_config(cfg_path)
    if cfg.get("rossko",{}).get("price_source") != "url":
        raise ValueError("Production preflight demands a fresh Rossko HTTPS price source")
    oems=read_evidence(project/args.evidence)
    photos=read_photo_map(project / text(cfg.get("drom",{}).get("photo_map_path") or "input/photos.csv"))
    book=load_fresh_price(cfg,project,2)
    try:
        items=select_rows(book.active,cfg)
        headers=read_header_map(book.active)
        nomenclatures={}
        for r in book.active.iter_rows(min_row=2):
            k=sku(text(get_cell(r,headers,"Бренд")),text(get_cell(r,headers,"Артикул")))
            if k in EXTRA and k not in nomenclatures:
                nomenclatures[k]=text(get_cell(r,headers,"Номенклатура"))
    finally:
        book.close()

    def verify_image(url):
        image,status,width,height,digest=retrieve_image(url)
        return image is not None and status=="available_unverified" and bool(digest)

    xml, report=assemble(Path(args.base_xml).read_bytes(),items,photos,nomenclatures,oems,
                         image_check=verify_image,allow_small_stock_removals=args.allow_small_stock_removals)
    target=project/args.out
    target.mkdir(parents=True,exist_ok=True)
    xml_name="AVITO_FOURTH_ELEVEN_LIVE_CANDIDATE.xml" if args.live_candidate else "AVITO_FOURTH_ELEVEN_REVIEW_NOT_FOR_UPLOAD.xml"
    (target/xml_name).write_bytes(xml)
    report["generated_at_utc"]=datetime.now(timezone.utc).isoformat()
    report["state"]="LIVE_CANDIDATE_AWAITING_WORKFLOW_SAFETY_CHECKS" if args.live_candidate else "PRIVATE_REVIEW_ONLY_NO_AVITO_PUBLICATION"
    report["needs_avito_moderation_report"]=not args.live_candidate
    (target/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AVITO_FOURTH_ELEVEN_PREFLIGHT",json.dumps(report,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
