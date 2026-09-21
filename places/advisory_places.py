"""PAGASA の注意報の本文から、対象の州・市町を PSGC のコードで取り出す。

書き方は 2 通りある(2026-09 の実物):
  NCR:      "... expected over Bataan (Limay, Mariveles, and Orion), Metro Manila (Quezon City), and Zambales (Iba) within ..."
  他の地域: "... expected over #Bohol(SierraBullones, Pilar) and #Cebu(CebuCity) within ..."
括弧が無い州(または地域)は全域を指す。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gazetteer import Gazetteer, Place, load

# (開始の言い回し, 状態)。終わりは within / which may / 文末。
_LEADS = [
    (r"(?:is|are)\s+expected\s+over", "expected"),
    (r"(?:is|are)\s+being\s+experienced\s+(?:in|over)", "occurring"),
    (r"(?:is|are)\s+affecting", "occurring"),
    (r"(?:MORE|LESS)\s+LIKELY\s+to\s+develop\s+over", "watch"),
]
# 文末は「.」で判定しない(「Gen. Mariano Alvarez」がある)。段落ごとに見て、決まった言い回しか段落の終わりで切る。
_END = r"(?=\s+(?:within|which\s+may|and\s+may|for\s+the\s+next)\b|\.?\s*$)"
_ENTRY = re.compile(r"#?\s*([A-Za-z][A-Za-z .'\-]*?)\s*(?:\(([^)]*)\)|(?=,|$))")


@dataclass
class Area:
    status: str                      # expected / occurring / watch
    likelihood: str = ""             # watch のときの MORE / LESS
    province: Place | None = None
    region_code: str = ""
    whole: bool = False              # 州(地域)の全域
    cities: list[Place] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def _split_top(s: str) -> list[str]:
    """括弧の外のカンマと and で区切る。"""
    out, depth, cur = [], 0, ""
    for tok in re.split(r"(\(|\)|,|\band\b)", s):
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        if depth == 0 and tok in (",", "and"):
            out.append(cur)
            cur = ""
        else:
            cur += tok
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def _towns(s: str) -> list[str]:
    return [x.strip() for x in re.split(r",|\band\b", s) if x.strip()]


def extract(text: str, gaz: Gazetteer | None = None) -> list[Area]:
    gaz = gaz or load()
    areas: list[Area] = []
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    for flat, (lead, status) in ((p, ls) for p in paragraphs for ls in _LEADS):
        for m in re.finditer(lead + r"\s+(.+?)" + _END, flat, flags=re.I):
            likelihood = "MORE" if "MORE" in m.group(0).upper().split("LIKELY")[0] else ("LESS" if status == "watch" else "")
            for entry in _split_top(m.group(1)):
                em = re.match(r"^#?\s*(?:the\s+)?(?:portions?\s+of\s+|rest\s+of\s+)?([^()]+?)\s*(?:\((.*)\))?$", entry, flags=re.I)
                if not em:
                    areas.append(Area(status=status, unmatched=[entry]))  # 読めなかった塊は黙って捨てず、外れとして残す
                    continue
                name, inside = em.group(1).strip(), em.group(2)
                area = Area(status=status, likelihood=likelihood if status == "watch" else "")
                area.province = gaz.province(name)
                if not area.province:
                    area.region_code = gaz.region_code(name) or ""
                if not area.province and not area.region_code:
                    # 「#DavaoCity」のように、州の位置に独立市が直接書かれることがある。
                    city = gaz.city(name)
                    if city:
                        area.cities.append(city)
                    else:
                        area.unmatched.append(name)
                    areas.append(area)
                    continue
                if inside is None:
                    area.whole = True
                else:
                    for town in _towns(inside):
                        c = gaz.city(town, area.province, area.region_code or None)
                        (area.cities if c else area.unmatched).append(c or town)
                areas.append(area)
    return areas


def city_codes(areas: list[Area], gaz: Gazetteer | None = None) -> dict[str, str]:
    """市町コード → 状態。全域指定は市町に展開する。occurring が expected / watch より優先。"""
    gaz = gaz or load()
    rank = {"watch": 0, "expected": 1, "occurring": 2}
    out: dict[str, str] = {}
    for a in areas:
        targets = list(a.cities)
        if a.whole:
            targets = gaz.cities_in_province(a.province.code) if a.province else gaz.cities_in_region(a.region_code)
        for c in targets:
            if rank[a.status] >= rank.get(out.get(c.code, "watch"), 0) or c.code not in out:
                out[c.code] = a.status
    return out
