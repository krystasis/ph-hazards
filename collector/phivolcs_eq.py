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
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def archive_url(month: str) -> str:
    """'2018-01' → 月別ページの URL。"""
    y, m = month.split("-")
    return f"{URL}EQLatest-Monthly/{y}/{y}_{_MONTHS[int(m) - 1]}.html"


def _num(s: str) -> str:
    s = s.strip()
    return str(float(s)) if re.fullmatch(r"-?\d+(\.\d+)?", s) else ""


def parse(page: str) -> list[dict]:
    rows: dict[str, dict] = {}
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
        lat, lon = _num(cell_text(cells[1])), _num(cell_text(cells[2]))
        # リンク先のファイル名は ID に使えない(古い月では別々の地震が同じリンクを共有している)。
        # 地震そのもの(発生時刻 + 震央)から作る。
        event_id = f"{dt:%Y%m%dT%H%M}_{lat}_{lon}"
        rows[event_id] = {
            "event_id": event_id,
            "datetime_pht": dt.strftime("%Y-%m-%dT%H:%M:00+08:00"),
            "lat": lat,
            "lon": lon,
            "depth_km": _num(cell_text(cells[3])),
            "mag": _num(cell_text(cells[4])),
            "location": cell_text(cells[5]),
            "bulletin": re.sub(r"^[./\\]+", "", href.group(1).replace("\\", "/")),
        }
    return list(rows.values())


def month_of(row: dict) -> str:
    return row["datetime_pht"][:7]
