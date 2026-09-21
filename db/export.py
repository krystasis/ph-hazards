"""公開側のデータファイルから D1 へ送る SQL を作る。**前回から変わった行だけ**を出す。

D1 の無料枠は 1 日 10 万行の書き込み。月のファイルを毎回丸ごと送ると地震だけで超えるので、
行ごとのハッシュを manifest に持ち、新規と変更だけを INSERT OR REPLACE する。

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
}
KEYS = {
    "earthquakes": ["event_id"], "city_quake_stats": ["city_code"], "advisories": ["id"],
    "advisory_cities": ["city_code", "advisory_id"], "dam_levels": ["dam", "obs_date"],
    "flood_watch": ["sub_basin", "date_pht"], "river_levels": ["station_code", "time_pht"],
    "volcano_alert": ["volcano", "date_pht"], "cyclone_bulletins": ["sha"],
}
NUMERIC = {"lat", "lon", "depth_km", "mag", "distance_km", "total", "m4_plus", "max_mag", "rwl_m", "dev_24h_m",
           "nhwl_m", "dev_nhwl_m", "rule_curve_m", "dev_rule_curve_m", "wl_m", "alert_m", "alarm_m", "critical_m",
           "alert_level"}

# 追記しかされない表は、行ごとのハッシュを持たずに「どこまで送ったか」だけ覚える(manifest を小さく保つ)。
WATERMARK = {"river_levels": "time_pht", "cyclone_bulletins": "fetched_utc", "advisories": None, "advisory_cities": None}
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


def build(data: Path) -> dict[str, dict[tuple, dict]]:
    """データファイル → テーブルごとの {主キー: 行}。"""
    t: dict[str, dict[tuple, dict]] = {name: {} for name in COLUMNS}
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


def diff(tables: dict, manifest: dict, max_rows: int | None = None) -> tuple[list[str], dict, dict[str, int]]:
    """変わった行だけの SQL、新しい manifest、テーブルごとの行数を返す。

    max_rows を渡すと、地震は古い月から順にその行数まで(過去分の初回投入を数日に分けるため)。
    """
    statements: list[str] = []
    counts: dict[str, int] = {}
    new: dict = {}

    # --- 地震: 月ごとに区切る
    old_eq = manifest.get("earthquakes", {"months": {}, "rows": {}})
    by_month: dict[str, dict[str, dict]] = {}
    for (eid,), r in tables["earthquakes"].items():
        by_month.setdefault(r["occurred_at"][:7], {})[eid] = r
    recent = set(sorted(by_month)[-RECENT_MONTHS:])
    new_eq = {"months": {}, "rows": {}}
    budget = max_rows if max_rows is not None else 10 ** 9
    changed: list[dict] = []
    gone: list[str] = []
    wipes: list[str] = []
    for month in sorted(by_month):
        rows = by_month[month]
        resend = None
        digest = hashlib.sha256("".join(sorted(r["row_hash"] for r in rows.values())).encode()).hexdigest()[:16]
        old_rows = old_eq["rows"].get(month)
        if old_eq["months"].get(month) == digest:
            pick: list[dict] = []
        elif old_rows is not None:  # 行ごとに比べられる月
            pick = [r for eid, r in rows.items() if old_rows.get(eid) != r["row_hash"]]
            gone += [eid for eid in old_rows if eid not in rows]
        else:                        # 初めての月、または古い月が後から直された → 月ごと送り直す
            pick = list(rows.values())
            resend = month if old_eq["months"].get(month) else None
        if len(pick) > budget:       # 今回は入りきらない。この月は次回に回す(中途半端に記録しない)
            if old_eq["months"].get(month):
                new_eq["months"][month] = old_eq["months"][month]
            if old_rows is not None:
                new_eq["rows"][month] = old_rows
            continue
        budget -= len(pick)
        if resend:  # 行ごとの記録が無い古い月は、消えた行を見つけられない。月の範囲を消してから入れ直す
            y, m = map(int, resend.split("-"))
            nxt = f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"
            wipes.append(f"DELETE FROM earthquakes WHERE occurred_at >= '{resend}-01' AND occurred_at < '{nxt}-01';")
        changed += pick
        new_eq["months"][month] = digest
        if month in recent:
            new_eq["rows"][month] = {eid: r["row_hash"] for eid, r in rows.items()}
    statements += wipes
    _emit("earthquakes", changed, statements)
    for i in range(0, len(gone), 200):  # 取得元が取り消した地震は D1 からも消す
        ids = ", ".join(_lit("event_id", g) for g in gone[i:i + 200])
        statements.append(f"DELETE FROM earthquakes WHERE event_id IN ({ids});")
    counts["earthquakes"] = len(changed) + len(gone)
    new["earthquakes"] = new_eq

    # --- 追記だけの表: 送信位置より新しい行だけ
    for table in WATERMARK:
        wm = manifest.get(table, {}).get("sent_until", "")
        fresh = [r for r in tables[table].values() if r["_wm"] > wm]
        _emit(table, fresh, statements)
        counts[table] = len(fresh)
        new[table] = {"sent_until": max([wm] + [r["_wm"] for r in fresh])}

    # --- 小さな表: 行ごとに比べる
    for table in ("city_quake_stats", "dam_levels", "flood_watch", "volcano_alert"):
        old = manifest.get(table, {})
        now = {"|".join(k): _hash(r) for k, r in tables[table].items()}
        pick = [tables[table][k] for k in tables[table] if old.get("|".join(k)) != now["|".join(k)]]
        _emit(table, pick, statements)
        counts[table] = len(pick)
        new[table] = now
    return statements, new, counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--manifest", default="state/d1-manifest.json")
    ap.add_argument("--out", default="-")
    ap.add_argument("--max-rows", type=int, default=None, help="地震の行数の上限(過去分の初回投入を数日に分ける)")
    args = ap.parse_args()
    mpath = Path(args.manifest)
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    statements, new_manifest, counts = diff(build(Path(args.data)), manifest, args.max_rows)
    sql = "\n".join(statements)
    print(sql) if args.out == "-" else Path(args.out).write_text(sql + "\n")
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(new_manifest, sort_keys=True))
    print("-- " + json.dumps(counts), flush=True) if args.out != "-" else None


if __name__ == "__main__":
    main()
