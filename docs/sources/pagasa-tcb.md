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
- 発令中は台風ごとのタブ(`tab-pane`)。1 タブ = 1 公報。2026-09-24〜27 の Typhoon "Queenie"(14 公報)で実物を見た。
  中身は題(「Typhoon "Queenie"」)→ 発表時刻「Issued at 11:00 am, 27 September 2026」→「(Valid for broadcast until the next advisory
  to be issued at 5:00 PM today)」→ 全部大文字の見出し → HAZARDS AFFECTING LAND AREAS / COASTAL WATERS / TRACK AND INTENSITY OUTLOOK
  → 「Location of Eye/center」「Movement」「Strength」「Forecast Position」「Wind Signal」の欄 → 定型の注意文 → 過去の PDF の一覧。
- ページには HTML コメントでふさいだ部分がある(「TOS」ボタン、「Tropical Cyclone: ALERT」、有効時刻の行の 2 つ目、ページ送り)。
  参考: コミュニティ製の解析器(github.com/edwardguevarra/bagyo-api は PSGC コード付き JSON)。

## 残し方(`collector/pagasa_tcb.py`、`data/tcb/YYYY-MM.jsonl`)
- 本文は **文言を変えずに** 整えて残す: HTML コメントを消してから文字にする。過去の PDF の一覧から後ろは落とす
  (公報が同じでも一覧だけ伸びるので、残すと同じ公報が 2 行になる)。
- `sha` = 整えた本文の sha256 の先頭 16 桁。**2026-09-27 より前に入った行(Queenie の分)は、`collector/tcb_clean.py` で
  本文だけ整え、sha は最初に入れたときの物のまま**(D1 の `cyclone_bulletins` と sha で突き合わせられるように)。
  整えた本文が同じ行は最初の 1 行だけ残した(18 行 → 14 行。4 行は過去の PDF の一覧が伸びただけの重複)。
  取り直した公報が古い sha の行と重ならないよう、収集は追記の前に本文そのものでも比べる。
- D1 の `cyclone_bulletins` は追記だけの表なので、整える前の本文と重複 4 行が残っている(sha は jsonl と同じ)。

## 構造化(`collector/tcb_parse.py` → D1 の `cyclone_advisories` / `cyclone_signals`、`db/export.py`)
- 公報 1 つにつき `cyclone_advisories` 1 行: name / category / issued_at / next_advisory_at(「today / tomorrow」は発表日から)/
  headline / par_status / 中心の緯度経度 / movement / 最大風速・最大瞬間風速(km/h)/ 陸・沿岸の本文 / 予報位置(JSON)。
  本文に無い値は NULL(作らない)。本文が同じ公報は先に取れた行の sha を使う。
- `par_status`(上から順に最初に当たった物):
  1. 中心の位置の文に「(OUTSIDE PAR)」、または見出しに「EXITED / HAS LEFT」→ 見出しか進路の見通しに「expected / forecast / likely /
     about to enter」があれば `entering`、無ければ `outside`
  2. 見出しに「ABOUT TO EXIT / EXITING / ABOUT TO LEAVE / LEAVING」→ `exiting`
  3. 中心の位置の文がある → `inside`(PAGASA は領域の外の位置に必ず「(OUTSIDE PAR)」を付ける)
  4. それ以外 → `unknown`
- 予報位置の `outside_par` は、その行に「(OUTSIDE PAR)」があるかどうか。
- Queenie の実物で取れた物: 14 公報すべてで name / category / issued_at / next_advisory_at / 見出し / 中心 / 動き / 風速 / 予報位置。
  2026-09-24 23:00 の公報は経度が「132. °E」と書かれている(132.0 として読む)。2026-09-26 11:00 の公報は陸の欄に沿岸の文が
  そのまま入っている(PAGASA 側の書き間違い。直さずに残す)。

### シグナル(`cyclone_signals`)— **実物では未確認**
Queenie は全公報が「No Tropical Cyclone Wind Signal」だったので、シグナルの出た実物をまだ見ていない。
読み方は PAGASA が公表している TCB の書式から作り、手で作った欄(`tests/fixtures/pagasa_tcb_signals_SYNTHETIC.txt`)でだけ確かめた。
**シグナルの出た最初の公報で、必ず実物と突き合わせる**(ページの表の組み方によっては文字の並びが想定と違う)。
- 見張り: 新しく足した公報でシグナルの行が 1 つでも読めたら、収集の出力に「[pagasa-tcb] ★ シグナル N 行を解析…」が出る。**初めての回だけ**その実行が 0 以外で終わり(Actions が赤くなる)、`state/pagasa-tcb.json` の `signals_seen_first` に時刻が残る(以後は緑。`collector/run.py` の `signal_watch`)。
- 「TCWS No. N」「Wind Signal No. N」「Signal No. N」の後に、その段階の地域が並ぶと想定。「Luzon / Visayas / Mindanao」の見出しは読み飛ばし、
  「Wind threat / Warning lead time / Range of wind speeds / Potential impacts」から後ろは場所として読まない。
- 地域は括弧の外のコンマと「and」で区切る(「the northern and central portions of」の and は区切らない)。
  - 州名 → `province`(Metro Manila は province_code に地域コード 1300000000。province_outlook と同じ)
  - 「the northern portion of X (Town1, Town2)」→ X の `portion` の行 + 括弧の中の町ごとに `city` の行(X の中で市町コードを当てる)
  - 「the rest of X」→ X の `portion` の行。意味は「X のうち、より高い段階に名前が出ていない町すべて」
  - 「Babuyan Islands」「Polillo Islands」などの島々 → 属する州の `portion`(`ISLAND_GROUPS` に手で持つ)
  - 州でない名前 → 全国で一意な市町なら `city`。当たらなければ `portion` でコードは空
- 市町ページでの段階 = その公報の「city_code が一致する行」「province_code が一致する `province` の行」
  「province_code が一致し area が "the rest of" で始まる `portion` の行」の signal の最大。
  それ以外の `portion` の行(括弧の無い「the southern portion of X」など)は「州の一部に発令」としてだけ出せる。

## 判断
- 30 分間隔(最小 29 分)。公報の発表は 3〜6 時間ごと。
