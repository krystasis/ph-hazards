#!/usr/bin/env bash
# Actions から data / state を commit して push する(.github/workflows/collect.yml の 2 か所から呼ぶ)。
#   scripts/push_commit.sh "<コミットのメッセージ>" <パス>...
#
# 予備(Mac)と同じ分に commit すると pull --rebase が衝突し、rebase 途中で止まって赤くなる
# (2026-10-13 16:21Z。state/phivolcs-eq.json などが両方で更新されていた)。予備の側はすでに自分のコミットを
# 捨てて抜けるので(scripts/fallback_collect.sh)、こちらも同じにする: rebase を戻し、今回のコミットを捨てて
# origin/main に揃え、警告だけ出して 0 で終わる。捨てるのは同じ分のデータで、予備が取って push している。
# 取得元へ取りに戻らない(再取得はしない)。
# D1 の state で捨てた場合: manifest は次の回が同じ単位を送り直す(文は冪等)。d1-usage はこの回に書いた分だけ
# 少なく数えるが、上限の内側の --reserve に収まる。
set -uo pipefail
msg="$1"; shift
git config user.name "ph-hazards-bot"
git config user.email "actions@users.noreply.github.com"
for p in "$@"; do
  if [ -e "$p" ]; then git add "$p"; fi
done
if git diff --cached --quiet; then
  echo "変更なし"
  exit 0
fi
git commit -q -m "$msg" || exit 1

# pull と push の間に予備が push して押し戻されることもあるので、取り込み直しは 1 回だけ足す。
for _ in 1 2; do
  if ! git pull -q --rebase; then
    git rebase --abort 2>/dev/null || true
    git fetch -q origin && git reset -q --hard origin/main || exit 1
    echo "::warning::pull --rebase が衝突した(予備が同じ分に push した)。今回のコミットを捨てて origin/main に揃えた: $msg"
    exit 0
  fi
  if git push -q; then exit 0; fi
done
echo "::error::push できなかった: $msg"
exit 1
