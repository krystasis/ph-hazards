"""台風公報(data/tcb の本文)を構造化する。docs/sources/pagasa-tcb.md

入力は `pagasa_tcb.clean_text` で整えた本文(念のためここでもかける。整え済みなら何も変わらない)。
**本文に無い値は作らない。** 見つからない物は None / 空。

par_status(PAR = フィリピン責任領域)の決め方。上から順に最初に当たった物:
1. 中心の位置の文に「(OUTSIDE PAR)」がある、または見出しに「EXITED / HAS LEFT」→ 領域の外。
   さらに見出しか進路の見通しに「enter」(expected / forecast / likely / about to enter)があれば `entering`、無ければ `outside`
2. 見出しに「ABOUT TO EXIT / EXITING / ABOUT TO LEAVE / LEAVING」→ `exiting`
3. 中心の位置の文がある(PAGASA は領域の外の位置に必ず「(OUTSIDE PAR)」を付ける)→ `inside`
4. それ以外 → `unknown`

シグナル(Tropical Cyclone Wind Signal)の読み方は `parse_signals` の説明。**実物ではまだ確かめていない**
(2026-09 の Queenie は全公報が「No Tropical Cyclone Wind Signal」)。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from places.gazetteer import Gazetteer, key as _key, load as load_gazetteer

from .pagasa_tcb import clean_text

CATEGORIES = ("Super Typhoon", "Severe Tropical Storm", "Tropical Storm", "Tropical Depression", "Typhoon")
_CAT = "|".join(CATEGORIES)
_TITLE = re.compile(rf'^({_CAT})\s*["“”]([^"“”]+)["“”]', re.M | re.I)
_CENTER_CAT = re.compile(rf"The center of (?:the eye of )?({_CAT})\s+([A-Z][A-Za-z-]+)", re.I)
_ISSUED = re.compile(r"Issued at\s+(\d{1,2}):(\d{2})\s*([ap])\.?m\.?,?\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)
_NEXT = re.compile(r"next advisory to be issued at\s+(\d{1,2}):(\d{2})\s*([AP])\.?M\.?\s*,?\s*"
                   r"(today|tonight|tomorrow|(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}))", re.I)
_LATLON = re.compile(r"\(\s*(\d+(?:\.\d*)?)\s*°\s*N\s*,\s*(\d+(?:\.\d*)?)\s*°\s*E\s*\)")
_WIND = re.compile(r"Maximum sustained winds of\s+(\d+)\s*km/h", re.I)
_GUST = re.compile(r"gustiness of up to\s+(\d+)\s*km/h", re.I)
_FCST = re.compile(r"^([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*([AP])M\s*[-–]\s*(.+)$", re.M)
_OUTSIDE = re.compile(r"\(\s*OUTSIDE\s+(?:THE\s+)?PAR\s*\)", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], 1)}

# 見出しの区切り(本文での並び順)
_HEAD_LAND = "HAZARDS AFFECTING LAND AREAS"
_HEAD_COAST = "HAZARDS AFFECTING COASTAL WATERS"
_HEAD_TRACK = "TRACK AND INTENSITY OUTLOOK"
_PANELS = ("Location of Eye/center", "Movement", "Strength", "Forecast Position", "Wind Signal")
_CLOSING = "Considering these developments"


def _month(name: str) -> int | None:
    """「September」「Sep」→ 9。"""
    return {k[:3]: v for k, v in _MONTHS.items()}.get(name[:3].lower())


def _iso(y: int, mo: int, d: int, h: int, mi: int, ampm: str) -> str | None:
    h = h % 12 + (12 if ampm.lower() == "p" else 0)
    try:
        return datetime(y, mo, d, h, mi).isoformat() + "+08:00"
    except ValueError:
        return None


def _between(text: str, start: str, ends: tuple[str, ...]) -> str | None:
    """見出し start の次の行から、ends のどれかの見出しの前まで。見出しが無ければ None。"""
    m = re.search(rf"^{re.escape(start)}\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    cut = len(rest)
    for e in ends:
        n = re.search(rf"^{re.escape(e)}", rest, re.M)
        if n:
            cut = min(cut, n.start())
    return rest[:cut].strip()


def _first_line(block: str | None) -> str | None:
    if not block:
        return None
    for ln in block.split("\n"):
        if ln.strip():
            return ln.strip()
    return None


def _headline(text: str) -> str | None:
    """「(Valid for broadcast …)」の後の、全部大文字の最初の行。"""
    m = re.search(r"^\(Valid for broadcast.*$", text, re.M | re.I)
    rest = text[m.end():] if m else text
    for ln in rest.split("\n"):
        s = ln.strip()
        if not s or s in (_HEAD_LAND, _HEAD_COAST, _HEAD_TRACK):
            if s:
                break
            continue
        letters = re.sub(r"[^A-Za-z]", "", s)
        if len(letters) >= 10 and letters == letters.upper():
            return s
        break
    return None


def par_status(headline: str | None, center_text: str | None, outlook: str | None) -> str:
    """docstring の規則どおり。"""
    head = (headline or "").upper()
    if (center_text and _OUTSIDE.search(center_text)) or re.search(r"\b(HAS\s+)?(EXITED|LEFT)\b", head):
        words = f"{headline or ''}\n{outlook or ''}"
        if re.search(r"\b(expected|forecast|likely|about)\s+to\s+(re-?)?enter\b", words, re.I):
            return "entering"
        return "outside"
    if re.search(r"\b(ABOUT TO (EXIT|LEAVE)|EXITING|LEAVING)\b", head):
        return "exiting"
    if center_text:
        return "inside"
    return "unknown"


def not_bulletin(a: dict) -> str | None:
    """parse() の結果が公報として成立していなければ理由を返す(成立していれば None)。収集が保存の前に使う。

    公報の本文は必ず題(「Typhoon "Queenie"」)と発表時刻(「Issued at …」)で始まる(2026-09 の実物 14 件すべて)。
    発令が終わった後のページは過去の PDF の一覧(「TCB#1_queenie.pdf」…)だけになり、どちらも無い。
    """
    missing = [k for k in ("name", "issued_at") if not a.get(k)]
    return f"公報の題・発表時刻が無い({' / '.join(missing)})" if missing else None


def parse(text: str, gaz: Gazetteer | None = None) -> dict:
    text = clean_text(text)
    out: dict = {k: None for k in ("name", "category", "issued_at", "next_advisory_at", "headline", "par_status",
                                   "center_text", "center_lat", "center_lon", "movement", "max_wind_kmh", "gust_kmh",
                                   "land_hazards_text", "coastal_text", "outlook_text")}
    m = _TITLE.search(text)
    if m:
        out["category"] = next(c for c in CATEGORIES if c.lower() == m.group(1).lower())
        out["name"] = m.group(2).strip()
    m = _ISSUED.search(text)
    issued = None
    if m and (mo := _month(m.group(5))):
        out["issued_at"] = _iso(int(m.group(6)), mo, int(m.group(4)), int(m.group(1)), int(m.group(2)), m.group(3))
        issued = datetime.fromisoformat(out["issued_at"][:19]) if out["issued_at"] else None
    m = _NEXT.search(text)
    if m:
        h, mi, ap, when = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4).lower()
        if m.group(5):
            mo = _month(m.group(6))
            out["next_advisory_at"] = _iso(int(m.group(7)), mo, int(m.group(5)), h, mi, ap) if mo else None
        elif issued:
            day = issued + timedelta(days=1 if when == "tomorrow" else 0)
            out["next_advisory_at"] = _iso(day.year, day.month, day.day, h, mi, ap)
    out["headline"] = _headline(text)

    ends = (_HEAD_LAND, _HEAD_COAST, _HEAD_TRACK) + _PANELS + (_CLOSING,)
    out["land_hazards_text"] = _between(text, _HEAD_LAND, ends)
    out["coastal_text"] = _between(text, _HEAD_COAST, ends)
    out["outlook_text"] = _between(text, _HEAD_TRACK, ends)
    out["center_text"] = _first_line(_between(text, "Location of Eye/center", ends))
    if out["center_text"]:
        if (ll := _LATLON.search(out["center_text"])):
            out["center_lat"], out["center_lon"] = float(ll.group(1)), float(ll.group(2))
        if not out["category"] and (cm := _CENTER_CAT.search(out["center_text"])):
            out["category"] = next(c for c in CATEGORIES if c.lower() == cm.group(1).lower())
    out["movement"] = _first_line(_between(text, "Movement", ends))
    strength = _between(text, "Strength", ends) or ""
    if (w := _WIND.search(strength)):
        out["max_wind_kmh"] = int(w.group(1))
    if (g := _GUST.search(strength)):
        out["gust_kmh"] = int(g.group(1))

    fc = []
    for f in _FCST.finditer(_between(text, "Forecast Position", ends) or ""):
        mo = _month(f.group(1))
        at = _iso(int(f.group(3)), mo, int(f.group(2)), int(f.group(4)), int(f.group(5)), f.group(6)) if mo else None
        fc.append({"at": at, "text": f.group(7).strip(), "outside_par": bool(_OUTSIDE.search(f.group(7)))})
    out["forecast_positions"] = fc
    out["par_status"] = par_status(out["headline"], out["center_text"], out["outlook_text"])
    signal_text = _between(text, "Wind Signal", (_CLOSING,))
    out["signal_text"] = signal_text
    out["signals"] = parse_signals(signal_text or "", gaz)
    return out


# ---------------------------------------------------------------- シグナル

_SIGNAL = re.compile(r"(?:\bTCWS|\bWind\s+Signal|\bSignal)\s*(?:No\.?|Number|#)\s*(\d)\b", re.I)
_ISLAND_HEAD = re.compile(r"(?:^|\n|(?<=\s))(Luzon|Visayas|Mindanao)\s*(?::|\n|$)", re.I)
# 地域の塊の後に並ぶ説明の欄(Wind threat など)。ここから先は場所ではない。
_DESCRIPTOR = re.compile(r"\b(Wind threat|Warning lead time|Range of wind speeds|Potential impacts?|Beaufort)\b", re.I)
_PORTION = re.compile(
    r"^(?:the\s+)?(?P<dir>(?:extreme\s+|central\s+|mainland\s+)?"
    r"(?:(?:north|south|east|west|central|north-?eastern|north-?western|south-?eastern|south-?western|"
    r"northern|southern|eastern|western|northeastern|northwestern|southeastern|southwestern)"
    r"(?:\s+and\s+(?:extreme\s+)?(?:northern|southern|eastern|western|central|northeastern|northwestern|"
    r"southeastern|southwestern))?)\s+portions?)\s+of\s+(?P<prov>.+)$", re.I)
_REST = re.compile(r"^(?:the\s+)?rest\s+of\s+(?P<prov>.+)$", re.I)
# PAGASA が州の代わりに書く島々 → その島々が属する州(地理の事実。PSGC に州として無いので手で持つ)
ISLAND_GROUPS = {
    "babuyanislands": "Cagayan", "polilloislands": "Quezon", "calamianislands": "Palawan", "cuyoislands": "Palawan",
    "kalayaanislands": "Palawan", "camotesislands": "Cebu", "bantayanislands": "Cebu", "buriasisland": "Masbate",
    "ticaoisland": "Masbate", "siargaoisland": "Surigao del Norte", "siargaoislands": "Surigao del Norte",
    "bucasgrandeislands": "Surigao del Norte", "caluyaislands": "Antique", "cuyo": "Palawan",
}


def _split_top(s: str) -> list[str]:
    """括弧の外のコンマ・セミコロン・「and」で区切る。「northern and central portions」の and は区切らない。"""
    parts, depth, buf, i = [], 0, "", 0
    while i < len(s):
        ch = s[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if depth == 0:
            if ch in ",;":
                parts.append(buf)
                buf, i = "", i + 1
                continue
            m = re.match(r"\s+and\s+(?=the\s|[A-Z])", s[i:])
            if m:
                parts.append(buf)
                buf, i = "", i + m.end()
                continue
        buf += ch
        i += 1
    parts.append(buf)
    return [p.strip(" .\n\t") for p in parts if p.strip(" .\n\t")]


def _towns(inner: str) -> list[str]:
    out = []
    for p in re.split(r",|;|\s+and\s+", inner):
        p = re.sub(r"^and\s+", "", p.strip(" .\n\t"), flags=re.I)
        if p:
            out.append(p)
    return out


def _province(name: str, g: Gazetteer):
    """州名(「mainland Cagayan」「Metro Manila」も)→ (Place か None, province_code)。"""
    n = re.sub(r"^mainland\s+", "", name.strip(), flags=re.I)
    if g.region_code(n) == "1300000000":
        return None, "1300000000"   # Metro Manila は地域コード(province_outlook と同じ扱い)
    p = g.province(n)
    return (p, p.code) if p else (None, None)


def parse_signals(section: str, gaz: Gazetteer | None = None) -> list[dict]:
    """「Wind Signal」の欄 → [{signal, area, area_kind, province_code, city_code}]。

    前提にしている書式(PAGASA が公表している TCB の書式から。**実物では未確認**):
    - 「TCWS No. N」「Wind Signal No. N」「Signal No. N」のどれかの後に、その段階の地域が並ぶ。
      「Luzon」「Visayas」「Mindanao」の島の見出しは読み飛ばす。「Wind threat」などの説明の欄からは場所として読まない。
    - 地域はコンマと「and」で区切る。1 つずつ:
      - 州名 → area_kind=province(Metro Manila は地域コード 1300000000 を province_code に入れる)
      - 「the northern portion of X (Town1, Town2)」→ area_kind=portion の行(province_code=X)と、
        括弧の中の町ごとに area_kind=city の行(X を手がかりに市町コードを当てる)
      - 「the rest of X」→ area_kind=portion の行(province_code=X)。**X のうち、より高い段階に名前が出ていない町すべて**の意味
      - 「Babuyan Islands」などの島々 → area_kind=portion、province_code は属する州(ISLAND_GROUPS)
      - 州でない名前 → 市町として全国で一意なら area_kind=city。当たらなければ area_kind=portion でコードは空
    - 同じ段階に同じ名前が 2 回出たら、2 回目以降は「, 州名」を付けて主キー (sha, signal, area) を分ける。
    """
    if not section or re.search(r"No Tropical Cyclone Wind Signal", section, re.I):
        return []
    g = gaz or load_gazetteer()
    marks = list(_SIGNAL.finditer(section))
    out: list[dict] = []
    seen: set[tuple] = set()

    def add(sig: int, area: str, kind: str, prov: str | None, city: str | None, prov_name: str = "") -> None:
        key = (sig, area)
        if key in seen and prov_name:
            area = f"{area}, {prov_name}"
            key = (sig, area)
        if key in seen:
            return
        seen.add(key)
        out.append({"signal": sig, "area": area, "area_kind": kind, "province_code": prov, "city_code": city})

    for i, m in enumerate(marks):
        sig = int(m.group(1))
        block = section[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(section)]
        if (d := _DESCRIPTOR.search(block)):
            block = block[: d.start()]
        block = _ISLAND_HEAD.sub(", ", block)
        block = re.sub(r"\s+", " ", block).strip(" :,-–")
        for item in _split_top(block):
            item = re.sub(r"^and\s+", "", item, flags=re.I).strip()
            paren = re.search(r"\((.*)\)\s*$", item)
            head = item[: paren.start()].strip() if paren else item
            pm, rm = _PORTION.match(head), _REST.match(head)
            if pm or rm:
                pname = (pm or rm).group("prov").strip()
                place, pcode = _province(pname, g)
                if not pcode and (isl := ISLAND_GROUPS.get(_key(pname))):
                    place, pcode = _province(isl, g)
                add(sig, head, "portion", pcode, None)
                if paren:
                    for t in _towns(paren.group(1)):
                        c = g.city(t, province=place) if place else g.city(t)
                        add(sig, t, "city", c.province_code if c else pcode, c.code if c else None,
                            place.name if place else pname)
                continue
            place, pcode = _province(head, g)
            if pcode:
                add(sig, head, "province", pcode, None)
                if paren:   # 「Cagayan (Santa Ana, Gonzaga)」のような書き方も町として拾う
                    for t in _towns(paren.group(1)):
                        c = g.city(t, province=place) if place else None
                        add(sig, t, "city", c.province_code if c else pcode, c.code if c else None, head)
                continue
            if (isl := ISLAND_GROUPS.get(_key(head))):
                _, pcode = _province(isl, g)
                add(sig, head, "portion", pcode, None)
                continue
            c = g.city(head)
            if c:
                add(sig, head, "city", c.province_code, c.code)
            else:
                add(sig, item, "portion", None, None)
    return out
