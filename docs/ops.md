# 運用 — 収集の予備(Mac / launchd)

収集の**登録上の正は GitHub Actions**(`.github/workflows/collect.yml`、15 分ごと)。
この文書は、それが発火しなかったときに手元の Mac が肩代わりする**予備**(`scripts/fallback_collect.sh`)の話。

予備を足した理由: リポジトリを作った日、`schedule` が一度も発火しなかった(手動の `workflow_dispatch` だけ通った)。
GitHub の定期実行は遅れることも落ちることもあると明記されている(§7)ので、**穴を埋める側**を手元に置く。
ただし取得元(政府サイト)を二重に叩かないことが最優先で、予備は「正が止まっているときだけ」動く。

**実測(2026-09-21〜10-09)では、Actions の schedule は 1 日 4〜7 回しか発火しない**(設計は 96 回。§7)。
つまり 15 分間隔の大半を担っているのは Mac の予備で、Actions は Mac が止まっている(スリープ・停電・回線断)
間の穴埋めになっている。役割の名前はそのままにしてあるが、**予備が止まると 15 分間隔は失われる**。
2026-09-29〜10-09 はそうなっていた(§8)。

## 1. 予備がやること・やらないこと

やること:
- 15 分おきに起動し、`origin/main` の `state/*.json` を見て**正が生きているかだけ**を判定する。
- 正が 20 分以上成功していなければ、`python3 -m collector.run` を 1 回走らせ、`data` と `state` だけを
  `data: <UTC 時刻> (mac fallback)` で commit して push する。
- 完走したら `logs/stamps/fallback-YYYY-MM-DD` を touch する(JobsBar の「今日済」)。

やらないこと:
- **取得元への再試行・回避をしない。** 最小間隔とクールダウンは `collector/fetch.py` と `collector/run.py` が持っている。
  403 / 429 / challenge はその取得元を止めて `state/<key>.json` に記録するだけ(予備は何も足さない)。
- **持ち主の作業を触らない。** `main` に居ないか作業ツリーが汚れていれば、記録して非ゼロで終わる。
  stash も checkout もしない。例外は**自分が残した故障**だけ(§8): main の rebase が途中で止まっていれば
  `rebase --abort`、origin/main より先にある差分が全部 `(mac fallback)` のコミットなら `reset --hard origin/main`。
  持ち主のコミットが 1 つでも混ざっていれば触らない。
- **DB(D1)へ送らない**……のは当初の話で、2026-09-27 から正と同じ `db.send` で送る(末尾の節)。
- 正が生きているときにデータを取りに行かない(= 二重取得しない)。

## 2. 「古い」の決め方

`git fetch` したあと、**チェックアウトせずに** `git show origin/main:state/<key>.json` で `last_ok` を読む。
手元の `state/` は予備が走った分しか進まないので見ない。正が回っているかは origin にしか出ない。

見るのは**15 分間隔の取得元 3 つだけ**:

| key | 最小間隔 | 判定に使う |
|---|---|---|
| `phivolcs-eq` | 14 分 | ✓ |
| `pagasa-regional` | 14 分 | ✓ |
| `pagasa-ffws` | 14 分 | ✓ |
| `pagasa-tcb` | 29 分 | — |
| `phivolcs-volcano` | 59 分 | — |
| `pagasa-flood`(ダム) | 170 分 | — |

理由: 火山(60 分)やダム(3 時間)の `last_ok` は正が元気でも古いままになる。それを混ぜると
「正が止まった」と誤判定して二重に取りに行く。逆に 15 分ソースは正が 1 回回れば必ず新しくなるので、
**3 つのうち最新のもの**が正の生存時刻そのものになる。

