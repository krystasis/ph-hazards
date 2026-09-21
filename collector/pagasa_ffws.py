"""Pasig-Marikina-Tullahan 流域の河川水位(PAGASA FFWS、10 分値)。docs/sources/pagasa-ffws.md"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

KEY = "pagasa-ffws"
URL = "https://pasig-marikina-tullahanffws.pagasa.dost.gov.ph/water/table_list.do"
MIN_INTERVAL_MIN = 14
KEEPALIVE_MIN = 60  # 値が動かなくても、この間隔では 1 行残す

FIELDS = ["time_pht", "station_code", "station", "wl_m", "flag", "alert_m", "alarm_m", "critical_m"]

_WL = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(\(\*\))?\s*$")


def slot(now_pht: datetime, back_min: int = 10) -> datetime:
    """観測は 10 分刻み。少し前の刻みを聞く(直近はまだ入っていないことがある)。"""
    t = now_pht - timedelta(minutes=back_min)
    return t.replace(minute=t.minute - t.minute % 10, second=0, microsecond=0)


def parse(body: str, at: datetime) -> list[dict]:
    rows = []
    for s in json.loads(body):
        m = _WL.match(s.get("wl") or "")
        if not m:
            continue
        rows.append({
            "time_pht": at.strftime("%Y-%m-%dT%H:%M:00+08:00"),
            "station_code": s.get("obscd") or "",
            "station": s.get("obsnm") or "",
            "wl_m": m.group(1),
            "flag": "*" if m.group(2) else "",  # 画面上の (*)。意味は未確認(推定値か欠測の持ち越し)
            "alert_m": s.get("alertwl") or "",
            "alarm_m": s.get("alarmwl") or "",
            "critical_m": s.get("criticalwl") or "",
        })
    return rows
