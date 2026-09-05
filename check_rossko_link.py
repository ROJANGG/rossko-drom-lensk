#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path
import requests

cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
url = cfg["rossko"]["price_url"]
r = requests.get(url, timeout=120)
print("status:", r.status_code)
print("content-type:", r.headers.get("content-type"))
print("size bytes:", len(r.content))
r.raise_for_status()
out = Path("input/rossko_price_download_test.xlsx")
out.parent.mkdir(exist_ok=True)
out.write_bytes(r.content)
print("saved:", out)
