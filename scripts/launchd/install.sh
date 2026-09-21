#!/usr/bin/env bash
# 予備の収集(launchd)を登録する。plist のひな形にこのリポジトリの場所を埋めて ~/Library/LaunchAgents へ置く。
#   scripts/launchd/install.sh            … 登録(入れ直しも可)
#   scripts/launchd/install.sh --remove   … 解除
# **開発に使っている作業ツリーではなく、予備専用の clone から実行する。** 作業ツリーが汚れていると予備は
# 走らない(持ち主の作業を巻き込まないため)ので、開発用の場所に入れると肝心なときに見送り続ける。
set -euo pipefail
LABEL=com.kazuki.ph_hazards.fallback
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
  rm -f "$DEST"
  echo "解除した: $LABEL"
  exit 0
fi
mkdir -p "$REPO/logs/stamps" "$HOME/Library/LaunchAgents"
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" "$REPO/scripts/launchd/$LABEL.plist.template" > "$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "登録した: $LABEL → $REPO"
echo "ログ: $REPO/logs/launchd-fallback.log"