- 最新の `last_ok` が **20 分以内** → 正は動いている → 何もせず `exit 0`(ログは 1 時間に 1 行だけ)。
- **20 分超** → 予備が走る。当初は 40 分(15 分周期 + GitHub 側の遅れを 1 回ぶん見逃しても誤発火しない幅)
  だったが、実測で Actions は 3〜7 時間おきにしか来ないので「遅れただけの正」との競合はほぼ起きず、
  40 分だと Actions が走るたびに 25 分の穴が空く。2026-10-09 に 20 分へ縮めた。
  同じ分に両方が commit して衝突しても、予備が自分のコミットを捨てて抜ける(§8)。
- どの state にも `last_ok` が無い → 古いとみなして走る。

例外: 3 つとも 24 時間クールダウン(403 など)に入ると `last_ok` が進まないので、予備は 15 分おきに
`collector.run` を呼び続ける。ただしクールダウン中の取得元には**行かない**ので外への通信は増えず、
差分も出ないので commit もされない。`state/<key>.json` の `cooldown_until` を見れば分かる。

## 3. 終了コードとログ

| コード | 意味 | JobsBar | 通知 |
|---|---|---|---|
| 0 | 正常(見送り、または収集して push まで完走) | 緑・今日のスタンプあり | なし |
| 1 | 今回は見送った/持ち越した(作業ツリーが汚れている・main に居ない・収集が NG・push を諦めた) | 赤(スタンプなし) | 3 時間続いたら 1 日 1 回 |
| 2 | 予備そのものが動けない(ロックを取れない・`git fetch` / `pull` が失敗) | 赤 | 毎回(plist 側)+ 上と同じ |

「3 時間続いたら」は `logs/.fallback-stale-since`(最初に収集できなかった時刻)で数える。収集して push できた回、
または正が動いていて見送った回に消える。通知は `logs/.fallback-notified` に日付を書いて 1 日 1 回に抑える。
これを足したのは、終了コード 1 が 10 日続いても誰も気づかなかったから(§8)。JobsBar のスタンプは
「正が動いていて見送った回」にも付くので、予備が壊れていても 1 日 1 回の Actions でスタンプが付き、緑に見える。

- ログ: `logs/launchd-fallback.log`(launchd の stdout / stderr をまとめてここへ)。
- 平常時は 1 時間に 1 行しか書かない(`logs/.fallback-quiet` に最後に書いた時刻を持つ)。
- 太ってきたら `: > logs/launchd-fallback.log` で空にする(削除するとジョブが起動しなくなる場合がある。
  `jobsbar/docs/launchd-jobs.md` の EX_CONFIG の項)。
- ロックは `logs/fallback.lock`(`mkdir`)。45 分より古い残骸は踏み越える(SIGKILL で trap が走らないため)。

**`logs/` は git 管理に入れない。** `.gitignore` に以下が無いと、予備が作る `logs/` 自身で作業ツリーが
汚れ続け、予備は永久に見送る(ログにその旨を出す):

```
logs/
```

## 4. 登録・解除・確認

```bash
# 登録(ここではやっていない。持ち主が判断して実行する)
# 予備専用の clone を作って、そこから登録する(開発用の作業ツリーに入れない。汚れていると予備が走らないため)
git clone git@github.com.krystasis:krystasis/ph-hazards.git ~/Library/Application\ Support/ph-hazards-fallback
~/Library/Application\ Support/ph-hazards-fallback/scripts/launchd/install.sh

# 確認
launchctl list | grep ph_hazards
launchctl print gui/$(id -u)/com.kazuki.ph_hazards.fallback | head -40
tail -f logs/launchd-fallback.log
ls -l logs/stamps/

# 今すぐ 1 回
launchctl kickstart -k gui/$(id -u)/com.kazuki.ph_hazards.fallback

# 手で確かめる(何も変えない)
scripts/fallback_collect.sh --dry-run

# 解除
launchctl bootout gui/$(id -u)/com.kazuki.ph_hazards.fallback
rm ~/Library/LaunchAgents/com.kazuki.ph_hazards.fallback.plist   # または scripts/launchd/install.sh --remove
```

