"""PAGASA 地域別ページの豪雨警報・雷雨注意報(市町名つき)。docs/sources/pagasa-regional.md"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from .htmlutil import block_text, inner_html_by_id

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
