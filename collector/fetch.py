"""礼儀を守る取得。403 / 429 / challenge は即停止して記録し、クールダウンに入る(回避はしない)。"""
from __future__ import annotations

import gzip
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
CERTS_DIR = Path(__file__).resolve().parent / "certs"

# 連絡先は公開リポジトリの URL を入れる(メールアドレスは送らない)。
USER_AGENT = os.environ.get(
    "PH_HAZARDS_UA", "ph-hazards-collector/0.1 (+https://github.com/krystasis/ph-hazards)"
)
TIMEOUT = 40
COOLDOWN_HOURS = {403: 24, 429: 6, "challenge": 24}
CHALLENGE_MARKERS = ("cf-mitigated", "Just a moment...", "Attention Required!", "cf-chl-")


class Blocked(Exception):
    """取得元に拒否された。呼び出し側はこの取得元を止める。"""


@dataclass
class Response:
    status: int  # 200 / 304
    text: str
    etag: str | None
    last_modified: str | None


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # PHIVOLCS は中間証明書を送ってこない。検証を切らず、公開されている中間証明書を足す。
    for pem in CERTS_DIR.glob("*.pem"):
        ctx.load_verify_locations(str(pem))
    return ctx


def _state_path(key: str) -> Path:
    return STATE_DIR / f"{key}.json"


def load_state(key: str) -> dict:
    p = _state_path(key)
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(key: str, state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    _state_path(key).write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def in_cooldown(state: dict, now: datetime) -> bool:
    until = state.get("cooldown_until")
    return bool(until) and now < datetime.fromisoformat(until)


def _block(key: str, state: dict, reason, now: datetime, detail: str) -> None:
    hours = COOLDOWN_HOURS[reason]
    state["cooldown_until"] = (now + timedelta(hours=hours)).isoformat()
    state["last_block"] = {"at": now.isoformat(), "reason": str(reason), "detail": detail[:200]}
    save_state(key, state)
    raise Blocked(f"{key}: {reason} → {hours}h 停止")


def fetch(key: str, url: str, state: dict, now: datetime | None = None, form: dict | None = None) -> Response:
    """条件付き GET。変更が無ければ status=304 で本文は空。form を渡すと、公開ページ自身が行うのと同じ POST になる。"""
    now = now or datetime.now(timezone.utc)
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "text/html"}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    body = urllib.parse.urlencode(form).encode() if form else None
    if form:
        headers["Accept"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8", "replace")
            if r.headers.get("cf-mitigated") or any(m in text[:3000] for m in CHALLENGE_MARKERS[1:]):
                _block(key, state, "challenge", now, text[:200])
            return Response(200, text, r.headers.get("ETag"), r.headers.get("Last-Modified"))
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return Response(304, "", state.get("etag"), state.get("last_modified"))
        if e.code in (403, 429):
            _block(key, state, e.code, now, str(e))
        raise