前提:
- `/bin/bash` に Full Disk Access(無いと launchd から `~/Documents` を読めず、エラーも出ずに何も起きない)。
- push は ssh(`github.com.krystasis` の `IdentityFile`)。鍵にパスフレーズがあるので、**ssh-agent / キーチェーンに
  読み込まれている必要がある**。読み込まれていないと `git fetch` の時点でコード 2 で止まり、通知が出る。
- 正(Actions)を止めるわけではない。予備は正と共存する前提で、両方が同時に走っても
  `git pull --rebase` と push の再送で吸収する(押し戻されたら 1 回だけやり直し、駄目なら次の 15 分)。
  rebase が衝突したら自分のコミットを捨てる(§8)。同じ分のデータは正が取っている。
- スクリプトや plist を変えたら、予備用 clone で `git pull` してから `scripts/launchd/install.sh` を入れ直す
  (plist は登録時にコピーされるので、clone を進めただけでは `Comment` などが変わらない)。

## 5. どちらが作ったコミットか

両方とも `ph-hazards-bot <actions@users.noreply.github.com>` 名義なので、**コミットメッセージで見分ける**。

| 作った側 | メッセージ |
|---|---|
| GitHub Actions(正) | `data: 2026-09-21T03:48Z` |
| Mac(予備) | `data: 2026-09-21T06:54Z (mac fallback)` |

```bash
git log --oneline -20 -- data state            # 並びを見る
git log --oneline --grep='mac fallback' -10    # 予備が出た回だけ
```

予備のコミットが続いているなら正が落ちている。Actions 側は `gh run list --workflow collect.yml -L 20` で見る
(`created`/`event` が `schedule` の行が出ていなければ定期実行が発火していない)。

## 6. 両方止まったとき

1. まず外(取得元)が拒否していないか: `state/<key>.json` の `cooldown_until` と `last_block`。
   拒否されているなら**待つ**。回避は書かない(CLAUDE.md)。
2. 手で 1 回:
   ```bash
   python3 -m unittest discover -s tests   # 通信なし。解析が壊れていないか
   python3 -m collector.run                # 最小間隔は守られる
   python3 -m collector.run --only phivolcs-eq --force
   ```
   取れたら `data` と `state` を手で commit して push する。
3. 穴の埋め方は取得元によって違う:
   - 地震 — ページが当月の全件を載せているので、後から回せば埋まる(`collector/backfill_eq.py` は過去の月用)。
   - ダム・火山 — 1 日 1 行なので、その日のうちに 1 回でも回れば埋まる。
   - 注意報(`data/advisories`)・河川水位・台風公報 — **その時刻の発表しか出ていないので後から取れない**。
     止まっていた間は欠測として残る。長く止めない。
4. Actions が 60 日ルールで無効化されていたら、リポジトリの Actions 画面から有効化し直す(§7)。

## 7. GitHub Actions の定期実行について(確認済み / 未確認)

docs.github.com「Events that trigger workflows」で確認した(2026-09-21 に参照):

- `schedule` は Actions の負荷が高いときに**遅れる**。毎時 00 分ちょうどが混む(だから `collect.yml` は
  7 / 22 / 37 / 52 分にずらしてある)。
- 負荷が十分高いと、**キューに入ったジョブが落とされる**ことがある(= その回は走らない)。
- 最短間隔は 5 分。
- **公開リポジトリでは、60 日間リポジトリに何も活動が無いと定期実行が自動で無効化される。**
  このリポジトリは収集が commit を作り続ける限り該当しない。予備だけで回っている間も commit は出るので、
  その意味でも予備は無効化避けになる。
- 定期実行は**デフォルトブランチの最新コミットでしか走らない**。

未確認(このセッションでは裏を取っていない。断定しない):

- **リポジトリ / ワークフローを作った直後、最初の `schedule` が発火するまでに時間がかかる**のか。
  今回「作った日に一度も発火しなかった」のがこれなのか、単に落とされ続けたのかは切り分けられていない。
