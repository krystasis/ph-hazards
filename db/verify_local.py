"""手元の SQLite(D1 と同じエンジン)で、スキーマと差分書き出しを確かめる。

    python3 -m db.verify_local data
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

from .export import build, diff, plan

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
con = sqlite3.connect(":memory:")
con.executescript((Path(__file__).parent / "schema.sql").read_text())

t0 = time.time()
tables = build(DATA)
print(f"組み立て {time.time() - t0:.1f} 秒")

tables_fresh = build(DATA)
stmts, manifest, counts = diff(tables, {})
for s in stmts:
    con.execute(s)
print("初回(全件):", json.dumps(counts), "| 文の数", len(stmts), "| 最大の文", max(len(s.encode()) for s in stmts) // 1024, "KB")

stmts2, _, counts2 = diff(tables, manifest)
print("変更なしで 2 回目:", sum(counts2.values()), "行 /", len(stmts2), "文")

def touch(month_prefix: str, label: str) -> None:
    """その月の 1 件を変え、1 件を消して、D1 側が同じ件数になるかを見る。"""
    global manifest
    ids = [k for k, r in tables["earthquakes"].items() if r["occurred_at"].startswith(month_prefix)]
    r = dict(tables["earthquakes"][ids[0]], mag="9.9")
    r["row_hash"] = "changed-" + label
    tables["earthquakes"][ids[0]] = r
    del tables["earthquakes"][ids[5]]
    s3, manifest, c3 = diff(tables, manifest)
    for s in s3:
        con.execute(s)
    have = con.execute("select count(*) from earthquakes").fetchone()[0]
    print(f"{label}: 送った行 {c3['earthquakes']} | D1 側 {have} 件 / 手元 {len(tables['earthquakes'])} 件 {'一致' if have == len(tables['earthquakes']) else '不一致!'}")


latest = max(r["occurred_at"] for r in tables["earthquakes"].values())[:7]
touch(latest, "当月で 1 件変更 + 1 件削除")
touch("2018-01", "古い月で 1 件変更 + 1 件削除(月ごと入れ直し)")

print("\n--- ページが使う問い合わせが、インデックスで引けているか")
city = con.execute("select city_code from city_quake_stats order by total desc limit 1").fetchone()[0]
queries = {
    "市町の直近の地震 20 件": ("select occurred_at, mag, location from earthquakes where city_code=? order by occurred_at desc limit 20", (city,)),
    "市町の集計 1 行": ("select * from city_quake_stats where city_code=?", (city,)),
    "市町に発令中の注意報": ("select advisory_id, status from advisory_cities where city_code=? and expires_at > ? order by expires_at desc", (city, "2026-09-21T12:00:00+08:00")),
    "全国の直近の地震 20 件": ("select * from earthquakes order by occurred_at desc limit 20", ()),
    "観測所の直近の水位": ("select * from river_levels where station_code=? order by time_pht desc limit 12", ("11103201",)),
    "市町の年ごとの件数": ("select year, n, n_m4 from city_quake_years where city_code=? order by year limit 20", (city,)),
    "市町のマグニチュード帯 1 行": ("select * from city_quake_bands where city_code=?", (city,)),
    "市町の直近 24 か月": ("select month, n from city_quake_months where city_code=? and month >= ? order by month limit 24", (city, "2024-10")),
    "全国の日ごとの件数(30 日)": ("select day, n, n_m4 from daily_quake_counts where day >= ? and day <= ? order by day limit 31", ("2026-08-27", "2026-09-26")),
    "地域の最新の週間予報": ("select * from regional_outlook where region=? order by issued_at desc limit 5", ("ncrprsd",)),
    "地域の最新の週間予報(発表時刻だけ)": ("select issued_at from regional_outlook where region=? order by issued_at desc limit 1", ("ncrprsd",)),
    "その発表の 5 日(日の順)": ("select * from regional_outlook where region=? and issued_at=? order by day_index limit 7", ("ncrprsd", "2026-09-26T09:00:00+08:00")),
    "消えた集計行の削除(主キーの OR)": ("delete from city_quake_years where (city_code = ? and year = 2019) or (city_code = ? and year = 2020)", (city, city)),
}
for name, (sql, params) in queries.items():
    how = " / ".join(r[3] for r in con.execute("explain query plan " + sql, params))
    bad = "SCAN" in how and "USING" not in how  # インデックス順に読んで LIMIT で止まる SCAN は問題ない
    print(f"  {name}: {'全件走査!' if bad else 'OK'} — {how}")
print("\n行数:", {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in manifest})
print("manifest の大きさ:", len(json.dumps(manifest)) // 1024, "KB")

print("\n--- 送る順(初回。小さい表 → 直近の月 → 過去分は新しい月から)")
first = [u for u in plan(tables_fresh, {}, max_rows=20000) if u.statements]
print("  " + " → ".join(u.key for u in first[:8]) + " → …")
print("  過去分より前に送る行:", sum(u.rows for u in first if not u.backlog))

print("\n--- 初回投入を 1 日 2 万行に区切った場合")
m, day = {}, 0
while True:
    s, m, c = diff(tables_fresh, m, max_rows=20000)
    day += 1
    if not c["earthquakes"]:
        break
    if day <= 3 or c["earthquakes"] < 15000:
        print(f"  {day} 日目: 地震 {c['earthquakes']} 行")
print(f"  → {day - 1} 日で入りきる")
