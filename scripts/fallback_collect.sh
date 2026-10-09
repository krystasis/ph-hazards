#!/usr/bin/env bash
# 収集の「予備」。登録上の正は GitHub Actions(.github/workflows/collect.yml、15 分ごと)だが、
# GitHub の schedule は実測で 1 日 4〜7 回しか発火しない(2026-09-21〜10-09)。実際にはこの Mac が
# 15 分間隔の大半を担い、Actions は Mac が止まっている(スリープ・停電・回線断)間の穴埋めになっている。
# launchd(15 分おき)から呼ぶ。
#   scripts/fallback_collect.sh            … 判定 → 古ければ収集 → data/state を commit して push
#   scripts/fallback_collect.sh --dry-run  … 判定と「何をするつもりか」を出すだけ(git fetch 以外は何も触らない)
#
# 二重取得をしないために、走るかどうかは **origin/main の state/*.json の last_ok** だけで決める
# (手元の state は予備が走った分しか進まないので見ない)。判定の詳しい理由は docs/ops.md。
# 取得元ごとの最小間隔・クールダウンは collector/fetch.py と collector/run.py が持っている。
# ここには再試行ループも回避策も書かない(403 / 429 / challenge はその取得元を止めるだけ)。
#
# 自分で抜ける故障: Actions と同じ分に commit すると pull --rebase が衝突し、rebase 途中(detached HEAD)で
# 残る。2026-09-29 にこれで 10 日間止まった(終了コード 1 なので通知も出ず、JobsBar は緑のまま)。
# いまは「rebase 中なら abort、自分の (mac fallback) コミットだけが残っていれば origin/main に揃える」で抜ける。
# 捨てるのは自分が取った同じ分のデータで、正が同じ時刻に取っている。持ち主のコミットは触らない。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
JOB=fallback
FRESH_MIN=10                                            # origin/main がこの分数以内に成功していれば見送る。15 分の起動間隔より短くしないと 1 回おきに見送って 30 分間隔になる。取得元への間隔は collector 側の 14 分が守る
STUCK_MIN=180                                           # 古いのに収集できない状態がこの分数続いたら macOS 通知
FAST_KEYS=(phivolcs-eq pagasa-regional pagasa-ffws)      # 15 分間隔の取得元。判定はこの 3 つだけで行う
BOT=(-c user.name=ph-hazards-bot -c user.email=actions@users.noreply.github.com)  # 持ち主のメールを出さない
OWN_RE='\(mac fallback\)$'                                 # 予備が作るコミットの印。これ以外は自分の物とみなさない

DRY=0
for a in "$@"; do case "$a" in --dry-run|-n) DRY=1 ;; *) echo "不明な引数: $a" >&2; exit 2 ;; esac; done

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ---- 「古いのに収集できていない」が続いたら通知する -----------------------------
# 見送り(exit 1)や故障(exit 2)が単発なら黙る。STUCK_MIN 以上続いたときだけ、1 日 1 回 macOS 通知を出す。
# 収集して push まで通ったら(または正が動いていて見送りなら)記録を消す。
STALE_SINCE="logs/.$JOB-stale-since"
NOTIFIED="logs/.$JOB-notified"
ok_exit() { rm -f "$STALE_SINCE"; exit "${1:-0}"; }
fail_exit() {  # fail_exit <code> <短い理由>
  local code="$1" why="$2" now since age today
  now=$(date +%s)
  if [ -s "$STALE_SINCE" ]; then since=$(cat "$STALE_SINCE"); else since=$now; echo "$now" > "$STALE_SINCE"; fi
  age=$(( (now - since) / 60 ))
  today=$(date +%Y-%m-%d)
  if [ "$age" -ge "$STUCK_MIN" ] && [ "$(cat "$NOTIFIED" 2>/dev/null)" != "$today" ]; then
    log "⚠ ${age} 分間 収集できていない(${why})。macOS 通知を出す"
    osascript -e "display notification \"${age} 分間 収集できていない: ${why}。logs/launchd-fallback.log を見る\" with title \"ph_hazards 予備\"" 2>/dev/null || true
    echo "$today" > "$NOTIFIED"
  fi
  exit "$code"
}

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
  [ "$DRY" = 1 ] && exit 2
  fail_exit 2 "git fetch 失敗"
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

