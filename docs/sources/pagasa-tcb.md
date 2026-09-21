# PAGASA 台風公報 — ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `pagasa-tcb` |
| base_url | https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin |
| 想定層 | http |
| 暫定 tier | green |
| **status** | approved(収集のみ) |
| gate_reviewed_at | 2026-09-21 |
| gate_reviewed_by | Claude(実測)/ 開発者の最終確認待ち |

## サイト構造
- 静的 HTML。発令なしのときは "No Active Tropical Cyclone within the Philippine Area of Responsibility"。
- **発令中のページはまだ見ていない。** 本文を丸ごと残し、シグナル(州・市町別)の構造化は実物が出てから書く。
  参考: コミュニティ製の解析器(github.com/edwardguevarra/bagyo-api は PSGC コード付き JSON)。

## 判断
- 30 分間隔(最小 29 分)。公報の発表は 3〜6 時間ごと。
