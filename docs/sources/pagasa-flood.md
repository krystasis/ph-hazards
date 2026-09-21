# PAGASA 洪水情報(ダム水位・流域の監視状況)— ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `pagasa-flood` |
| base_url | https://www.pagasa.dost.gov.ph/flood |
| 想定層 | http |
| 暫定 tier | green |
| **status** | approved(収集のみ) |
| gate_reviewed_at | 2026-09-21 |
| gate_reviewed_by | Claude(実測)/ 開発者の最終確認待ち |

## robots.txt(実測日: 2026-09-21)
- pagasa.dost.gov.ph は 404(robots.txt が無い)。

## 利用規約(ToS)
- 知的財産法176条(営利利用は事前承認)。過去の気候観測値は別途 CADS-07 の利用条件書がある(今回の対象外)。

## サイト構造
- 静的 HTML。9 ダム × 4 行(rowspan)。`<td data-id="ダム名">` を順に並べると、今日 14 セル + 前日 10 セル。
  値は 1 日 1 回(朝 8 時)。門の開度・流入・流出は空のことが多い。
- 同じページに流域(4 つ)の Flood Watch / Non-Flood Watch の表がある。
- ページ内の General Flood Advisory は panahon.gov.ph の iframe(未取得)。

## 判断
- 値が 1 日 1 回なので 3 時間間隔(最小 170 分)。
