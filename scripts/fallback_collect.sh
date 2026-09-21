#!/usr/bin/env bash
# 収集の「予備」。正は GitHub Actions(.github/workflows/collect.yml、15 分ごと)で、
# **それが発火しなかったときだけ**この Mac が代わりに 1 回分を回す。launchd(15 分おき)から呼ぶ。
#   scripts/fallback_collect.sh            … 判定 → 古ければ収集 → data/state を commit して push
#   scripts/fallback_collect.sh --dry-run  … 判定と「何をするつもりか」を出すだけ(git fetch 以外は何も触らない)
#
# 二重取得をしないために、走るかどうかは **origin/main の state/*.json の last_ok** だけで決める
# (手元の state は予備が走った分しか進まないので見ない)。判定の詳しい理由は docs/ops.md。
# 取得元ごとの最小間隔・クールダウンは collector/fetch.py と collector/run.py が持っている。
# ここには再試行ループも回避策も書かない(403 / 429 / challenge はその取得元を止めるだけ)。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
JOB=fallback
FRESH_MIN=40                                            # origin/main がこの分数以内に成功していれば見送る
FAST_KEYS=(phivolcs-eq pagasa-regional pagasa-ffws)      # 15 分間隔の取得元。判定はこの 3 つだけで行う
BOT=(-c user.name=ph-hazards-bot -c user.email=actions@users.noreply.github.com)  # 持ち主のメールを出さない

DRY=0
for a in "$@"; do case "$a" in --dry-run|-n) DRY=1 ;; *) echo "不明な引数: $a" >&2; exit 2 ;; esac; done

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ---- ロック(重ねない) ----------------------------------------------------
# 15 分おきに起動するので、前回が長引いていたら今回は黙って見送る。
# bash は SIGKILL では EXIT トラップを走らせない(launchd がログアウトで殺すとロックが残る)。
# 残骸を踏み越えないと以後ずっと「skip」し続け、終了コード 0 なので誰も気づけない(sweldex で踏んだ)。
if [ "$DRY" = 0 ]; then
  mkdir -p logs logs/stamps || exit 2
  LOCK="logs/$JOB.lock"
  if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +45 2>/dev/null)" ]; then
      log "⚠ 45 分より古いロックが残っていたので踏み越える: $LOCK"
      rmdir "$LOCK" 2>/dev/null
      mkdir "$LOCK" 2>/dev/null || { log "✘ ロックを取れない"; exit 2; }
    else
      exit 0   # 前回がまだ走っている。次の 15 分に回す(ログも出さない)
    fi
  fi
  trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
fi

# ---- 正(GitHub Actions)の新しさを見る ------------------------------------
if ! git fetch --quiet origin 2>/dev/null; then
  log "✘ git fetch に失敗した(ssh 鍵が agent に無い・回線断)。次の起動で再試行する"
  exit 2
fi

# origin/main の state を **チェックアウトせずに** 読む(作業ツリーに触らない)。
# 終了コード 0 = 十分新しい(見送り) / 1 = 古い(走る)。1 行の要約を stdout に出す。
freshness() {
  python3 - "$FRESH_MIN" "${FAST_KEYS[@]}" <<'PY'
import json, subprocess, sys
from datetime import datetime, timezone

fresh_min, keys = int(sys.argv[1]), sys.argv[2:]
now, best, parts = datetime.now(timezone.utc), None, []
for key in keys:
    try:
        out = subprocess.run(["git", "show", f"origin/main:state/{key}.json"],
                             capture_output=True, text=True, check=True).stdout
        last_ok = json.loads(out).get("last_ok")
    except Exception:
        last_ok = None
    if not last_ok:
        parts.append(f"{key}=last_ok 無し")
        continue
    age = (now - datetime.fromisoformat(last_ok)).total_seconds() / 60
    parts.append(f"{key}={age:.0f}分前")
    if best is None or age < best[1]:
        best = (key, age)
summary = " / ".join(parts)
if best is None:
    print(f"origin/main に成功記録が無い({summary})→ 古いとみなす")
    sys.exit(1)
key, age = best
verdict = "新しい(見送り)" if age < fresh_min else f"古い({fresh_min} 分超)"
print(f"origin/main の 15 分ソース: {summary} → 最新は {key} の {age:.0f} 分前 → {verdict}")
sys.exit(0 if age < fresh_min else 1)
PY
}

VERDICT="$(freshness)"; STALE=$?

