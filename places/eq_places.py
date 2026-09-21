"""PHIVOLCS の地震の location("005 km S 24° E of Kalamansig (Sultan Kudarat)")を市町に紐づける。

基準点の町であって震央の町ではない(沖合の地震は最寄りの町からの距離で書かれる)。ページでは
「○○町の近く」として出す。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .gazetteer import Gazetteer, Place, load

# 距離は「1 49 km」のように途中に空白が入ることがある(取得元の打ち間違い)。
_LOC = re.compile(r"^\s*(\d[\d ]*?)\s*k?m\s+(.*?)\s+of\s+(.+?)\s*$", re.I)
_PAREN = re.compile(r"\(([^()]*)\)")


@dataclass
class EqPlace:
    distance_km: int | None
    bearing: str
    city: Place | None
    province: Place | None
    raw_town: str


def resolve(location: str, gaz: Gazetteer | None = None) -> EqPlace:
    gaz = gaz or load()
    m = _LOC.match(location)
    rest = m.group(3) if m else location
    groups = _PAREN.findall(rest)
    town = _PAREN.sub("", rest).strip(" ,")
    province = None
    for g in reversed(groups):  # 最後の括弧が州。手前の括弧は「Municipality Of Sarangani」のような補足
        province = gaz.province(g)
        if province:
            break
    candidates = [town] + [re.sub(r"^municipality of\s+", "", g, flags=re.I) for g in groups]
    city = None
    for name in candidates:
        city = gaz.city(name, province)
        if city:
            break
    return EqPlace(int(m.group(1).replace(" ", "")) if m else None, re.sub(r"\s+", " ", m.group(2)).strip() if m else "", city, province, town)
