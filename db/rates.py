"""市町ごとの地震の頻度(50 km 圏のベースレート)。

「次の地震がいつ起きるか」は誰にも予測できない。ここで出すのは「この町の周りでは、これまでどれくらいの頻度で
起きてきたか」と、その頻度が続くと仮定したときの「30 日以内に 1 回以上ある確率」(ポアソン近似)だけ。
地震は群発するので、実際には静かな期間はもっと静かで、活発な期間はもっと活発になる。サイトではその旨を必ず書く。

完全性: PHIVOLCS の掲載は M1〜2 で年によって大きく違う(2018 年の M1 は 397 件、2025 年は 6,768 件)が、
M3 以上は 2019 年以降ほぼ一定(年 2,600〜3,100 件)。数えるのは M3.0 以上、期間は 2019-01-01 から。
"""
from __future__ import annotations

import bisect
import json
import math
from datetime import date

from places.gazetteer import load

RADIUS_KM = 50
SINCE = "2019-01-01"
MIN_MAG = 3.0
KY = 110.57


def city_rates(events, today: date | None = None) -> list[dict]:
    """events: earthquakes の行(occurred_at, lat, lon, mag)。全市町(SubMun を除く)の 1 行ずつを返す。"""
    pts = []
    for e in events:
        try:
            lat, lon, mag = float(e["lat"]), float(e["lon"]), float(e["mag"])
        except (TypeError, ValueError):
            continue
        if e["occurred_at"] < SINCE or mag < MIN_MAG:
            continue
        pts.append((lat, lon, mag, e["occurred_at"]))
    if not pts:
        return []
    pts.sort()
    lats = [p[0] for p in pts]
    until = max(p[3] for p in pts)[:10]
    if today:
        until = max(until, today.isoformat())
    years = max(0.5, (date.fromisoformat(until) - date.fromisoformat(SINCE)).days / 365.25)

    out = []
    for c in load().cities.values():
        if c.lat is None or c.level == "SubMun":
            continue
        dlat = RADIUS_KM / KY
        kx = 111.32 * math.cos(math.radians(c.lat))
        lo, hi = bisect.bisect_left(lats, c.lat - dlat), bisect.bisect_right(lats, c.lat + dlat)
        n3 = n4 = n5 = 0
        last4 = last5 = ""
        by_year: dict[str, int] = {}
        for lat, lon, mag, at in pts[lo:hi]:
            dx, dy = (lon - c.lon) * kx, (lat - c.lat) * KY
            if dx * dx + dy * dy > RADIUS_KM * RADIUS_KM:
                continue
            n3 += 1
            if mag >= 4.0:
                n4 += 1
                last4 = max(last4, at)
                by_year[at[:4]] = by_year.get(at[:4], 0) + 1
            if mag >= 5.0:
                n5 += 1
                last5 = max(last5, at)
        r4 = n4 / years
        out.append({
            "city_code": c.code, "radius_km": str(RADIUS_KM), "since": SINCE, "until_": until, "years": f"{years:.2f}",
            "n_m3": str(n3), "n_m4": str(n4), "n_m5": str(n5), "m4_per_year": f"{r4:.3f}",
            "p30_m4": f"{1 - math.exp(-r4 * 30 / 365.25):.4f}", "p365_m4": f"{1 - math.exp(-r4):.4f}",
            "last_m4_at": last4, "last_m5_at": last5,
            "m4_by_year": json.dumps({str(y): by_year.get(str(y), 0) for y in range(int(SINCE[:4]), int(until[:4]) + 1)}, separators=(",", ":")),
        })
    return out
