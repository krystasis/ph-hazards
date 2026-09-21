"""公開側のデータファイルから D1 へ送る SQL を作る。**前回から変わった行だけ**を出す。

D1 の無料枠は 1 日 10 万行の書き込み。月のファイルを毎回丸ごと送ると地震だけで超えるので、
行ごとのハッシュを manifest に持ち、新規と変更だけを INSERT OR REPLACE する。

SQL は `plan()` が「単位(Unit)」に区切って返す。単位は *全部送れたときだけ* manifest を進める
最小のかたまりで、表 1 つか、地震の 1 か月ぶん。途中で失敗しても、送れた単位までは記録が進み、
残りは次の回が送り直す(`db/send.py`)。

    python3 -m db.export data --manifest state/d1-manifest.json --out out.sql
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from places.advisory_places import city_codes, extract
from places.eq_places import resolve

MAX_SQL_BYTES = 90_000  # D1 は 1 文 100KB まで

COLUMNS = {
    "earthquakes": ["event_id", "occurred_at", "lat", "lon", "depth_km", "mag", "location",
                    "city_code", "province_code", "distance_km", "bearing", "row_hash"],
    "city_quake_stats": ["city_code", "total", "m4_plus", "max_mag", "max_mag_at", "first_at", "last_at"],
    "advisories": ["id", "region", "kind", "title", "number", "issued_at", "expires_at", "text", "first_seen"],
    "advisory_cities": ["advisory_id", "city_code", "status", "expires_at"],
    "dam_levels": ["dam", "obs_date", "obs_time", "rwl_m", "dev_24h_m", "nhwl_m", "dev_nhwl_m", "rule_curve_m",
                   "dev_rule_curve_m", "gates", "gate_opening_m", "inflow_cms", "outflow_cms"],
    "flood_watch": ["date_pht", "sub_basin", "status"],
    "river_levels": ["station_code", "time_pht", "station", "wl_m", "flag", "alert_m", "alarm_m", "critical_m"],
    "volcano_alert": ["volcano", "date_pht", "alert_level"],
    "cyclone_bulletins": ["sha", "fetched_utc", "text"],
    "source_status": ["source", "last_ok", "last_fetch", "note"],
}
KEYS = {
    "earthquakes": ["event_id"], "city_quake_stats": ["city_code"], "advisories": ["id"],
    "advisory_cities": ["city_code", "advisory_id"], "dam_levels": ["dam", "obs_date"],
    "flood_watch": ["sub_basin", "date_pht"], "river_levels": ["station_code", "time_pht"],
    "volcano_alert": ["volcano", "date_pht"], "cyclone_bulletins": ["sha"], "source_status": ["source"],
}
NUMERIC = {"lat", "lon", "depth_km", "mag", "distance_km", "total", "m4_plus", "max_mag", "rwl_m", "dev_24h_m",
           "nhwl_m", "dev_nhwl_m", "rule_curve_m", "dev_rule_curve_m", "wl_m", "alert_m", "alarm_m", "critical_m",
           "alert_level"}

# 追記しかされない表は、行ごとのハッシュを持たずに「どこまで送ったか」だけ覚える(manifest を小さく保つ)。
WATERMARK = {"river_levels": "time_pht", "cyclone_bulletins": "fetched_utc", "advisories": None, "advisory_cities": None}
# 送る順。新しいデータを過去分の積み残しで待たせないため、小さい表を先に置く(地震はこの後ろ)。
APPEND_ORDER = ("advisories", "advisory_cities", "river_levels", "cyclone_bulletins")
ROWHASH_ORDER = ("source_status", "city_quake_stats", "dam_levels", "flood_watch", "volcano_alert")
RECENT_MONTHS = 2  # 地震は直近 2 か月だけ行ごとに比べ、それより古い月は月の要約で比べる

_HOURS = re.compile(r"(\d+)\s*(?:to\s*(\d+)\s*)?hours?|an\s+hour", re.I)


def _csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _expires(issued_at: str, text: str) -> str:
    """本文に出てくる時間のうち最長を有効時間とみなす。読めなければ 3 時間。"""
    hours = [max(int(a or 1), int(b or 0)) if (a or b) else 1 for a, b in _HOURS.findall(text)]
    if not issued_at:
        return ""
    dt = datetime.fromisoformat(issued_at) + timedelta(hours=max(hours) if hours else 3)
    return dt.isoformat()


def source_status(state: Path) -> dict[tuple, dict]:
    """`state/<key>.json` → 取得元ごとの鮮度(ページの「○時○分現在」)。

    取得元ではないファイル(過去分の進捗、D1 への送信状態)は last_fetch を持たないので外れる。
    """
    rows: dict[tuple, dict] = {}
    if not state.is_dir():
        return rows
    for f in sorted(state.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(d, dict) or "last_fetch" not in d:
            continue
        rows[(f.stem,)] = {"source": f.stem, "last_ok": d.get("last_ok") or "",
                           "last_fetch": d.get("last_fetch") or "", "note": d.get("last_note") or ""}
    return rows


def build(data: Path, state: Path | None = None) -> dict[str, dict[tuple, dict]]:
    """データファイル → テーブルごとの {主キー: 行}。"""
    t: dict[str, dict[tuple, dict]] = {name: {} for name in COLUMNS}
    t["source_status"] = source_status(state if state is not None else data.parent / "state")
    stats: dict[str, dict] = {}

    for f in sorted((data / "earthquakes").glob("*.csv")):
        for r in _csv(f):
            p = resolve(r["location"])
            row = {
                "event_id": r["event_id"], "occurred_at": r["datetime_pht"], "lat": r["lat"], "lon": r["lon"],
                "depth_km": r["depth_km"], "mag": r["mag"], "location": r["location"],
                "city_code": p.city.code if p.city else "", "province_code": p.province.code if p.province else "",
                "distance_km": "" if p.distance_km is None else str(p.distance_km), "bearing": p.bearing,
            }
            row["row_hash"] = _hash(row)
            t["earthquakes"][(row["event_id"],)] = row
            if row["city_code"]:
                s = stats.setdefault(row["city_code"], {"city_code": row["city_code"], "total": 0, "m4_plus": 0,
                                                        "max_mag": 0.0, "max_mag_at": "", "first_at": "9", "last_at": ""})
                mag = float(row["mag"] or 0)
                s["total"] += 1
                s["m4_plus"] += mag >= 4
                if mag > s["max_mag"]:
                    s["max_mag"], s["max_mag_at"] = mag, row["occurred_at"]
                s["first_at"], s["last_at"] = min(s["first_at"], row["occurred_at"]), max(s["last_at"], row["occurred_at"])
    for s in stats.values():
        t["city_quake_stats"][(s["city_code"],)] = {k: str(v) for k, v in s.items()}

    for f in sorted((data / "advisories").glob("*.jsonl")):
        for a in _jsonl(f):
            exp = _expires(a.get("issued_at", ""), a["text"])
            seen = a.get("first_seen_utc", "")
            t["advisories"][(a["id"],)] = {
                "_wm": seen,
                "id": a["id"], "region": a["region"], "kind": a["kind"], "title": a.get("title", ""),
                "number": a.get("number", ""), "issued_at": a.get("issued_at", ""), "expires_at": exp,
                "text": a["text"], "first_seen": a.get("first_seen_utc", ""),
            }
            for code, status in city_codes(extract(a["text"])).items():
                t["advisory_cities"][(code, a["id"])] = {"_wm": seen, "advisory_id": a["id"], "city_code": code, "status": status, "expires_at": exp}

    for table, folder, reader in [("dam_levels", "dams", _csv), ("flood_watch", "flood_watch", _csv),
                                  ("river_levels", "river_levels", _csv), ("volcano_alert", "volcano_alert", _csv),
                                  ("cyclone_bulletins", "tcb", _jsonl)]:
        for f in sorted((data / folder).glob("*")):
            for r in reader(f):
                row = {c: str(r.get(c, "")) for c in COLUMNS[table]}
                if table in WATERMARK:
                    row["_wm"] = row[WATERMARK[table]]
                t[table][tuple(row[k] for k in KEYS[table])] = row
    return t


def _hash(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _lit(col: str, v: str) -> str:
    if v == "" or v is None:
        return "NULL"
    if col in NUMERIC and re.fullmatch(r"-?\d+(\.\d+)?", str(v)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _emit(table: str, changed: list[dict], statements: list[str]) -> None:
    cols = COLUMNS[table]
    head = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES\n"
    buf: list[str] = []
    size = len(head)
    for r in changed:
        tup = "(" + ", ".join(_lit(c, r.get(c, "")) for c in cols) + ")"
        if buf and size + len(tup.encode()) + 2 > MAX_SQL_BYTES:
            statements.append(head + ",\n".join(buf) + ";")
            buf, size = [], len(head)
        buf.append(tup)
        size += len(tup.encode()) + 2
    if buf:
        statements.append(head + ",\n".join(buf) + ";")


class Unit:
    """D1 へ送る 1 かたまり。**全部送り切れたときだけ** manifest を進める。

    途中で失敗した単位は manifest に反映しない。中身は INSERT OR REPLACE か
    「範囲 DELETE → 入れ直し」なので、次の回に丸ごと送り直して構わない。
    """

    __slots__ = ("key", "table", "statements", "rows", "backlog", "_patch")

    def __init__(self, key: str, table: str, statements: list[str], rows: int, patch, backlog: bool = False):
        self.key = key              # ログに出す名前。"earthquakes:2026-08" など
        self.table = table
        self.statements = statements
        self.rows = rows            # 送る行数(D1 が数える rows_written とは別物。索引のぶん増える)
        self.backlog = backlog      # 過去分の積み残し。新しいデータより後ろに置き、上限も別にする
        self._patch = patch

    def apply(self, manifest: dict) -> None:
        self._patch(manifest)


def _watermark_unit(table: str, tables: dict, manifest: dict) -> Unit:
    """追記だけの表: 送信位置より新しい行だけ。"""
    wm = (manifest.get(table) or {}).get("sent_until", "")
    fresh = sorted((r for r in tables[table].values() if r["_wm"] > wm), key=lambda r: r["_wm"])
    statements: list[str] = []
    _emit(table, fresh, statements)
    until = max([wm] + [r["_wm"] for r in fresh])

    def patch(m: dict) -> None:
        m.setdefault(table, {})["sent_until"] = until

    return Unit(table, table, statements, len(fresh), patch)


def _rowhash_unit(table: str, tables: dict, manifest: dict) -> Unit:
    """小さな表: 行ごとにハッシュを比べる。"""
    old = manifest.get(table) or {}
    now = {"|".join(k): _hash(r) for k, r in tables[table].items()}
    pick = [tables[table][k] for k in tables[table] if old.get("|".join(k)) != now["|".join(k)]]
    statements: list[str] = []
    _emit(table, pick, statements)

    def patch(m: dict) -> None:
        m[table] = now

    return Unit(table, table, statements, len(pick), patch)


def _eq_units(tables: dict, manifest: dict, max_rows: int | None) -> list[Unit]:
    """地震: 月ごとに 1 単位。直近の月が先、過去分は **新しい月から**。

    サイトに出て嬉しいのは新しい月なので、積み残しは古い方からではなく新しい方から埋める。
    max_rows は過去分だけにかかる(直近の月は必ず送る。新しい地震を積み残しで待たせない)。
    """
    old = manifest.get("earthquakes") or {}
    old_months = old.get("months") or {}
    old_rows_all = old.get("rows") or {}
    by_month: dict[str, dict[str, dict]] = {}
    for (eid,), r in tables["earthquakes"].items():
        by_month.setdefault(r["occurred_at"][:7], {})[eid] = r
    months = sorted(by_month, reverse=True)
    recent = set(months[:RECENT_MONTHS])

    fresh: list[Unit] = []
    older: list[Unit] = []
    budget = max_rows if max_rows is not None else 10 ** 9
    stopped = took = False   # 過去分の上限に当たったら、そこから古い月は次の回に回す
    for month in months:
        rows = by_month[month]
        digest = hashlib.sha256("".join(sorted(r["row_hash"] for r in rows.values())).encode()).hexdigest()[:16]
        old_rows = old_rows_all.get(month)
        statements: list[str] = []
        pick: list[dict] = []
        gone: list[str] = []
        if old_months.get(month) == digest:
            pass                     # 変わっていない
        elif old_rows is not None:   # 行ごとに比べられる月
            pick = [r for eid, r in rows.items() if old_rows.get(eid) != r["row_hash"]]
            gone = [eid for eid in old_rows if eid not in rows]
        else:                        # 初めての月、または古い月が後から直された → 月ごと送り直す
            pick = list(rows.values())
            if old_months.get(month):
                # 行ごとの記録が無い月は、消えた行を見つけられない。月の範囲を消してから入れ直す。
                # この DELETE は同じ単位に入れる(途中で落ちても manifest は進まないので、次の回がやり直す)。
                y, m = map(int, month.split("-"))
                nxt = f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"
                statements.append(f"DELETE FROM earthquakes WHERE occurred_at >= '{month}-01' AND occurred_at < '{nxt}-01';")
        _emit("earthquakes", sorted(pick, key=lambda r: r["occurred_at"]), statements)
        for i in range(0, len(gone), 200):  # 取得元が取り消した地震は D1 からも消す
            ids = ", ".join(_lit("event_id", g) for g in gone[i:i + 200])
            statements.append(f"DELETE FROM earthquakes WHERE event_id IN ({ids});")

        keep = {eid: r["row_hash"] for eid, r in rows.items()} if month in recent else None

        def patch(m: dict, month=month, digest=digest, keep=keep) -> None:
            eq = m.setdefault("earthquakes", {})
            eq.setdefault("months", {})[month] = digest
            kept = eq.setdefault("rows", {})
            if keep is None:  # 直近でなくなった月は、行ごとの記録を捨てて manifest を小さく保つ
                kept.pop(month, None)
            else:
                kept[month] = keep

        unit = Unit(f"earthquakes:{month}", "earthquakes", statements, len(pick) + len(gone), patch,
                    backlog=month not in recent)
        if month in recent:
            fresh.append(unit)
        elif not unit.rows:          # 送る物が無い月(掃除だけ)は上限に関係なく進めてよい
            older.append(unit)
        elif stopped:
            continue
        elif unit.rows > budget and took:
            stopped = True           # 穴を空けて古い月に飛ばない。新しい月から順に詰める
        else:
            budget -= unit.rows      # 1 か月が上限より大きくても、最初の 1 か月は送る(進まなくなるため)
            took = True
            older.append(unit)
    return fresh + older


def plan(tables: dict, manifest: dict, max_rows: int | None = None) -> list[Unit]:
    """送る単位を、送る順に並べて返す。

    小さい表 → 直近の月の地震 → 過去分の地震(新しい月から)。
    先頭ほど「新しいデータ」なので、1 日の上限に当たっても鮮度は落ちない。
    """
    units = [_rowhash_unit("source_status", tables, manifest)]
    units += [_watermark_unit(t, tables, manifest) for t in APPEND_ORDER]
    units += [_rowhash_unit(t, tables, manifest) for t in ROWHASH_ORDER if t != "source_status"]
    units += _eq_units(tables, manifest, max_rows)
    return units


def diff(tables: dict, manifest: dict, max_rows: int | None = None) -> tuple[list[str], dict, dict[str, int]]:
    """変わった行だけの SQL、新しい manifest、テーブルごとの行数を返す(全部送れた前提)。

    max_rows を渡すと、過去分の地震はその行数まで(初回投入を数日に分けるため)。
    実際の送信は `db/send.py` が `plan()` の単位ごとに行い、送れた分だけ manifest を進める。
    """
    statements: list[str] = []
    counts: dict[str, int] = {t: 0 for t in COLUMNS}
    new: dict = json.loads(json.dumps(manifest))
    for u in plan(tables, manifest, max_rows):
        statements += u.statements
        counts[u.table] += u.rows
        u.apply(new)
    return statements, new, counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--manifest", default="state/d1-manifest.json")
    ap.add_argument("--out", default="-")
    ap.add_argument("--max-rows", type=int, default=None, help="地震の行数の上限(過去分の初回投入を数日に分ける)")
    ap.add_argument("--state", default="state", help="取得元の鮮度(source_status)を読む場所")
    args = ap.parse_args()
    mpath = Path(args.manifest)
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    statements, new_manifest, counts = diff(build(Path(args.data), Path(args.state)), manifest, args.max_rows)
    sql = "\n".join(statements)
    print(sql) if args.out == "-" else Path(args.out).write_text(sql + "\n")
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(new_manifest, sort_keys=True))
    print("-- " + json.dumps(counts), flush=True) if args.out != "-" else None


if __name__ == "__main__":
    main()