# ---- 自分が残した故障から抜ける ---------------------------------------------
# 対象は「予備が自分で作った状態」だけ:
#   1. main を rebase している途中で止まっている(rebase-merge/head-name が refs/heads/main)→ abort
#   2. main が origin/main より先にいて、その差分が全部 "(mac fallback)" のコミット → origin/main に揃える
#      (同じ分のデータは正が取って push している。衝突したまま持ち続けると毎回 rebase が失敗して永久に見送る)
# それ以外(持ち主のブランチ・持ち主のコミット・汚れた作業ツリー)は触らず、見送るだけ。
recover() {
  local gd head_name own total
  gd="$(git rev-parse --git-dir)"
  if [ -d "$gd/rebase-merge" ] || [ -d "$gd/rebase-apply" ]; then
    head_name="$(cat "$gd/rebase-merge/head-name" "$gd/rebase-apply/head-name" 2>/dev/null | head -1)"
    if [ "$head_name" = "refs/heads/main" ]; then
      if [ "$DRY" = 1 ]; then echo "やること(復旧): main の rebase が途中なので abort する"; else
        git rebase --abort 2>/dev/null && log "↺ 止まっていた main の rebase を abort した(自分が残した物)"
      fi
    else
      log "✘ main 以外($head_name)の rebase が途中なので触らない(持ち主の作業中)"
      return 1
    fi
  fi
  if [ "$(git rev-parse --abbrev-ref HEAD)" = "main" ]; then
    total=$(git rev-list --count origin/main..main)
    if [ "$total" -gt 0 ]; then
      own=$(git log --format=%s origin/main..main | grep -cE "$OWN_RE")
      if [ "$own" = "$total" ]; then
        if [ "$DRY" = 1 ]; then echo "やること(復旧): 自分の (mac fallback) コミット $total 個を捨てて origin/main に揃える"; else
          git reset -q --hard origin/main && log "↺ 自分の (mac fallback) コミット $total 個を捨てて origin/main に揃えた(同じ分は正が取っている)"
        fi
      else
        log "✘ main に持ち主のコミットが $((total - own)) 個ある(push されていない)ので触らない"
        return 1
      fi
    fi
  fi
  return 0
}

VERDICT="$(freshness)"; STALE=$?

if [ "$DRY" = 1 ]; then
  echo "== dry-run(何も変えない) $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "判定: $VERDICT"
  echo "基準: 15 分ソース($(echo "${FAST_KEYS[*]}" | tr ' ' ','))の last_ok の最新が ${FRESH_MIN} 分以内なら見送る"
  echo "ブランチ: $(git rev-parse --abbrev-ref HEAD)  作業ツリー: $([ -z "$(git status --porcelain)" ] && echo クリーン || echo '汚れている(予備は走らない)')"
  git status --porcelain | head -10 | sed 's/^/  /'
  recover || true
  if [ "$STALE" = 0 ]; then
    echo "やること: 何もしない(1 時間に 1 行だけログに残して exit 0)"
  else
    echo "やること: git pull --rebase → python3 -m collector.run → data と state だけを"
    echo "          'data: $(date -u +%Y-%m-%dT%H:%MZ) (mac fallback)' で commit(ph-hazards-bot 名義)→ pull --rebase → push"
    echo "          (押し戻されたら 1 回だけ rebase して再送。それでも駄目なら次の 15 分に回す)"
  fi
  [ -s "$STALE_SINCE" ] && echo "収集できていない期間: $(( ($(date +%s) - $(cat "$STALE_SINCE")) / 60 )) 分(${STUCK_MIN} 分で通知)"
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
  ok_exit 0
fi

# ---- ここから予備として 1 回分を回す --------------------------------------
log "== 予備として走る。$VERDICT"

# 自分が残した故障(rebase 途中・衝突した自分のコミット)なら抜ける。持ち主の物なら触らず見送る。
recover || fail_exit 1 "持ち主の作業中"

