"""PAGASA 地域別ページの豪雨警報・雷雨注意報(市町名つき)。docs/sources/pagasa-regional.md"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime

from .htmlutil import block_text, cell_text, inner_html_by_id

KEY = "pagasa-regional"
BASE = "https://www.pagasa.dost.gov.ph/regional-forecast/"
REGIONS = ["ncrprsd", "nlprsd", "slprsd", "visprsd", "minprsd"]
MIN_INTERVAL_MIN = 14

KINDS = {"rainfalls": "rainfall", "thunderstorms": "thunderstorm"}
_NONE = re.compile(r"there is no .{0,60}(issued|warning|advisory)", re.I)
_NO = re.compile(r"\bNo\.?\s*(\d+[A-Z]?)", re.I)
_ISSUED = re.compile(r"Issued at:?\s*([0-9: ]+[AP]M),?\s*(\d{1,2}\s+\w+\s+\d{4})", re.I)
_SPLIT = re.compile(r"</div>\s*<div[^>]*>", re.I)


def _issued_iso(text: str) -> str:
    m = _ISSUED.search(text)
    if not m:
        return ""
    try:
        dt = datetime.strptime(f"{m.group(2)} {m.group(1).strip()}", "%d %B %Y %I:%M %p")
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:00+08:00")


def parse(page: str, region: str) -> list[dict]:
    items: list[dict] = []
    for element_id, kind in KINDS.items():
        inner = inner_html_by_id(page, element_id)
        if not inner:
            continue
        for frag in _SPLIT.split(inner):
            text = block_text(frag)
            if len(text) < 40 or _NONE.search(text[:200]):
                continue
            no = _NO.search(text.split("\n", 1)[0])
            issued = _issued_iso(text)
            digest = hashlib.sha256(text.encode()).hexdigest()[:12]
            items.append(
                {
                    "id": f"{region}:{kind}:{issued or 'na'}:{no.group(1) if no else 'na'}:{digest}",
                    "region": region,
                    "kind": kind,
                    "title": text.split("\n", 1)[0],
                    "number": no.group(1) if no else "",
                    "issued_at": issued,
                    "text": text,
                }
            )
    return items


def month_of(item: dict, fallback: str) -> str:
    return (item["issued_at"] or fallback)[:7]


# --- 週間予報(Extended Weather Outlook)---------------------------------------------------------
# 同じページの中にある。注意報と同じ 1 回の取得から読む(リクエストは増やさない)。
# 静的な HTML の欄は **その PRSD の既定の州 1 つぶん**(NCR は Metro Manila、NL は Ilocos Norte など)。
# 州を選ぶと JS が `let regional = {...}` の州別データで書き換える。州別データも同じページに載っているので、
# 表(regional_outlook)には HTML の欄だけを入れ、州別は jsonl に残しておく(docs/sources/pagasa-regional.md)。

_OUTLOOK_HEAD = "Extended Weather Outlook"
_OUTLOOK_ISSUED = re.compile(
    r"Issued\s+at\s*:?\s*(\d{1,2})\s*:\s*(\d{2})\s*([AP])\.?\s*M\.?\s*,?\s*"
    r"(?:(\d{1,2})\s+([A-Za-z]+)\.?|([A-Za-z]+)\.?\s+(\d{1,2}))\s*,?\s*(\d{4})",
    re.I,
)
_OUTLOOK_END = re.compile(r'<ul class="nav|id="rainfalls"|<script', re.I)
_OUTLOOK_ITEM = re.compile(r'<div class="outlook-item"', re.I)
_BOLD = re.compile(r'<span style="font-weight:\s*bold;?">(.*?)</span>', re.I | re.S)
_IMG_TITLE = re.compile(r'<img[^>]*\btitle="([^"]*)"', re.I)
_LOW = re.compile(r'class="low">\s*(-?\d+)', re.I)
_HIGH = re.compile(r'class="high">\s*(-?\d+)', re.I)
_VALUES = re.compile(r"<div>\s*<span>(.*?)</span>\s*<span>(.*?)</span>\s*</div>", re.I | re.S)
_LABELS = {"windspeed": "wind", "direction": "direction", "coastalcondition": "coastal"}
_REGIONAL_JSON = re.compile(r"let\s+regional\s*=\s*")
PROVINCE_DAY = ("tmin", "tmax", "wind", "direction", "coastal")  # jsonl の provinces[*].days[i] の並び


def outlook_issued_iso(text: str) -> str:
    """「Issued at: 09:00 AM, 26 September, 2026」→ 2026-09-26T09:00:00+08:00。読めなければ空。"""
    m = _OUTLOOK_ISSUED.search(text)
    if not m:
        return ""
    hh, mm, ap, d1, mon1, mon2, d2, year = m.groups()
    day, mon = (d1, mon1) if d1 else (d2, mon2)
    for fmt, name in (("%d %B %Y %I:%M %p", mon), ("%d %b %Y %I:%M %p", mon[:3])):  # 「Sept」のような略記も読む
        try:
            dt = datetime.strptime(f"{int(day)} {name} {year} {int(hh)}:{mm} {ap.upper()}M", fmt)
        except ValueError:
            continue
        return dt.strftime("%Y-%m-%dT%H:%M:00+08:00")
    return ""


def _int(m) -> int | None:
    return int(m.group(1)) if m else None


def _regional_json(page: str) -> dict | None:
    m = _REGIONAL_JSON.search(page)
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(page, m.end())
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _provinces(page: str) -> tuple[dict, str, str]:
    """州別の週間予報({州のコード: {name, days}})、既定の州の名前、既定の州のコード。

    ページの JS と同じく、州の outlook の先頭(24 時間予報)を落とした残りが週間予報の欄に並ぶ。
    """
    d = _regional_json(page)
    if not d:
        return {}, "", ""
    data = ((d.get("provincial") or {}).get("data")) or {}
    out: dict = {}
    for code, p in data.items():
        if not isinstance(p, dict):
            continue
        days = []
        for o in (p.get("outlook") or [])[1:]:
            if not isinstance(o, dict):
                continue
            # 行を小さく保つため配列で持つ(PROVINCE_DAY の順)。空の値は null。
            days.append([o.get("day_low"), o.get("day_high"), o.get("day_wind_speed"),
                         o.get("day_wind_direction"), o.get("day_coastal_condition")])
        out[str(p.get("psgc_code") or code)] = {"name": p.get("name") or "", "days": days}
    default = data.get(str(d.get("default") or "")) or {}
    return out, default.get("name") or "", str(default.get("psgc_code") or "")


def parse_outlook(page: str, region: str) -> dict | None:
    """週間予報の欄 → 1 件(1 地域 × 1 発表)。欄が無い・読めないときは None(呼び出し側は記録して続ける)。"""
    at = page.find(_OUTLOOK_HEAD)
    if at < 0:
        return None
    end = _OUTLOOK_END.search(page, at)
    block = page[at:end.start() if end else at + 20000]
    issued = outlook_issued_iso(cell_text(block[:600]))
    if not issued:
        return None
    days = []
    chunks = _OUTLOOK_ITEM.split(block)[1:]
    for i, chunk in enumerate(chunks):
        name = _BOLD.search(chunk)
        title = _IMG_TITLE.search(chunk)
        vals = {}
        for label, value in _VALUES.findall(chunk):
            k = _LABELS.get(re.sub(r"[^a-z]", "", cell_text(label).lower()))
            if k:
                vals[k] = cell_text(value)
        days.append({
            "day_index": i, "name": cell_text(name.group(1)) if name else "",
            "tmin": _int(_LOW.search(chunk)), "tmax": _int(_HIGH.search(chunk)),
            "wind": vals.get("wind", ""), "direction": vals.get("direction", ""), "coastal": vals.get("coastal", ""),
            "sky": html.unescape(title.group(1)).strip() if title else "",
        })
    if not days or not all(d["name"] for d in days):
        return None
    provinces, pname, pcode = _provinces(page)
    return {"id": f"{region}:{issued}", "region": region, "issued_at": issued,
            "province": pname, "province_psgc": pcode, "days": days, "provinces": provinces}
