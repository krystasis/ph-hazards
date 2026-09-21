"""PHIVOLCS の火山警戒レベル(常時表示の帯から読む)。docs/sources/phivolcs-volcano.md"""
from __future__ import annotations

import re
from datetime import date

KEY = "phivolcs-volcano"
URL = "https://wovodat.phivolcs.dost.gov.ph/bulletin/list-of-bulletin"
MIN_INTERVAL_MIN = 59

FIELDS = ["date_pht", "volcano", "alert_level"]

_ITEM = re.compile(r'class="[a-z]+-scroll-level[^"]*"[^>]*>\s*([A-Za-z .\'-]+?)\s*-\s*(\d)\s*<', re.I)


def parse(page: str, today: date) -> list[dict]:
    return [
        {"date_pht": today.isoformat(), "volcano": name.strip(), "alert_level": level}
        for name, level in _ITEM.findall(page)
    ]