# 持ち主の作業を絶対に巻き込まない(stash も checkout もしない。reset は上の recover が自分のコミットにだけ使う)。
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  log "✘ main ではなく $BRANCH に居るので見送る(持ち主の作業中)。"
  fail_exit 1 "main ではなく $BRANCH"
fi
DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ]; then
  log "✘ 作業ツリーが汚れているので見送る(コミットも退避もしない):"
  echo "$DIRTY" | head -10
  # logs/ が .gitignore に入っていないと、このスクリプトが作った logs/ 自身で永久に見送り続ける。
  case "$DIRTY" in *"logs/"*) log "   → logs/ が追跡対象のままになっている。.gitignore に logs/ を足す(docs/ops.md)" ;; esac
  fail_exit 1 "作業ツリーが汚れている"
fi

if ! git pull -q --rebase; then
  log "✘ git pull --rebase に失敗した。rebase を戻して次の起動で再試行する"
  recover || true
  fail_exit 2 "pull --rebase 失敗"
fi

python3 -m collector.run; COLLECT=$?
[ "$COLLECT" = 0 ] || log "⚠ 収集が NG を返した(解析 0 件・拒否など)。取れた分と state は残す"

git add data state
if git diff --cached --quiet; then
  log "変更なし(commit しない)"
  # 取れなかったのではなく「変わっていない」だけなので、完走として扱う。
  touch "logs/stamps/$JOB-$(date +%Y-%m-%d)"
  [ "$COLLECT" = 0 ] && ok_exit 0 || fail_exit 1 "収集が NG"
fi

git "${BOT[@]}" commit -q -m "data: $(date -u +%Y-%m-%dT%H:%MZ) (mac fallback)" || { log "✘ commit に失敗"; fail_exit 2 "commit 失敗"; }
if ! git "${BOT[@]}" pull -q --rebase; then
  # 正が同じ分に同じファイルを push した。rebase を戻し、自分のコミットは捨てる(同じ分は正が取っている)。
  log "✘ push 前の pull --rebase が衝突した。自分のコミットを捨てて次の起動に回す"
  recover || true
  fail_exit 1 "push 前の rebase が衝突"
fi
if ! git push -q; then
  # 正が直前に push した可能性。1 回だけ rebase して送り直し、それでも駄目なら次の 15 分に回す
  # (収集済みの分はローカルの commit に残っているので取り直さない)。
  log "⚠ push を押し戻された。1 回だけ rebase して再送する"
  if ! { git "${BOT[@]}" pull -q --rebase && git push -q; }; then
    log "✘ 再送も駄目だった。rebase を戻して次の起動で送る"
    recover || true
    fail_exit 1 "push できない"
  fi
fi
log "push した"

# --- D1 への送信 ------------------------------------------------------------
# 正(Actions)と同じ物を、同じ予算(state/d1-usage.json は commit されているので両者で共有)で送る。
# 資格情報はリポジトリの外(~/.config/ph-hazards/d1.env、CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID / D1_DATABASE_ID)。
# 無ければ何もしない。失敗しても収集は完走扱い(D1 は写しで、次の回が送り直す)。
D1_ENV="$HOME/.config/ph-hazards/d1.env"
if [ -r "$D1_ENV" ]; then
  set -a; . "$D1_ENV"; set +a
  if python3 -m db.send data; then
    git add state/d1-manifest.json state/d1-usage.json 2>/dev/null
    if ! git diff --cached --quiet; then
      git "${BOT[@]}" commit -q -m "d1: $(date -u +%Y-%m-%dT%H:%MZ) (mac fallback)" \
        && { git "${BOT[@]}" pull -q --rebase && git push -q || { log "⚠ d1 state の push に失敗(次回に持ち越す)"; recover || true; }; }
    fi
  else
    log "⚠ db.send が失敗した(次回に持ち越す)"
    git checkout -q -- state/d1-manifest.json state/d1-usage.json 2>/dev/null || true
  fi
fi

touch "logs/stamps/$JOB-$(date +%Y-%m-%d)"
log "== done"
[ "$COLLECT" = 0 ] && ok_exit 0 || fail_exit 1 "収集が NG"