if [ "$DRY" = 1 ]; then
  echo "== dry-run(何も変えない) $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "判定: $VERDICT"
  echo "基準: 15 分ソース($(echo "${FAST_KEYS[*]}" | tr ' ' ','))の last_ok の最新が ${FRESH_MIN} 分以内なら見送る"
  echo "ブランチ: $(git rev-parse --abbrev-ref HEAD)  作業ツリー: $([ -z "$(git status --porcelain)" ] && echo クリーン || echo '汚れている(予備は走らない)')"
  git status --porcelain | head -10 | sed 's/^/  /'
  if [ "$STALE" = 0 ]; then
    echo "やること: 何もしない(1 時間に 1 行だけログに残して exit 0)"
  else
    echo "やること: git pull --rebase → python3 -m collector.run → data と state だけを"
    echo "          'data: $(date -u +%Y-%m-%dT%H:%MZ) (mac fallback)' で commit(ph-hazards-bot 名義)→ pull --rebase → push"
    echo "          (押し戻されたら 1 回だけ rebase して再送。それでも駄目なら次の 15 分に回す)"
  fi
  exit 0
fi

if [ "$STALE" = 0 ]; then
  # ログを太らせないため、平常時は 1 時間に 1 行だけ残す。
  hour="$(date -u +%Y-%m-%dT%H)"
  if [ "$(cat "logs/.$JOB-quiet" 2>/dev/null)" != "$hour" ]; then
    log "正(Actions)は動いている。$VERDICT"
    echo "$hour" > "logs/.$JOB-quiet"
  fi
  touch "logs/stamps/$JOB-$(date +%Y-%m-%d)"
  exit 0
fi

# ---- ここから予備として 1 回分を回す --------------------------------------
log "== 予備として走る。$VERDICT"

# 持ち主の作業を絶対に巻き込まない(stash も reset もしない)。
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  log "✘ main ではなく $BRANCH に居るので見送る(持ち主の作業中)。"
  exit 1
fi
DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ]; then
  log "✘ 作業ツリーが汚れているので見送る(コミットも退避もしない):"
  echo "$DIRTY" | head -10
  # logs/ が .gitignore に入っていないと、このスクリプトが作った logs/ 自身で永久に見送り続ける。
  case "$DIRTY" in *"logs/"*) log "   → logs/ が追跡対象のままになっている。.gitignore に logs/ を足す(docs/ops.md)" ;; esac
  exit 1
fi

if ! git pull -q --rebase; then
  log "✘ git pull --rebase に失敗した。次の起動で再試行する"
  exit 2
fi

python3 -m collector.run; COLLECT=$?
[ "$COLLECT" = 0 ] || log "⚠ 収集が NG を返した(解析 0 件・拒否など)。取れた分と state は残す"

git add data state
if git diff --cached --quiet; then
  log "変更なし(commit しない)"
  # 取れなかったのではなく「変わっていない」だけなので、完走として扱う。
  touch "logs/stamps/$JOB-$(date +%Y-%m-%d)"
  exit $([ "$COLLECT" = 0 ] && echo 0 || echo 1)
fi

git "${BOT[@]}" commit -q -m "data: $(date -u +%Y-%m-%dT%H:%MZ) (mac fallback)" || { log "✘ commit に失敗"; exit 2; }
git "${BOT[@]}" pull -q --rebase || { log "✘ push 前の pull --rebase に失敗。次の起動で持ち越す"; exit 1; }
if ! git push -q; then
  # 正が直前に push した可能性。1 回だけ rebase して送り直し、それでも駄目なら次の 15 分に回す
  # (収集済みの分はローカルの commit に残っているので取り直さない)。
  log "⚠ push を押し戻された。1 回だけ rebase して再送する"
  if ! { git "${BOT[@]}" pull -q --rebase && git push -q; }; then
    log "✘ 再送も駄目だった。次の起動で送る"
    exit 1
  fi
fi
log "push した"

# --- DB 送信のフック(未実装・無効) ----------------------------------------
# D1 への送信はここに入る。別の担当が db/ 側を作っている最中なので、**まだ呼ばない**。
# 有効にするときは 1 行のコメントを外し、失敗しても収集は完走扱いにする(D1 は写しで作り直せる)。
#   python3 -m db.send data || log "⚠ db.send が失敗した(次回に持ち越す)"
# ---------------------------------------------------------------------------

touch "logs/stamps/$JOB-$(date +%Y-%m-%d)"
log "== done"
exit $([ "$COLLECT" = 0 ] && echo 0 || echo 1)
