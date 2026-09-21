# PAGASA 地域別ページ(豪雨警報・雷雨注意報)— ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `pagasa-regional` |
| base_url | https://www.pagasa.dost.gov.ph/regional-forecast/{ncrprsd,nlprsd,slprsd,visprsd,minprsd} |
| 想定層 | http |
| 暫定 tier | green |
| **status** | approved(収集のみ) |
| gate_reviewed_at | 2026-09-21 |
| gate_reviewed_by | Claude(実測)/ 開発者の最終確認待ち |

## robots.txt / 規約
- robots.txt は 404。知的財産法176条(営利利用は事前承認)。

## サイト構造
- 静的 HTML。`<div id="rainfalls">` に豪雨警報、`<div id="thunderstorms">` に雷雨の Advisory / Watch / Information。
  1 件 = 内側の `<div>` 1 つ。本文に対象の州と市町名が列挙される(例: `Bulacan (Meycauayan, Marilao, and Obando)`)。
- 発令なしのときは "As of today, there is no Heavy Rainfall Warning Issued." の 1 文。
- 「Issued at」の書式が地域で少し違う(コロンの有無、曜日の有無)。どちらも解析できる。
- 2026-09-21 の実測: 9:34 発令の注意報が 10:10 の取得時点で載っていた。注意報の有効時間は 2〜3 時間。

## 判断
- 15 分間隔(最小 14 分)。1 回 5 リクエスト、間を 2 秒空ける。条件付き GET は効かない(動的ページ)。
- 市町名の PSGC への名寄せはサイト側でやる。ここでは本文をそのまま残す。
