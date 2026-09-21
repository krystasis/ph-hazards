"""リポジトリ内のファイルへ追記する(git の履歴がそのままデータの変更履歴になる)。"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def upsert_csv(path: Path, fields: list[str], rows: list[dict], key: list[str], sort: list[str]) -> int:
    """key が同じ行は上書き、無ければ追加。変わった行数を返す。"""
    existing: dict[tuple, dict] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[tuple(r[k] for k in key)] = r
    changed = 0
    for r in rows:
        k = tuple(r[x] for x in key)
        new = {f: str(r.get(f, "")) for f in fields}
        if existing.get(k) != new:
            existing[k] = new
            changed += 1
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(existing.values(), key=lambda r: tuple(r[s] for s in sort))
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(ordered)
    return changed


def append_jsonl(path: Path, items: list[dict], id_field: str) -> int:
    """id が未出の物だけ追記する。"""
    seen: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    seen.add(json.loads(line)[id_field])
    fresh = [i for i in items if i[id_field] not in seen]
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for i in fresh:
                f.write(json.dumps(i, ensure_ascii=False, sort_keys=True) + "\n")
    return len(fresh)


def replace_csv(path: Path, fields: list[str], rows: list[dict], sort: list[str], min_ratio: float = 0.95) -> tuple[int, bool]:
    """ファイルを今回の内容で置き換える(取得元の訂正・削除に追従する)。

    行数が急に減ったときは途中で切れたページとみなし、書かずに (0, False) を返す。
    """
    old: list[dict] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            old = list(csv.DictReader(f))
    if old and len(rows) < len(old) * min_ratio:
        return 0, False
    new = sorted(({f: str(r.get(f, "")) for f in fields} for r in rows), key=lambda r: tuple(r[s] for s in sort))
    if new == old:
        return 0, True
    old_keys = {tuple(r.items()) for r in old}
    changed = sum(1 for r in new if tuple(r.items()) not in old_keys) + max(0, len(old) - len(new))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(new)
    return changed, True
