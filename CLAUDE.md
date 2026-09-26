# CLAUDE.md — ph-hazards

フィリピンの天気・災害の公開データを集めて残す収集器。このリポジトリは公開。
計画や判断のメモはここに置かない(手元の別ファイルにある)。トークンや各種 ID を直書きしない(Actions の secrets に入れる)。

## 決まり
- 有料の API・有料プランを足さない。
- 取得元は `docs/sources/<key>.md` に robots / 規約 / 取り方を書いてから向ける。status が approved 以外の物は取らない。
- 403 / 429 / challenge は即停止 + `state/<key>.json` に記録 + クールダウン(`collector/fetch.py`)。回避は書かない。
  GitHub の IP が拒否されたら、その取得元は止めたままにする。
- TLS の検証は切らない。PHIVOLCS は中間証明書を送ってこないので、公開されている中間証明書を
  `collector/certs/` に同梱している(GlobalSign の 2 枚。期限は 2028-11-21 と、もう 1 枚は `openssl x509 -enddate` で確認。切れる前に差し替える)。河川水位のホストも同じ事情。
- 個人名・連絡先は保存しない(今の取得元には含まれない)。
- 依存は標準ライブラリだけ(Actions で pip install しない)。

## 定期実行の例外
**収集は GitHub Actions(`.github/workflows/collect.yml`)で回す。** 手元のマシンの停電・回線断に左右されないようにするため。

## 場所の名寄せと D1 への書き出し
- `vendor/psgc/` — PSGC の地域・州・市町(PyPI `psgc`、MIT)。四半期に 1 回差し替える。
- `places/` — 注意報の本文と地震の location を PSGC の市町コードに当てる。外れた名前は `places/aliases.json` に手で足す。
- `db/schema.sql` — D1 のスキーマ。問い合わせは全部インデックスで引ける形にする(D1 の無料枠は走査した行数で数える)。
- `db/export.py` — **前回から変わった行だけ**の SQL を作る。月のファイルを丸ごと送らない(1 日 10 万行の上限を超える)。
  `plan()` が SQL を「単位」に区切る(表 1 つ、または地震の 1 か月)。単位は *全部送れたときだけ* manifest を進める最小のかたまり。
- `db/send.py` — その単位を D1 へ送る。下の決まりを守る。
- `db/verify_local.py` — 手元の SQLite でスキーマ・差分・削除の追従・問い合わせ計画を確かめる。
- `db/prsd_regions.json` — PSGC の地域(割れている地域は州)→ PRSD。`python3 -m db.prsd_regions data` で注意報から作り直す。

### D1 へ送るときの決まり(`db/send.py`)
- **送れた分だけ manifest を進める。** 途中で失敗したらそこで止めて 0 以外で終わる(Actions が赤くなる)。
  文は INSERT OR REPLACE か「範囲 DELETE → 入れ直し」なので、次の回が同じ単位を丸ごと送り直せばよい。
- **1 日の書き込み上限**は `state/d1-usage.json`(UTC の日付ごと)。数えるのは **API が返した `rows_written`**(索引の更新も入るので、送った行数より多い)。
  既定 6 万行。無料枠 10 万行は **アカウント全体で** もう 1 つのアプリと共有なので、残りは空けておく。
  上限に当たって止めるのは失敗ではない(0 で終わる)。上限の内側にさらに `--reserve`(既定 1 万)を空け、過去分の積み残しはそこまでで止める。
- **送る順**は「小さい表 → 直近 2 か月の地震 → 過去分は新しい月から」。新しいデータを過去分の積み残しで待たせない。
- 過去分の地震(13.5 万件)は 1 回 `--eq-rows`(既定 4000)行ずつ。日々の上限に当たるまで詰め、残りは翌日に回す。
- トークン・アカウント ID・データベース ID は出力しない。Actions の secrets は
  `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` / `D1_DATABASE_ID`。1 つでも無ければ送信を飛ばして 0 で終わる(フォークでも動くように)。
- 手元から送るときは wrangler 経由(`--via wrangler --wrangler-bin … --wrangler-cwd …`)。場所は既定を持たない。

## 動かし方
    python3 -m unittest discover -s tests     # 実ページの切り抜きで解析を確認(通信なし)
    python3 -m collector.run                  # 1 回分(各取得元の最小間隔を守る)
    python3 -m collector.run --only phivolcs-eq --force
    python3 -m db.verify_local data               # D1 へ送る内容を手元の SQLite で検証
    python3 -m db.send data --dry-run             # 今回送る単位を見るだけ
    python3 -m db.send data                       # D1 へ送る(secrets が無ければ何もしない)
    python3 -m scripts.report_places data/advisories
    python3 -m collector.backfill_eq          # 過去分の地震(1 回だけ。済んだ月は取らない)

## データ
- `data/earthquakes/YYYY-MM.csv` — event_id で上書き(速報→確報の差し替えに追従)
- `data/dams/YYYY.csv`、`data/flood_watch/YYYY.csv`
- `data/advisories/YYYY-MM.jsonl` — 雷雨注意報・豪雨警報の本文(市町名つき)。追記のみ
- `data/outlook/YYYY-MM.jsonl` — 地域別ページの週間予報(1 地域 × 1 発表で 1 行、追記のみ)。静的な欄は既定の州 1 つぶん、州別は `provinces`
- `data/river_levels/YYYY-MM.csv` — 河川水位(10 分値)。値が動いたときと 1 時間ごとだけ残す
- `data/volcano_alert/YYYY.csv` — 火山の警戒レベル(1 日 1 行)
- `data/tcb/YYYY-MM.jsonl` — 台風公報の本文。発令中のみ。シグナルの構造化は実物が出てから書く
- `state/<key>.json` — etag、最終取得、クールダウン。Actions には永続ディスクが無いのでコミットする
