"""どの PRSD(PAGASA の地域センター)がどの PSGC の地域を受け持っているかを、実際の注意報から数える。

    python3 -m db.prsd_regions data            # → db/prsd_regions.json

サイトは市町ページの「週間予報」「同じ PRSD のほかの注意報」を引くのに使う(サイトの設定へ写す)。
- 地域ごとに、その地域の州・市町を挙げた注意報の数を PRSD 別に数え、いちばん多い PRSD を採る。
- 2 つ以上の PRSD が挙げた地域は「割れている」。PRSD の受け持ちは地域の境ではなく州の境で切れている
  (例: Region III の Aurora は NL、残りは NCR)。そういう地域の州は `_provinces` に州ごとの PRSD を出す。
  州ごとの値は注意報の数えで決め、注意報に出てこない州は地域別ページの州の一覧(週間予報の州別データ)で埋める。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from places.advisory_places import extract
from places.gazetteer import Gazetteer, key, load

OUT = Path(__file__).resolve().parent / "prsd_regions.json"


def _page_province(g: Gazetteer, name: str) -> str | None:
    """週間予報の州別データの名前(「Isabela City, Zamboanga Peninsula」など)→ PSGC の州(独立市は擬似州)のコード。"""
    head, _, tail = name.partition(",")
    head = head.strip()
    region = g.region_code(tail) if tail.strip() else None
    if head.lower().endswith(" city") or head.lower().startswith("city of "):
        # 「Isabela City」を州の Isabela に当てない。市として、地域の中で探す。
        c = g.city(head, region_code=region)
        return c.province_code if c else None
    p = g.province(head)
    return p.code if p else None


def derive(data: Path, g: Gazetteer | None = None) -> dict:
    g = g or load()
    by_region: dict[str, Counter] = defaultdict(Counter)
    by_province: dict[str, Counter] = defaultdict(Counter)
    for f in sorted((data / "advisories").glob("*.jsonl")):
        for line in f.open(encoding="utf-8"):
            if not line.strip():
                continue
            a = json.loads(line)
            regions, provinces = set(), set()
            for area in extract(a["text"], g):
                if area.province:
                    regions.add(area.province.region_code)
                    provinces.add(area.province.code)
                if area.region_code:
                    regions.add(area.region_code)
                for c in area.cities:
                    regions.add(c.region_code)
                    provinces.add(c.province_code)
            for r in regions:          # 1 件の注意報は、同じ地域を何度挙げても 1 と数える
                by_region[r][a["region"]] += 1
            for p in provinces:
                by_province[p][a["region"]] += 1

    # 地域別ページの州の一覧(最新の発表)。注意報に出てこない州を埋めるのと、突き合わせに使う。
    pages: dict[str, str] = {}
    for f in sorted((data / "outlook").glob("*.jsonl")):
        for line in f.open(encoding="utf-8"):
            if line.strip():
                o = json.loads(line)
                for p in (o.get("provinces") or {}).values():
                    code = _page_province(g, p.get("name") or "")
                    if code:
                        pages[code] = o["region"]

    out: dict = {}
    ambiguous = {}
    for r in sorted(by_region):
        c = by_region[r]
        out[r] = c.most_common(1)[0][0]
        if len(c) > 1:
            ambiguous[r] = dict(c.most_common())
    provinces = {}
    for r in ambiguous:
        for p in sorted(x.code for x in g.provinces.values() if x.region_code == r):
            if by_province.get(p):
                provinces[p] = by_province[p].most_common(1)[0][0]
            elif p in pages:
                provinces[p] = pages[p]
    disagree = {p: {"advisories": provinces[p], "pages": pages[p]} for p in provinces if p in pages and pages[p] != provinces[p]}
    missing = sorted(p.code for p in g.provinces.values() if p.region_code not in out)
    return {
        "_comment": "PSGC の地域コード → PRSD。注意報(data/advisories)で挙げられた数の多い方。_counts が数(注意報の件数)。"
                    "_ambiguous の地域は州で割れているので、市町ページは _provinces(州のコード → PRSD)を先に引くこと。"
                    "作り方は db/prsd_regions.py。",
        "_counts": {r: dict(by_region[r].most_common()) for r in sorted(by_region)},
        "_ambiguous": ambiguous,
        "_provinces": provinces,
        "_province_counts": {p: dict(by_province[p].most_common()) for p in provinces if p in by_province},
        "_pages_disagree": disagree,
        "_regions_without_advisories": sorted({g.provinces[p].region_code for p in missing}),
        **out,
    }


def main() -> None:
    data = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    result = derive(data)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    g = load()
    for r, c in result["_ambiguous"].items():
        print(f"割れている: {r} {c}")
        for p, prsd in result["_provinces"].items():
            if g.provinces[p].region_code == r:
                print(f"    {p} {g.provinces[p].name}: {prsd} {result['_province_counts'].get(p, '(注意報なし → ページの一覧)')}")
    print("ページの一覧と食い違う州:", result["_pages_disagree"] or "なし")
    print("注意報に出てこない地域:", result["_regions_without_advisories"] or "なし")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