- 遅れの実際の幅(「10〜30 分」は `collect.yml` のコメントにある経験則で、GitHub が数字で示している値ではない)。
- 落とされた回が後から追いかけて実行されるのか(されないと見ているが、根拠は取っていない)。

切り分けは `gh run list --workflow collect.yml -L 50` で `schedule` の行が何分おきに出ているかを見る。

**実測(2026-10-09 に 200 回ぶんを集計)**: 2026-09-21 から毎日 **4〜7 回**しか `schedule` が発火していない
(設計は 96 回)。間隔は 3〜7 時間で、「作った直後だけ」ではなく恒常的。失敗は 19 日間で 14 回あり、
9/26 に 8 回集中している以外は PHIVOLCS の 502 など取得元側の一時的なもの。
落とされた回が後から追いかけて実行される様子は無い(発火の間隔がそのまま穴になっている)。

結論: GitHub の無料の schedule は 15 分間隔の収集には使えない。設計上の「正」は Actions のままだが、
実際の 15 分間隔は Mac の予備が担う。Actions は Mac が止まっているときの穴埋め(1 日数回は取れる)と、
60 日の無活動で無効化されないためのもの。Mac を止める(引っ越し・長期の停電)ときは、
注意報・河川水位・台風公報が 1 日数回の粒度に落ちると承知しておく。

```bash
gh run list --workflow collect.yml -L 200 --json createdAt,event \
  -q '.[] | select(.event=="schedule") | .createdAt[0:10]' | sort | uniq -c   # 1 日の発火回数
```

## 8. 予備が 10 日止まった(2026-09-29〜10-09)

2026-09-29T02:15Z、予備と Actions が同じ分に同じファイル(`data/advisories/2026-09.jsonl` と `state/*.json`)を
commit し、予備の push 前の `git pull --rebase` が衝突した。スクリプトは「持ち主の作業を触らない」ため
rebase を abort せず、予備用 clone は rebase 途中の detached HEAD で残った。以後 723 回、15 分おきに
「main ではなく HEAD に居るので見送る」で終了コード 1。通知はコード 2 以上にしか無く、JobsBar のスタンプは
Actions が生きている瞬間の見送り(コード 0)で毎日付いたので、見た目は緑のまま 10 日間止まっていた。

その間 Actions だけが動き、1 日 4〜6 回の収集になった(河川水位は 17 局 × 5 回 ≒ 85 行/日、注意報の発令・解除の
時刻は 3〜7 時間の粗さ)。注意報・河川水位・台風公報の欠測は後から埋められない(§6)。

直したこと(2026-10-09):
- 予備用 clone: `git rebase --abort` し、衝突した自分のコミットを `backup/mac-fallback-2026-09-29` に残して main を
  origin/main に揃えた。
- `scripts/fallback_collect.sh`: 走る前と rebase に失敗したときに `recover` を呼ぶ。main の rebase が途中なら abort、
  origin/main との差分が全部 `(mac fallback)` のコミットなら `reset --hard origin/main`。持ち主の物が混ざっていれば触らない。
- 終了コード 1 / 2 が 3 時間続いたら 1 日 1 回 macOS 通知(§3)。
- 判定の幅を 40 分 → 20 分(§2)。

## D1 への送信(予備側、2026-09-27 追加)

- 予備も、正(Actions)と同じ `python3 -m db.send data` で D1 に送る。予算(1 日の書き込み行数)は `state/d1-usage.json` がコミットされて共有されるので、両方が走っても合計で守られる。
- 資格情報は `~/.config/ph-hazards/d1.env`(`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` / `D1_DATABASE_ID`、`chmod 600`)。無ければ送らない。
- 正の GitHub の定期実行は数時間遅れることがあり、予備だけが動いている時間帯はサイトの D1 が古くなる。それを防ぐための追加。
