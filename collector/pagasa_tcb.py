"""PAGASA の台風公報。発令中だけ本文を丸ごと残す(シグナルの構造化は実物が出てから)。docs/sources/pagasa-tcb.md"""
from __future__ import annotations

import hashlib
import re

from .htmlutil import block_text

KEY = "pagasa-tcb"
URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin"
MIN_INTERVAL_MIN = 29

_NO_ACTIVE = re.compile(r"No Active Tropical Cyclone", re.I)
_BODY = re.compile(r'<div class="[^"]*article-content[^"]*">(.*)', re.S | re.I)
_CUT = re.compile(r"We always find ways to improve|<footer", re.I)


def parse(page: str) -> dict | None:
    """発令なしなら None。"""
    m = _BODY.search(page)
    body = m.group(1) if m else page
    cut = _CUT.search(body)
    if cut:
        body = body[: cut.start()]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    text = block_text(body)
    if _NO_ACTIVE.search(text) or len(text) < 200:
        return None
    return {"sha": hashlib.sha256(text.encode()).hexdigest()[:16], "text": text}
