"""PAGASA のダム水位(1 日 1 回、朝 8 時の値)と流域の洪水監視状況。docs/sources/pagasa-flood.md"""
from __future__ import annotations

import re
from datetime import date, datetime

from .htmlutil import cell_text

KEY = "pagasa-flood"
URL = "https://www.pagasa.dost.gov.ph/flood"
MIN_INTERVAL_MIN = 170

DAM_FIELDS = [
    "dam", "obs_date", "obs_time", "rwl_m", "dev_24h_m", "nhwl_m", "dev_nhwl_m",
    "rule_curve_m", "dev_rule_curve_m", "gates", "gate_opening_m", "inflow_cms", "outflow_cms",
]
WATCH_FIELDS = ["date_pht", "sub_basin", "status"]

_TD = re.compile(r'<td\s+data-id="([^"]+)"[^>]*>(.*?)</td>', re.S | re.I)
_WATCH = re.compile(
    r"<tr>\s*<td>([^<]+?Sub-basin)</td>\s*<td[^>]*>\s*<a[^>]*>([^<]+)</a>", re.S | re.I
)


def _obs_date(label: str, today: date) -> str:
    """'Sep-21' に年を足す。年をまたぐ 1 月初めは前年 12 月を正しく戻す。"""
    try:
        d = datetime.strptime(f"{label}-{today.year}", "%b-%d-%Y").date()
    except ValueError:
        return ""
    if (d - today).days > 2:
        d = d.replace(year=today.year - 1)
    return d.isoformat()


def parse(page: str, today: date) -> tuple[list[dict], list[dict]]:
    by_dam: dict[str, list[str]] = {}
    for dam, frag in _TD.findall(page):
        by_dam.setdefault(dam, []).append(cell_text(frag))

    dams: list[dict] = []
    for dam, c in by_dam.items():
        # 1 ダム 4 行(rowspan)。今日 14 セル + 前日 10 セル。
        if len(c) < 14:
            continue
        dams.append(dict(zip(DAM_FIELDS, [dam, _obs_date(c[13], today), c[1], c[2], c[4], c[5], c[6], c[7], c[8], c[9], c[10], c[11], c[12]])))
        if len(c) >= 24:
            dams.append(dict(zip(DAM_FIELDS, [dam, _obs_date(c[23], today), c[14], c[15], "", c[5], c[16], c[17], c[18], c[19], c[20], c[21], c[22]])))
    dams = [d for d in dams if d["obs_date"] and d["rwl_m"]]

    watch = [
        {"date_pht": today.isoformat(), "sub_basin": cell_text(n), "status": cell_text(s)}
        for n, s in _WATCH.findall(page)
    ]
    return dams, watch
