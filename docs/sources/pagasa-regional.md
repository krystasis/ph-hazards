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

## 追記: 週間予報(Extended Weather Outlook)— 2026-09-26
- **同じページ・同じ取得から読む**(リクエストは増やさない)。`collector/pagasa_regional.py` の `parse_outlook`。
- 欄の形: 「Extended Weather Outlook」の見出しの後に `Issued at: 09:00 AM, 26 September, 2026`(月の後にカンマがある。
  空白・カンマの有無・「September 26」の順・「Sept」の略記も読む)、続いて `<div class="outlook-item">` が 5 つ
  (曜日 / `<span class="low">25&deg</span>` `<span class="high">33&deg</span>` / Wind Speed / Direction / Coastal Condition、
  空の様子は `<img title="…">`)。
- **静的な欄はその PRSD の既定の州 1 つぶんだけ**。2026-09-26 の実物では NCR = Metro Manila、NL = Ilocos Norte、
  SL = Albay、VIS = Cebu、MIN = Zamboanga City。州を選ぶとページの JS が `let regional = {...}` の州別データで欄を書き換える
  (州の outlook の先頭は 24 時間予報で、残り 5 日が欄に並ぶ)。同じ PRSD でも州で値が大きく違う
  (同じ日に Ilocos Norte 24–32°、Benguet 16–25°)。
- 残し方: `data/outlook/YYYY-MM.jsonl` に 1 地域 × 1 発表で 1 行(追記のみ、`id = <region>:<issued_at>` で重複を落とす)。
  `days` が静的な欄(D1 の `regional_outlook` に入るのはこれだけ)、`provinces` が州別データ
  (`{州のコード: {name, days: [[tmin, tmax, wind, direction, coastal], …]}}`、コードは取得元の表記のまま)。
  州別は今は D1 に送らない。州ごとの表にするかはサイト側で決める。
- 欄が無い・読めないときは記録して続ける(注意報の取得は失敗にしない)。状態の note に「週間予報 n/5」が出る。
- 2026-09-26 の実測: 5 ページとも 09:00 AM 発表、Saturday〜Wednesday の 5 日。
