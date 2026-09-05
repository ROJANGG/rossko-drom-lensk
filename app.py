#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small HTTP server for Drom permanent price links.

Run with:
    py -m uvicorn app:app --host 0.0.0.0 --port 8080

Drom link example:
    http://your-server:8080/price/drom_lensk.xlsx
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from update_prices import run_once, load_config, text

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

app = FastAPI(title="Rossko Drom Auto Link", version="0.4")
last_update: Dict[str, Any] = {"started_at": None, "finished_at": None, "status": "not_started", "error": None}


def _config() -> Dict[str, Any]:
    return load_config(CONFIG_PATH)


def _update_job() -> None:
    last_update.update({"started_at": datetime.now().isoformat(timespec="seconds"), "status": "running", "error": None})
    try:
        run_once(CONFIG_PATH)
        last_update.update({"finished_at": datetime.now().isoformat(timespec="seconds"), "status": "ok", "error": None})
    except Exception as exc:
        last_update.update({"finished_at": datetime.now().isoformat(timespec="seconds"), "status": "error", "error": str(exc)})


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    try:
        config = _config()
        public_dir = BASE_DIR / text(config.get("drom", {}).get("public_dir") or "public")
        links = []
        for profile in config.get("profiles", []):
            if profile.get("enabled", True):
                filename = text(profile.get("output_filename"))
                path = public_dir / filename
                size = f"{path.stat().st_size / 1024 / 1024:.2f} МБ" if path.exists() else "файл еще не создан"
                links.append(f'<li><a href="/price/{filename}">{filename}</a> — {size}</li>')
        links_html = "".join(links) or "<li>Нет включенных профилей</li>"
    except Exception as exc:
        links_html = f"<li>Ошибка чтения настроек: {exc}</li>"
    return f"""
    <html><head><meta charset="utf-8"><title>Rossko → Drom</title></head>
    <body style="font-family: Arial, sans-serif; max-width: 900px; margin: 32px auto;">
      <h1>Rossko → Drom</h1>
      <p>Статус последнего обновления: <b>{last_update.get('status')}</b></p>
      <p>Начало: {last_update.get('started_at')}<br>Конец: {last_update.get('finished_at')}<br>Ошибка: {last_update.get('error')}</p>
      <form action="/update-now" method="post"><button type="submit">Обновить сейчас</button></form>
      <h2>Постоянные ссылки для Дрома</h2>
      <ul>{links_html}</ul>
    </body></html>
    """


@app.post("/update-now", response_class=PlainTextResponse)
def update_now(background_tasks: BackgroundTasks) -> str:
    if last_update.get("status") == "running":
        return "Обновление уже выполняется."
    background_tasks.add_task(_update_job)
    return "Обновление запущено. Проверь страницу через несколько минут."


@app.get("/status")
def status() -> Dict[str, Any]:
    return dict(last_update)


@app.get("/price/{filename}")
def price_file(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Некорректное имя файла")
    config = _config()
    public_dir = BASE_DIR / text(config.get("drom", {}).get("public_dir") or "public")
    path = public_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл еще не сформирован")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
