# PAGASA Pasig-Marikina-Tullahan 河川水位(FFWS)— ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `pagasa-ffws` |
| base_url | https://pasig-marikina-tullahanffws.pagasa.dost.gov.ph/water/table.do |
| 想定層 | http |
| 暫定 tier | yellow |
| **status** | approved(収集のみ)/ 開発者の最終確認待ち |
| gate_reviewed_at | 2026-09-21 |
| gate_reviewed_by | Claude(実測) |

## robots.txt(実測日: 2026-09-21)
- 404(robots.txt が無い)。

## サイト構造
- 公開ページ `water/table.do` は空の表だけを返し、読み込み時に `POST /water/table_list.do`(`ymdhm=YYYYMMDDHHmm`、10 分刻み)で中身を取る。
  応答は JSON(17 観測所、約 3KB): `obscd, obsnm, wl, wl30m, wl1h, wl2h, alertwl, alarmwl, criticalwl`。
- ログインも鍵も無く、公開ページを開いた閲覧者のブラウザが行うのと同じ 1 リクエスト。
- **yellow にした理由**: 文書化された API ではなく、ページ内部の通信であること。承認依頼(知的財産法176条)に含めて伝える。
- `wl` に付く `(*)` の意味は未確認(推定値か、欠測で前の値を持ち越しているか)。`flag` 列にそのまま残す。
- Sto Nino(マリキナ川)、Montalban、Nangka、San Mateo など。警戒(alert)・警報(alarm)・危険(critical)の基準水位つき。

## 判断
- 15 分間隔(最小 14 分)、1 回 1 リクエスト。値が動いた観測所だけ残し、動かなくても 1 時間に 1 行。
