"""PSGC の州・市町を、表記ゆれに強い鍵で引けるようにする。

鍵 = 小文字の英数字だけ(空白・記号・アクセントを落とす)。PAGASA の「#SierraBullones」も
PSGC の「Sierra Bullones」も同じ鍵 `sierrabullones` になる。
"""
from __future__ import annotations

import difflib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "psgc"
ALIASES = Path(__file__).resolve().parent / "aliases.json"

_ABBR = [
    (r"\bgen\b\.?", "general"), (r"\bsto\b\.?", "santo"), (r"\bsta\b\.?", "santa"),
    (r"\bpres\b\.?", "president"), (r"\bmt\b\.?", "mount"), (r"\bst\b\.?", "saint"),
]
_DROP = [r"\(.*?\)", r"^city of\s+", r"^municipality of\s+", r"\s+city$"]

# PAGASA が使う呼び名 → PSGC の地域コード(州より上の単位で書かれることがある)。
REGION_ALIASES = {
    "metromanila": "1300000000", "ncr": "1300000000", "nationalcapitalregion": "1300000000",
    "bicolregion": "0500000000", "ilocosregion": "0100000000", "cagayanvalley": "0200000000",
    "centralluzon": "0300000000", "calabarzon": "0400000000", "mimaropa": "1700000000",
    "westernvisayas": "0600000000", "centralvisayas": "0700000000", "easternvisayas": "0800000000",
    "zamboangapeninsula": "0900000000", "northernmindanao": "1000000000", "davaoregion": "1100000000",
    "soccsksargen": "1200000000", "caraga": "1600000000", "cordilleraadministrativeregion": "1400000000",
    "car": "1400000000", "negrosislandregion": "1800000000", "barmm": "1900000000", "bangsamoro": "1900000000",
}
# 州名の別表記。
PROVINCE_ALIASES = {
    "samar": "westernsamar", "westernsamar": "samar", "compostelavalley": "davaodeoro",
    "northcotabato": "cotabato", "mtprovince": "mountainprovince",
}


def key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s).lower()  # 「CebuCity」→「cebu city」
    for pat in _DROP:
        s = re.sub(pat, " ", s).strip()
    for pat, full in _ABBR:
        s = re.sub(pat, full, s)
    return re.sub(r"[^a-z0-9]", "", s)


@dataclass(frozen=True)
class Place:
    code: str
    name: str
    level: str  # Reg / Prov / City / Mun / SubMun
    province_code: str
    region_code: str
    lat: float | None
    lon: float | None


def _coord(rec: dict) -> tuple[float | None, float | None]:
    c = rec.get("coordinate") or {}
    return c.get("latitude"), c.get("longitude")


class Gazetteer:
    def __init__(self) -> None:
        provinces = json.loads((VENDOR / "provinces.json").read_text())
        cities = json.loads((VENDOR / "cities.json").read_text())
        self.provinces: dict[str, Place] = {}
        self.cities: dict[str, Place] = {}
        self.province_by_key: dict[str, Place] = {}
        self.cities_by_key: dict[str, list[Place]] = {}
        for r in provinces:
            p = Place(r["psgc_code"], r["name"], "Prov", r["psgc_code"], r["region_code"], *_coord(r))
            self.provinces[p.code] = p
            if "(" not in r["name"]:  # 「City of Cebu (Independent City)」のような擬似州は州名として引かせない
                self.province_by_key[key(r["name"])] = p
        for a, b in PROVINCE_ALIASES.items():
            if b in self.province_by_key:
                self.province_by_key.setdefault(a, self.province_by_key[b])
        for r in cities:
            c = Place(r["psgc_code"], r["name"], r["geographic_level"], r["province_code"], r["region_code"], *_coord(r))
            self.cities[c.code] = c
            self.cities_by_key.setdefault(key(r["name"]), []).append(c)
        # 手で足す対応表(バランガイ名や旧称で書かれる物)。"州の鍵|名前の鍵" → 市町コード
        self.aliases: dict[str, str] = {}
        if ALIASES.exists():
            for entry in json.loads(ALIASES.read_text()):
                prov = self.province(entry["province"])
                towns = [c for c in self.cities_by_key.get(key(entry["is_in"]), []) if prov and c.province_code == prov.code]
                if towns:
                    self.aliases[f"{key(prov.name)}|{key(entry['written_as'])}"] = towns[0].code

    def province(self, name: str) -> Place | None:
        return self.province_by_key.get(key(name))

    def region_code(self, name: str) -> str | None:
        return REGION_ALIASES.get(key(name))

    def cities_in_province(self, province_code: str) -> list[Place]:
        return [c for c in self.cities.values() if c.province_code == province_code]

    def cities_in_region(self, region_code: str) -> list[Place]:
        return [c for c in self.cities.values() if c.region_code == region_code and c.level != "SubMun"]

    def city(self, name: str, province: Place | None = None, region_code: str | None = None) -> Place | None:
        """州(または地域)の中で探し、無ければ近くの独立市、最後に全国で一意な名前を当てる。"""
        k = key(name)
        if province and (hit := self.aliases.get(f"{key(province.name)}|{k}")):
            return self.cities.get(hit)
        cands = self.cities_by_key.get(k, [])
        if not cands and province:
            # 綴りの小さな違い(「Remedios Romualdez」と「Remedios T. Romualdez」)。州の中だけで、近い物が 1 つのときに限る。
            local = {key(c.name): c for c in self.cities_in_province(province.code)}
            close = difflib.get_close_matches(k, list(local), n=2, cutoff=0.88)
            if len(close) == 1:
                return local[close[0]]
        if not cands:
            return None
        if province:
            inside = [c for c in cands if c.province_code == province.code]
            if inside:
                return inside[0]
            # PAGASA は独立市(Angeles、Cebu City など)を元の州の中に書く。PSGC では州の外。
            near = [c for c in cands if c.region_code == province.region_code and _km(c, province) < 120]
            if near:
                return min(near, key=lambda c: _km(c, province))
        if region_code:
            inside = [c for c in cands if c.region_code == region_code]
            if inside:
                return inside[0]
        return cands[0] if len(cands) == 1 and not province and not region_code else None


def _km(a: Place, b: Place) -> float:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return 1e9
    dlat, dlon = math.radians(a.lat - b.lat), math.radians(a.lon - b.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a.lat)) * math.cos(math.radians(b.lat)) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


@lru_cache(maxsize=1)
def load() -> Gazetteer:
    return Gazetteer()
