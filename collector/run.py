"""1 回分の収集。`python -m collector.run [--only KEY] [--force]`

取得元ごとに独立して動く。1 つが拒否されても他は続ける。解析が 0 件なら etag を進めず、
終了コードを 1 にして GitHub Actions 上で赤く見せる(レイアウト変更の合図)。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

from . import pagasa_dams, pagasa_regional, pagasa_tcb, phivolcs_eq, phivolcs_volcano
from .fetch import Blocked, fetch, in_cooldown, load_state, save_state
from .store import DATA, append_jsonl, replace_csv, upsert_csv

PHT = timezone(timedelta(hours=8))
PAUSE_SEC = 2  # 同じホストへ続けて行くときの間隔


def _due(state: dict, now: datetime, min_interval_min: int, force: bool) -> bool:
    last = state.get("last_fetch")
    return force or not last or now - datetime.fromisoformat(last) >= timedelta(minutes=min_interval_min)


def _finish(key: str, state: dict, now: datetime, resp, ok: bool, note: str) -> None:
    state["last_fetch"] = now.isoformat()
    state["last_status"] = resp.status
    state["last_note"] = note
    if ok and resp.status == 200:
        state["etag"], state["last_modified"] = resp.etag, resp.last_modified
        state["last_ok"] = now.isoformat()
    save_state(key, state)


def save_eq_months(rows: list[dict]) -> tuple[int, bool]:
    """ページは月の全件を載せているので、月ごとのファイルを丸ごと置き換える。"""
    changed, ok = 0, True
    for month in sorted({phivolcs_eq.month_of(r) for r in rows}):
        part = [r for r in rows if phivolcs_eq.month_of(r) == month]
        n, fine = replace_csv(DATA / "earthquakes" / f"{month}.csv", phivolcs_eq.FIELDS, part, ["datetime_pht", "event_id"])
        changed, ok = changed + n, ok and fine
    return changed, ok


def run_eq(now, force) -> tuple[bool, str]:
    key, state = phivolcs_eq.KEY, load_state(phivolcs_eq.KEY)
    if in_cooldown(state, now):
        return True, "cooldown"
    if not _due(state, now, phivolcs_eq.MIN_INTERVAL_MIN, force):
        return True, "not due"
    resp = fetch(key, phivolcs_eq.URL, state, now)
    if resp.status == 304:
        _finish(key, state, now, resp, True, "304")
        return True, "304 変更なし"
    rows = phivolcs_eq.parse(resp.text)
    changed, ok = save_eq_months(rows)
    ok = ok and len(rows) > 0
    note = f"{len(rows)} 行を解析、{changed} 行を更新" + ("" if ok else "(行数が急減。書かずに止めた)")
    _finish(key, state, now, resp, ok, note)
    return ok, note


def run_dams(now, force) -> tuple[bool, str]:
    key, state = pagasa_dams.KEY, load_state(pagasa_dams.KEY)
    if in_cooldown(state, now):
        return True, "cooldown"
    if not _due(state, now, pagasa_dams.MIN_INTERVAL_MIN, force):
        return True, "not due"
    resp = fetch(key, pagasa_dams.URL, state, now)
    if resp.status == 304:
        _finish(key, state, now, resp, True, "304")
        return True, "304 変更なし"
    today = now.astimezone(PHT).date()
    dams, watch = pagasa_dams.parse(resp.text, today)
    changed = 0
    for year in sorted({d["obs_date"][:4] for d in dams}):
        part = [d for d in dams if d["obs_date"][:4] == year]
        changed += upsert_csv(DATA / "dams" / f"{year}.csv", pagasa_dams.DAM_FIELDS, part, ["dam", "obs_date"], ["obs_date", "dam"])
    changed += upsert_csv(DATA / "flood_watch" / f"{today.year}.csv", pagasa_dams.WATCH_FIELDS, watch, ["date_pht", "sub_basin"], ["date_pht", "sub_basin"])
    ok = len(dams) > 0
    note = f"ダム {len(dams)} 行、流域 {len(watch)} 行を解析、{changed} 行を更新"
    _finish(key, state, now, resp, ok, note)
    return ok, note


def run_regional(now, force) -> tuple[bool, str]:
    key, state = pagasa_regional.KEY, load_state(pagasa_regional.KEY)
    if in_cooldown(state, now):
        return True, "cooldown"
    if not _due(state, now, pagasa_regional.MIN_INTERVAL_MIN, force):
        return True, "not due"
    fallback = now.astimezone(PHT).isoformat()
    total = fresh = pages_ok = 0
    resp = None
    for region in pagasa_regional.REGIONS:
        resp = fetch(key, pagasa_regional.BASE + region, {}, now)  # 動的ページなので条件付き GET は使わない
        # タブの入れ物(#thunderstorms)が見つからなければレイアウトが変わっている。
        if 'id="thunderstorms"' in resp.text and 'id="rainfalls"' in resp.text:
            pages_ok += 1
        items = pagasa_regional.parse(resp.text, region)
        for it in items:
            it["first_seen_utc"] = now.isoformat()
        total += len(items)
        for month in sorted({pagasa_regional.month_of(i, fallback) for i in items}):
            part = [i for i in items if pagasa_regional.month_of(i, fallback) == month]
            fresh += append_jsonl(DATA / "advisories" / f"{month}.jsonl", part, "id")
        time.sleep(PAUSE_SEC)
    ok = pages_ok == len(pagasa_regional.REGIONS)
    note = f"{pages_ok}/{len(pagasa_regional.REGIONS)} ページ、発令中 {total} 件、新規 {fresh} 件"
    _finish(key, state, now, resp, ok, note)
    return ok, note


def run_tcb(now, force) -> tuple[bool, str]:
    key, state = pagasa_tcb.KEY, load_state(pagasa_tcb.KEY)
    if in_cooldown(state, now):
        return True, "cooldown"
    if not _due(state, now, pagasa_tcb.MIN_INTERVAL_MIN, force):
        return True, "not due"
    resp = fetch(key, pagasa_tcb.URL, {}, now)
    ok = "Tropical Cyclone" in resp.text
    snap = pagasa_tcb.parse(resp.text)
    fresh = 0
    if snap:
        snap["fetched_utc"] = now.isoformat()
        month = now.astimezone(PHT).strftime("%Y-%m")
        fresh = append_jsonl(DATA / "tcb" / f"{month}.jsonl", [snap], "sha")
    note = "発令なし" if not snap else f"公報あり、新規 {fresh} 件"
    _finish(key, state, now, resp, ok, note)
    return ok, note


def run_volcano(now, force) -> tuple[bool, str]:
    key, state = phivolcs_volcano.KEY, load_state(phivolcs_volcano.KEY)
    if in_cooldown(state, now):
        return True, "cooldown"
    if not _due(state, now, phivolcs_volcano.MIN_INTERVAL_MIN, force):
        return True, "not due"
    resp = fetch(key, phivolcs_volcano.URL, {}, now)
    today = now.astimezone(PHT).date()
    rows = phivolcs_volcano.parse(resp.text, today)
    changed = upsert_csv(DATA / "volcano_alert" / f"{today.year}.csv", phivolcs_volcano.FIELDS, rows, ["date_pht", "volcano"], ["date_pht", "volcano"])
    ok = len(rows) > 0
    note = f"{len(rows)} 火山、{changed} 行を更新"
    _finish(key, state, now, resp, ok, note)
    return ok, note


SOURCES = {
    phivolcs_eq.KEY: run_eq,
    pagasa_dams.KEY: run_dams,
    pagasa_regional.KEY: run_regional,
    pagasa_tcb.KEY: run_tcb,
    phivolcs_volcano.KEY: run_volcano,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(SOURCES))
    ap.add_argument("--force", action="store_true", help="最小間隔を無視する(クールダウンは無視しない)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    failed = False
    for key, fn in SOURCES.items():
        if args.only and key != args.only:
            continue
        try:
            ok, note = fn(now, args.force)
        except Blocked as e:
            ok, note = False, f"停止: {e}"  # 初回は赤で気づけるようにする。以後はクールダウン中として緑。
        except Exception as e:  # noqa: BLE001 — 1 つの失敗で他の取得元を止めない
            ok, note = False, f"失敗: {e!r}"
        print(f"[{key}] {'ok' if ok else 'NG'} — {note}")
        failed |= not ok
        time.sleep(PAUSE_SEC)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
