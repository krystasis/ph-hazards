"""Actions の定期実行の入口で、すでに誰か(ほぼ Mac の予備)が直近に取っているかを見る。

    python3 scripts/primary_fresh.py [分]   # 既定 10

15 分ソース 3 つの state/<key>.json の last_ok の最新が [分] 以内なら「新しい」。
GITHUB_OUTPUT があれば run=false / run=true を書く(.github/workflows/collect.yml の gate)。
判定は scripts/fallback_collect.sh の freshness() と同じ(見る取得元・幅)。両方が同じ分に走って
push が衝突するのを減らすためで、Mac が止まっていれば last_ok が古くなり、Actions がそのまま取りに行く。
"""
import json
import os
import sys
from datetime import datetime, timezone

FAST_KEYS = ("phivolcs-eq", "pagasa-regional", "pagasa-ffws")


def main() -> int:
    fresh_min = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    now, best, parts = datetime.now(timezone.utc), None, []
    for key in FAST_KEYS:
        try:
            with open(f"state/{key}.json", encoding="utf-8") as f:
                last_ok = json.load(f).get("last_ok")
        except (OSError, ValueError):
            last_ok = None
        if not last_ok:
            parts.append(f"{key}=last_ok 無し")
            continue
        age = (now - datetime.fromisoformat(last_ok)).total_seconds() / 60
        parts.append(f"{key}={age:.0f}分前")
        if best is None or age < best:
            best = age
    run = best is None or best >= fresh_min
    print(" / ".join(parts), "→", "取りに行く" if run else f"{fresh_min} 分以内に取れているので見送る")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
