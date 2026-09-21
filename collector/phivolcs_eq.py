"""PHIVOLCS の地震一覧(当月分が 1 ページ)。docs/sources/phivolcs-eq.md"""
from __future__ import annotations

import re
from datetime import datetime

from .htmlutil import cell_text

KEY = "phivolcs-eq"
URL = "https://earthquake.phivolcs.dost.gov.ph/"
MIN_INTERVAL_MIN = 14

FIELDS = ["event_id", "datetime_pht", "lat", "lon", "depth_km", "mag", "location", "bulletin"]

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_HREF = re.compile(r'href="([^"]+\.html)"', re.I)
# 通常は 分 まで(2026_0921_0058)。同じ分に別の地震があると 秒 まで付く(2026_0920_201041)。
_STEM = re.compile(r"(\d{4}_\d{4}_\d{4,6})")


def _num(s: str) -> str:
    s = s.strip()
    return str(float(s)) if re.fullmatch(r"-?\d+(\.\d+)?", s) else ""


def parse(page: str) -> list[dict]:
    rows: list[dict] = []
    for m in _ROW.finditer(page):
        body = m.group(1)
        href = _HREF.search(body)
        cells = _TD.findall(body)
        if not href or len(cells) < 6:
            continue
        when = cell_text(cells[0])
        try:
            dt = datetime.strptime(when, "%d %B %Y - %I:%M %p")
        except ValueError:
            continue
        bulletin = href.group(1).replace("\\", "/")
        stem = _STEM.search(bulletin)
        rows.append(
            {
                # 速報(B1)が確報(B2)に差し替わっても同じ地震として上書きできるよう、版の接尾辞は外す。
                "event_id": stem.group(1) if stem else dt.strftime("%Y_%m%d_%H%M") + "_pht",
                "datetime_pht": dt.strftime("%Y-%m-%dT%H:%M:00+08:00"),
                "lat": _num(cell_text(cells[1])),
                "lon": _num(cell_text(cells[2])),
                "depth_km": _num(cell_text(cells[3])),
                "mag": _num(cell_text(cells[4])),
                "location": cell_text(cells[5]),
                "bulletin": bulletin,
            }
        )
    return rows


def month_of(row: dict) -> str:
    return row["datetime_pht"][:7]
