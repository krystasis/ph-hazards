"""一度だけ: 整える前に入った台風公報の行(data/tcb/*.jsonl)の本文を整え、同じ公報を 1 行にする。

    python3 -m collector.tcb_clean data/tcb          # 書き換える
    python3 -m collector.tcb_clean data/tcb --check  # 何行が何行になるかだけ見る

- 本文は `pagasa_tcb.clean_text` で整える(文言は変えない。コメントの残りと過去 PDF の一覧を落とすだけ)。
- 整えた本文が同じ行は、最初に取れた行(fetched_utc が一番早い)だけ残す。
- **sha は書き換えない**。最初に入れたときの sha のまま(D1 の cyclone_bulletins と突き合わせられるように)。
  これから入る行の sha は整えた本文から作る(pagasa_tcb.py)。
- 何度かけても同じ結果になる(整え済みのファイルにかけても変わらない)。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pagasa_tcb import clean_text


def clean_file(path: Path, write: bool = True) -> tuple[int, int]:
    """(前の行数, 後の行数) を返す。"""
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r.get("fetched_utc", "")):
        text = clean_text(r["text"])
        if text not in kept:
            kept[text] = dict(r, text=text)
    out = list(kept.values())
    if write and out != rows:
        with path.open("w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows), len(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="data/tcb")
    ap.add_argument("--check", action="store_true", help="書き換えずに数だけ出す")
    args = ap.parse_args()
    for f in sorted(Path(args.folder).glob("*.jsonl")):
        before, after = clean_file(f, write=not args.check)
        print(f"{f}: {before} 行 → {after} 行")


if __name__ == "__main__":
    main()
