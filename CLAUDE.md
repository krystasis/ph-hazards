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

## 動かし方
    python3 -m unittest discover -s tests     # 実ページの切り抜きで解析を確認(通信なし)
    python3 -m collector.run                  # 1 回分(各取得元の最小間隔を守る)
    python3 -m collector.run --only phivolcs-eq --force
    python3 -m collector.backfill_eq          # 過去分の地震(1 回だけ。済んだ月は取らない)

## データ
- `data/earthquakes/YYYY-MM.csv` — event_id で上書き(速報→確報の差し替えに追従)
- `data/dams/YYYY.csv`、`data/flood_watch/YYYY.csv`
- `data/advisories/YYYY-MM.jsonl` — 雷雨注意報・豪雨警報の本文(市町名つき)。追記のみ
- `data/river_levels/YYYY-MM.csv` — 河川水位(10 分値)。値が動いたときと 1 時間ごとだけ残す
- `data/volcano_alert/YYYY.csv` — 火山の警戒レベル(1 日 1 行)
- `data/tcb/YYYY-MM.jsonl` — 台風公報の本文。発令中のみ。シグナルの構造化は実物が出てから書く
- `state/<key>.json` — etag、最終取得、クールダウン。Actions には永続ディスクが無いのでコミットする
