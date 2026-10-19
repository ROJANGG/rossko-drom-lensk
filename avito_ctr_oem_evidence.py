"""Extract documented OEM cross references from CTR's own product catalog.

Review-only: never modify the public XML, never accept SKU inferred from fitment,
and never generate replacement OEM codes. All external pages are untrusted.
"""
from __future__ import annotations

import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent
IN = ROOT / "input/avito_extra_100_pinned_REVIEW.csv"
OUT = ROOT / "output/avito_ctr_oem_evidence"
CTR_ORIGIN = "https://ctr.co.ru"
USER_AGENT = "Mozilla/5.0 (compatible; Avito-SKU-OEM-evidence-review/1.0)"


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skipping += 1
        if tag in {"p", "div", "span", "li", "br", "h1", "h2", "h3"}:
            self.fragments.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skipping:
            self.skipping -= 1
        self.fragments.append(" ")

    def handle_data(self, data):
        if not self.skipping:
            self.fragments.append(data)


def documented_ctr_oems(html: str, requested_article: str) -> list[str]:
    """Accept exact CTR article and OEM block only; false positives fail closed."""
    parsed = _TextOnly()
    parsed.feed(html)
    content = re.sub(r"\\s+", " ", " ".join(parsed.fragments)).strip()
    sku = requested_article.upper()
    if not re.search(r"Артикул\\s*:\\s*" + re.escape(sku) + r"\\b", content, re.I):
        return []
    if not re.search(r"CTR\\s+" + re.escape(sku) + r"\\b", content, re.I):
        return []
    match = re.search(
        r"OEM-номера\\s*:\\s*(.{4,700}?)"
        r"(?=\\s*(?:Результаты поиска|Применимость|Как убедиться|\\* Результаты))",
        content, re.I
    )
    if not match:
        return []
    numbers = []
    for token in re.findall(r"(?<![A-Z0-9])[A-Z0-9][A-Z0-9-]{3,28}(?![A-Z0-9])", match.group(1).upper()):
        normalized = token.replace("-", "")
        if 5 <= len(normalized) <= 25 and any(c.isdigit() for c in normalized):
            if normalized not in numbers:
                numbers.append(normalized)
    return numbers[:12]


def query_ctr(article: str):
    url = CTR_ORIGIN + "/catalog/" + quote(article.upper())
    try:
        response = requests.get(url, timeout=(8, 16),
                                headers={"User-Agent": USER_AGENT},
                                allow_redirects=False)
        if response.status_code != 200:
            return article, url, [], "http_" + str(response.status_code)
        numbers = documented_ctr_oems(response.text, article)
        return article, url, numbers, "evidence_found" if numbers else "no_exact_oem_evidence"
    except requests.RequestException as error:
        return article, url, [], "network_error_" + type(error).__name__


def read_ctr_pinned(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not {"brand", "article"} <= set(reader.fieldnames or ()):
            raise ValueError("Expected brand;article columns")
        records = list(reader)
    if len(records) != 100:
        raise ValueError("Expected EXACT 100 unique pinned candidates")
    seen = set()
    ctr = []
    for row in records:
        key = (row["brand"].strip().casefold(), row["article"].strip().upper())
        if key in seen or not key[1]:
            raise ValueError("Duplicate or empty pinned SKU")
        seen.add(key)
        if key[0] == "ctr":
            if not re.fullmatch(r"GD[0-9]{4}", key[1]):
                raise ValueError("Unexpected CTR candidate article")
            ctr.append(key[1])
    return ctr


def main():
    articles = read_ctr_pinned(IN)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(query_ctr, articles))
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "CTR_OEM_MANUFACTURER_EVIDENCE_REVIEW.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["brand", "article", "suggested_oem", "other_oem_candidates",
                         "source", "evidence_status", "publication_permission"])
        for article, url, oems, status in results:
            writer.writerow(["CTR", article, oems[0] if oems else "",
                             "|".join(oems[1:]), url, status, "NO"])
    summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "official_ctr_candidates": len(articles),
        "with_exact_oem_evidence": sum(bool(x[2]) for x in results),
        "missing_or_unreadable": sum(not x[2] for x in results),
        "publication": "NEVER; review source, article, image and local stock first",
    }
    (OUT / "summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\\n", encoding="utf-8")
    print("CTR_OEM_MANUFACTURER_AUDIT", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__=="__main__":
    main()
