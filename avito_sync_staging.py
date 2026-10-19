"""Build a validated XML candidate from fresh ROSSKO price/stock and OEM evidence.

Only source-verified OEM cross-references are allowed into XML. The script itself never uploads to Avito or commits to the public XML branch.
A separately configured GitHub Actions workflow may publish after safety checks.
A failed price download MUST abort.
Use identical stable IDs across update cycles. Do not bypass change checks
or publish supplier price files and audits to a public URL.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_irkutsk import load_fresh_price, load_sku_whitelist, select_rows
from avito_photo_check import approved_url
from update_prices import get_cell, read_header_map
from avito_xml_v3_diagnostic import build_xml, verified_oem
from update_prices import load_config, normalize_key, read_photo_map, text


def product_key(brand: str, article: str) -> str:
    return normalize_key(brand) + "|" + normalize_key(article)


def load_verified_oem(csv_path: Path, whitelist: set[str]) -> dict[str, str]:
    """Only documented, human-reviewed OEM codes; never use vendor SKUs as OEM."""
    result = {}
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        expected = {"brand", "article", "oem_number", "source"}
        if not expected.issubset(set(reader.fieldnames or ())):
            raise ValueError("OEM evidence CSV must have brand;article;oem_number;source")
        for row in reader:
            k = product_key(row["brand"], row["article"])
            oem = text(row["oem_number"]).upper()
            source = text(row["source"])
            if not k or k not in whitelist or k in result:
                raise ValueError(f"Unknown or duplicate OEM key: {k}")
            if not re.fullmatch(r"[A-Z0-9]{4,32}", oem) or not source.startswith("https://"):
                raise ValueError(f"Invalid OEM or evidence URL for {k}")
            # The XML diagnostic contains the four independently investigated
            # codes; disagreeing copies indicate a dangerous silent overwrite.
            if verified_oem(row["brand"], row["article"]) != oem:
                raise ValueError("OEM evidence disagrees with validated XML reference: " + k)
            result[k] = oem
    return result


def evaluate(allowlist: set[str], products: list[dict], photos: dict[str, str],
             verified: dict[str, str], supplier_oem: dict[str, str] | None = None):
    """Return rows for test XML and complete pilot audit (including missing stock)."""
    supplier_oem = supplier_oem or {}
    by_sku = {}
    for p in products:
        k = product_key(p["Бренд"], p["Артикул"])
        if k in allowlist:
            by_sku[k] = p

    ready, audit = [], []
    for k in sorted(allowlist):
        brand_key, article_key = k.split("|", 1)
        p = by_sku.get(k)
        meta = {
            "sku_key": k,
            "brand": p["Бренд"] if p else brand_key,
            "article": p["Артикул"] if p else article_key,
            "group": p["Группа"] if p else "",
            "local_stock": p["Остаток РОССКО"] if p else 0,
            "price_rub": p["Цена Авито"] if p else "",
            "OEM": verified.get(k, ""),
            "supplier_OEM_as_listed": supplier_oem.get(k, ""),
            "status": "",
        }
        if p is None:
            meta["status"] = "out_of_stock_or_not_zero_day_in_irkutsk"
        elif not k in verified:
            meta["status"] = "needs_documented_OEM_cross_reference"
        elif not approved_url(photos.get(k, "")):
            meta["status"] = "missing_supplier_photo"
        else:
            meta["status"] = "staging_xml_ready"
            ready.append({
                "Группа": p["Группа"],
                "Бренд": p["Бренд"],
                "Артикул": p["Артикул"],
                "Цена ₽": p["Цена Авито"],
                "Остаток": p["Остаток РОССКО"],
                "Фото URL": photos[k],
                "Применимость РОССКО": p.get("Применимость", ""),
            })
        audit.append(meta)
    return ready, audit


def build_report(config_path: Path, whitelist_path: Path, evidence_path: Path,
                 target: Path) -> dict:
    cfg = load_config(config_path)
    if cfg.get("rossko", {}).get("price_source") != "url":
        raise ValueError("Production staging requires direct fresh HTTPS Rossko price")
    base = config_path.parent
    allowlist = load_sku_whitelist(whitelist_path)
    if len(allowlist) != 50:
        raise ValueError(f"Expected pinned 50 SKUs, found {len(allowlist)}")
    verified = load_verified_oem(evidence_path, allowlist)
    photos = read_photo_map(base / text(cfg.get("drom", {}).get("photo_map_path") or "input/photos.csv"))
    workbook = load_fresh_price(cfg, base, 2)
    supplier_oem = {}
    try:
        # select_rows guarantees Irkutsk, local stock >0 and delivery exactly 0.
        products = select_rows(workbook.active, cfg)
        header_map = read_header_map(workbook.active)
        if "OEМ Номер" not in header_map:
            print("SOURCE_OEM_COLUMN_MISSING; original-OEM cross-reference not supplied", flush=True)
        else:
            for excel_row in workbook.active.iter_rows(min_row=2):
                k = product_key(
                    text(get_cell(excel_row, header_map, "Бренд")),
                    text(get_cell(excel_row, header_map, "Артикул")),
                )
                if k in allowlist and k not in supplier_oem:
                    supplier_oem[k] = text(get_cell(excel_row, header_map, "OEМ Номер"))
    finally:
        workbook.close()
    if len(products) < 10:
        # Guard against an accidentally empty/wrong-warehouse supplier file.
        raise RuntimeError("Unexpectedly few local-stock candidates; refusing new XML")

    ready, audit = evaluate(allowlist, products, photos, verified, supplier_oem)
    target.mkdir(parents=True, exist_ok=True)
    fields = ["sku_key", "brand", "article", "group", "local_stock", "price_rub", "OEM", "supplier_OEM_as_listed", "status"]
    with (target / "avito_50_sync_audit.csv").open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(audit)

    status_count = dict(Counter(x["status"] for x in audit))
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pilot_sku_count": 50,
        "source": "fresh Rossko Irkutsk XLSX (never cached)",
        "pricing_strategy": "progressive_marginal_markup_avito_only",
        "avito_pricing": cfg.get("avito", {}).get("pricing", {}),
        "profit_note": "Gross spread before Avito commissions, delivery, taxes and refunds",
        "state": "CANDIDATE_XML_GENERATOR_ONLY_PUBLICATION_HANDLED_BY_WORKFLOW",
        "ready_count": len(ready),
        "verified_oem_count": len(verified),
        "note": "Only documented original-equipment cross-references. Missing ones never enter Avito.",

        "supplier_oem_nonempty_count": sum(bool(supplier_oem.get(k)) for k in allowlist),
        "status_counts": status_count,
        "stock_failure_policy": "abort without modifying last known-good artifact",
        "out_of_stock_policy": "omit expired SKU from staged XML; verify Avito feed ownership/removal before using on a live URL",
    }
    (target / "summary.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if ready:
        # Only source-verified OEMs may appear. Do not publish XML
        # before checking removal semantics, any Avito category changes, and
        # that the feed cannot unintentionally control unrelated listings.
        xml_path = target / "AVITO_XML_PRICE_STOCK_STAGING_NOT_LIVE.xml"
        xml_path.write_bytes(build_xml(ready))
        parsed = ET.parse(xml_path)
        assert len(parsed.findall("./Ad")) == len(ready)
    print("AVITO_SYNC_STAGING", json.dumps(metadata, ensure_ascii=False), flush=True)
    print("VERIFIED_OEM_PILOT_ARTICLES", len(verified), "OF", len(allowlist), flush=True)
    print("ALL_50_DOCUMENTED_OEM_CANDIDATES", len(verified) == len(allowlist), flush=True)
    return metadata


def main():
    p = argparse.ArgumentParser(description="Stage XML price/stock review only; NO Avito posting")
    p.add_argument("--config", default="config.json")
    p.add_argument("--whitelist", default="input/avito_pilot_articles.csv")
    p.add_argument("--verified-oem", default="input/avito_oem_verified.csv")
    p.add_argument("--out", default="output/avito_price_stock_staging")
    a = p.parse_args()
    config_path = Path(a.config).resolve()
    base = config_path.parent
    def resolve(s):
        path = Path(s)
        return path if path.is_absolute() else base / path
    build_report(config_path, resolve(a.whitelist), resolve(a.verified_oem), resolve(a.out))


if __name__ == "__main__":
    main()
