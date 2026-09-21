# PHIVOLCS 火山警戒レベル — ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `phivolcs-volcano` |
| base_url | https://wovodat.phivolcs.dost.gov.ph/bulletin/list-of-bulletin |
| 想定層 | http |
| 暫定 tier | green |
| **status** | approved(収集のみ) |
| gate_reviewed_at | 2026-09-21 |
| gate_reviewed_by | Claude(実測)/ 開発者の最終確認待ち |

## robots.txt / 規約
- robots.txt は未確認(次の見直しで実測する)。知的財産法176条(営利利用は事前承認)。

## サイト構造
- 静的 HTML(約 31KB)。ページ上部の帯に監視中の火山と警戒レベルが常時出る。
  `<span class="tvo-scroll-level scroll-item">Taal - 1</span>` の形。2026-09-21 は Taal 1 / Kanlaon 2 / Bulusan 1 / Pinatubo 0 / Mayon 2。
- 中間証明書は earthquake.phivolcs と同じ(同梱の物で検証が通る)。
- 同じページに火山ごとの公報の一覧がある(未取得。本文を残すかは後で決める)。

## 判断
- 1 時間間隔(最小 59 分)。1 日 1 行(その日の最後に見た値)。レベルが変わった日が履歴として残る。
