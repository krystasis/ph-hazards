"""過去分の地震(月別ページ、2018-01〜先月)を 1 回だけ取り込む。

    python3 -m collector.backfill_eq [--from 2018-01] [--limit 12] [--pause 20]

月ごとに 1 リクエスト、間を空ける。済んだ月は state/phivolcs-eq-archive.json に記録して二度と取らない。
拒否されたら止まる(クールダウンは fetch.py が記録する)。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

from . import phivolcs_eq
from .fetch import Blocked, fetch, in_cooldown, load_state, save_state
from .run import PHT, save_eq_months

KEY = "phivolcs-eq-archive"


def months_between(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2018-01")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--pause", type=int, default=20)
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    first_of_month = now.astimezone(PHT).replace(day=1)
    last_month = (first_of_month - timedelta(days=1)).strftime("%Y-%m")

    state = load_state(KEY)
    if in_cooldown(state, now):
        print("cooldown 中")
        return 0
    done: dict = state.setdefault("done", {})
    todo = [m for m in months_between(args.start, last_month) if m not in done][: args.limit]
    print(f"残り {len(todo)} か月")
    for i, month in enumerate(todo):
        try:
            resp = fetch(KEY, phivolcs_eq.archive_url(month), {}, datetime.now(timezone.utc))
        except Blocked as e:
            print(f"停止: {e}")
            return 1
        except Exception as e:  # noqa: BLE001 — 404 の月などは記録して先へ進む
            print(f"[{month}] 失敗: {e!r}")
            state.setdefault("failed", {})[month] = repr(e)[:120]
            save_state(KEY, state)
            time.sleep(args.pause)
            continue
        rows = [r for r in phivolcs_eq.parse(resp.text) if phivolcs_eq.month_of(r) == month]
        changed, ok = save_eq_months(rows)
        print(f"[{month}] {len(rows)} 行、{changed} 行を更新{'' if ok and rows else ' — NG'}")
        if ok and rows:
            done[month] = {"rows": len(rows), "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
            state.get("failed", {}).pop(month, None)
            save_state(KEY, state)
        if i < len(todo) - 1:
            time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    sys.exit(main())
