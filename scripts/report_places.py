"""公開リポジトリの注意報を全部なめて、名寄せの当たり具合と外れた名前を出す。

    python3 -m scripts.report_places data/advisories
"""
import collections
import json
import sys
from pathlib import Path

from places.advisory_places import extract


def main(folder: str) -> None:
    items = [json.loads(l) for p in sorted(Path(folder).glob("*.jsonl")) for l in p.open(encoding="utf-8") if l.strip()]
    hit = miss = empty = 0
    missed = collections.Counter()
    for it in items:
        areas = extract(it["text"])
        if not areas:
            empty += 1
        for a in areas:
            hit += len(a.cities) + (1 if a.whole else 0)
            miss += len(a.unmatched)
            for u in a.unmatched:
                missed[(it["region"], a.province.name if a.province else a.region_code, u)] += 1
    print(f"注意報 {len(items)} 件 / 場所が取れなかった本文 {empty} 件 / 当たり {hit} / 外れ {miss}")
    for (region, prov, name), n in missed.most_common(40):
        print(f"  {n:3d}  {region:8s} {prov or '-':22s} {name}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/advisories")
