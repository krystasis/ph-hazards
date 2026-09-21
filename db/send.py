"""変わった行を Cloudflare D1 へ送る。**送れた分だけ** manifest を進める。

    python3 -m db.send data                                   # HTTP API(Actions 用)
    python3 -m db.send data --via wrangler \
        --wrangler-bin /path/to/wrangler --wrangler-cwd /path/to/site   # 手元用

決まり:
- 送る単位(`db/export.plan()`)ごとに、全部の文が通ったときだけ manifest を進める。
  途中で失敗したら **そこで止めて 0 以外で終わる**。文は INSERT OR REPLACE か
  「範囲 DELETE → 入れ直し」なので、次の回が同じ単位を丸ごと送り直せばよい。
- 1 日に書ける行数には上限を置く(`state/d1-usage.json`)。無料枠は 1 日 10 万行で、
  しかも **アカウント全体で** 共有なので、既定は 6 万行に留める。
  上限に当たって止めるのは失敗ではない(0 で終わる)。
  さらに上限の内側に「新しいデータぶん」を空けておき、過去分の積み残しはそこまでで止める。
- D1 が数える rows_written は索引の更新も含むので、送った行数より多くなる。
  予算は **API が返した rows_written** で数える(送った行数では数えない)。
- トークン・アカウント ID・データベース ID は絶対に出力しない。

環境変数: CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID / D1_DATABASE_ID
          D1_DAILY_BUDGET / D1_FRESH_RESERVE / D1_EQ_ROWS_PER_RUN
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .export import build, plan

DEFAULT_BUDGET = 60_000   # 1 日に書いてよい rows_written。無料枠 10 万をもう 1 つのアプリと分ける
DEFAULT_RESERVE = 10_000  # そのうち、新しいデータのために空けておく分(過去分はここまで来たら止める)
DEFAULT_EQ_ROWS = 4_000   # 1 回で送る過去分の地震の上限(1 回の実行を長くしすぎない)
DEFAULT_COST = 5.0        # 地震 1 行あたりの rows_written。本体 + 主キー + 索引 3 本(実測 5.0)
ENV_KEYS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "D1_DATABASE_ID")


class SendError(Exception):
    """1 文を送れなかった。ここで止めて、次の回に送り直す。"""


def _scrubber(*secrets: str):
    """トークンや ID が誤ってメッセージに混ざっても出さないようにする。"""
    hide = [s for s in secrets if s and len(s) >= 8]

    def scrub(text: str) -> str:
        for s in hide:
            text = text.replace(s, "***")
        return text

    return scrub


class ApiTransport:
    """Cloudflare の HTTP API。1 文ずつ送って rows_written を受け取る。"""

    def __init__(self, token: str, account: str, database: str, timeout: int = 120):
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._url = f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"
        self._timeout = timeout
        self._scrub = _scrubber(token, account, database)

    def execute(self, sql: str) -> int:
        req = urllib.request.Request(self._url, data=json.dumps({"sql": sql}).encode(),
                                     headers=self._headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as res:
                payload = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            raise SendError(self._scrub(f"HTTP {e.code} {_messages(body)}")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SendError(self._scrub(f"つながらない: {e}")) from None
        if not payload.get("success"):
            raise SendError(self._scrub("D1: " + _errors(payload)))
        return sum(int((r.get("meta") or {}).get("rows_written") or 0) for r in payload.get("result") or [])


class WranglerTransport:
    """wrangler CLI 経由(手元用)。API トークンをまだ作っていないときに使う。"""

    def __init__(self, binary: str, cwd: str, database: str, timeout: int = 600):
        self._cmd = [binary, "d1", "execute", database, "--remote", "--yes", "--json", "--file"]
        self._cwd = cwd
        self._timeout = timeout

    def execute(self, sql: str) -> int:
        with tempfile.NamedTemporaryFile("w", suffix=".sql", encoding="utf-8", delete=False) as f:
            f.write(sql if sql.endswith("\n") else sql + "\n")
            path = f.name
        try:
            p = subprocess.run(self._cmd + [path], cwd=self._cwd, capture_output=True,
                               text=True, timeout=self._timeout)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise SendError(f"wrangler を動かせない: {e}") from None
        finally:
            os.unlink(path)
        payload = _json_tail(p.stdout)
        if p.returncode != 0 or payload is None:
            raise SendError(f"wrangler({p.returncode}): {_errors(payload) or (p.stdout + p.stderr)[-400:].strip()}")
        return sum(int((r.get("meta") or {}).get("rows_written") or 0) for r in payload if isinstance(r, dict))


def _errors(payload) -> str:
    """API / wrangler が返したエラー文だけを取り出す(ID は入らない)。"""
    if isinstance(payload, dict):
        if isinstance(payload.get("error"), dict):
            return str(payload["error"].get("text", ""))
        return "; ".join(str(e.get("message", e)) for e in payload.get("errors") or [])
    return ""


def _messages(body: str) -> str:
    try:
        return _errors(json.loads(body)) or body
    except ValueError:
        return body


def _json_tail(text: str):
    """wrangler は進捗の行を混ぜてくるので、行頭の [ か { から先を JSON として読む。"""
    for i, ch in enumerate(text):
        if ch in "[{" and (i == 0 or text[i - 1] == "\n"):
            try:
                return json.loads(text[i:])
            except ValueError:
                continue
    return None


class Usage:
    """その日(UTC)に書いた行数。日付が変わったら 0 に戻す。

    cost_per_row(1 行あたりの rows_written の実測)だけは日付をまたいで持ち越す。
    これが無いと、実行の 1 つ目の単位を見積もれず、上限を大きく踏み越える。
    """

    def __init__(self, path: Path | None, today: str | None = None):
        self.path = path
        self.today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.rows_written = 0
        self.statements = 0
        self.cost = DEFAULT_COST
        if path and path.exists():
            try:
                d = json.loads(path.read_text())
            except ValueError:
                d = {}
            self.cost = float(d.get("cost_per_row") or DEFAULT_COST)
            if d.get("date") == self.today:
                self.rows_written = int(d.get("rows_written") or 0)
                self.statements = int(d.get("statements") or 0)

    def add(self, rows_written: int) -> None:
        self.rows_written += rows_written
        self.statements += 1
        self.save()

    def measure(self, rows: int, rows_written: int) -> None:
        """実測で見積もりを直す。次の実行の 1 つ目の単位はこれを使う。"""
        if rows > 0:
            self.cost = rows_written / rows
            self.save()

    def save(self) -> None:
        if not self.path:
            return
        _replace(self.path, json.dumps({"date": self.today, "rows_written": self.rows_written,
                                        "statements": self.statements,
                                        "cost_per_row": round(self.cost, 3)}, sort_keys=True) + "\n")


def _replace(path: Path, text: str) -> None:
    """書き途中のファイルを残さない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def send(units, transport, manifest: dict, usage: Usage, *, budget: int = DEFAULT_BUDGET,
         reserve: int = DEFAULT_RESERVE, save=None, log=print) -> str:
    """単位ごとに送る。戻り値は終わり方: done / budget / failed。

    manifest はその場で書き換える(送れた単位だけ)。save があれば単位ごとに呼ぶ。
    """
    outcome = "done"
    sent_rows = 0
    for u in units:
        if not u.statements:       # 送る物が無い単位も manifest は進める(直近でなくなった月の掃除など)
            u.apply(manifest)
            continue
        limit = budget - reserve if u.backlog else budget
        # 上限の判定は単位の手前だけ(途中で切ると送った行が無駄になる)。
        # 過去分は「この単位を送ったらいくつ書くか」を実測の cost_per_row で見積もり、はみ出す前に止める。
        est = u.rows * usage.cost if u.backlog else 0
        if usage.rows_written + est >= limit:
            kind = "過去分" if u.backlog else "全体"
            log(f"D1: 今日の書き込みが {usage.rows_written} 行なので{kind}はここまで(上限 {limit})。失敗ではない")
            outcome = "budget"
            break
        rows_written = 0
        try:
            for s in u.statements:
                n = transport.execute(s)
                rows_written += n
                usage.add(n)  # 文ごとに記録する。途中で落ちても今日書いた分を見失わない
        except SendError as e:
            log(f"D1: {u.key} の途中で失敗 → ここで止める(次の回が送り直す): {e}")
            outcome = "failed"
            break
        u.apply(manifest)
        sent_rows += u.rows
        if u.backlog:
            usage.measure(u.rows, rows_written)
        log(f"D1: {u.key} {u.rows} 行 / {len(u.statements)} 文 → rows_written {rows_written}")
        if save:
            save(manifest)
    if save:
        save(manifest)
    log(f"D1: 送った {sent_rows} 行、今日の rows_written は合計 {usage.rows_written} 行({outcome})")
    return outcome


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?", default="data")
    ap.add_argument("--state", default="state")
    ap.add_argument("--manifest", default="state/d1-manifest.json")
    ap.add_argument("--usage", default="state/d1-usage.json")
    ap.add_argument("--via", choices=("api", "wrangler"), default="api")
    ap.add_argument("--wrangler-bin", default=os.environ.get("D1_WRANGLER_BIN"),
                    help="wrangler の場所(--via wrangler のとき必須。既定なし)")
    ap.add_argument("--wrangler-cwd", default=os.environ.get("D1_WRANGLER_CWD"),
                    help="wrangler.jsonc がある場所(--via wrangler のとき必須。既定なし)")
    ap.add_argument("--database", default=os.environ.get("D1_DATABASE_NAME", "ph-hazards"))
    ap.add_argument("--budget", type=int, default=int(os.environ.get("D1_DAILY_BUDGET") or DEFAULT_BUDGET))
    ap.add_argument("--reserve", type=int, default=int(os.environ.get("D1_FRESH_RESERVE") or DEFAULT_RESERVE),
                    help="新しいデータのために空けておく rows_written")
    ap.add_argument("--eq-rows", type=int, default=int(os.environ.get("D1_EQ_ROWS_PER_RUN") or DEFAULT_EQ_ROWS),
                    help="1 回で送る過去分の地震の上限")
    ap.add_argument("--dry-run", action="store_true", help="送らずに、送る単位だけ出す")
    args = ap.parse_args(argv)

    mpath, upath = Path(args.manifest), Path(args.usage)
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    units = plan(build(Path(args.data), Path(args.state)), manifest, args.eq_rows)

    if args.dry_run:
        for u in units:
            if u.statements:
                print(f"  {u.key}: {u.rows} 行 / {len(u.statements)} 文{' (過去分)' if u.backlog else ''}")
        print(f"  合計 {sum(u.rows for u in units)} 行 / {sum(len(u.statements) for u in units)} 文")
        return 0

    if args.via == "wrangler":
        if not args.wrangler_bin or not args.wrangler_cwd:
            print("D1: --wrangler-bin と --wrangler-cwd が要る(D1_WRANGLER_BIN / D1_WRANGLER_CWD でもよい)")
            return 2
        transport = WranglerTransport(args.wrangler_bin, args.wrangler_cwd, args.database)
    else:
        env = {k: os.environ.get(k, "") for k in ENV_KEYS}
        if not all(env.values()):
            print("D1: 認証情報が無いので送信は飛ばす(" + "・".join(k for k in ENV_KEYS if not env[k]) + " が未設定)")
            return 0
        transport = ApiTransport(env["CLOUDFLARE_API_TOKEN"], env["CLOUDFLARE_ACCOUNT_ID"], env["D1_DATABASE_ID"])

    usage = Usage(upath)
    outcome = send(units, transport, manifest, usage, budget=args.budget, reserve=args.reserve,
                   save=lambda m: _replace(mpath, json.dumps(m, sort_keys=True)))
    return 1 if outcome == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
