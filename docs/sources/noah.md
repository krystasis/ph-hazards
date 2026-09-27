# UP NOAH 危険度図(洪水・土砂・高潮)— ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `noah` |
| base_url | https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps(公式 Google Drive のミラー) |
| 想定層 | 手作業(1 回きりの一括取得。定期取得はしない) |
| 暫定 tier | green |
| **status** | **approved(1 回きりの手作業のみ。Actions からは取らない)** |
| gate_reviewed_at | 2026-09-27 |
| gate_reviewed_by | Claude(実測)/ 開発者の最終確認待ち |

## ライセンス(原文で確認)
- ODbL 1.0。`NOAH_License.pdf`(ミラーの同梱物、2026-09-27 に読んだ): "The downloadable products of Project NOAH hosted in this
  server are open data licensed under the Open Data Commons Open Database License (ODC-ODbL)" / "You are free to download, copy,
  transmit, redistribute, and adapt our data provided that Project NOAH and its contributors are always properly attributed" /
  "If you alter or build upon our data, you may only distribute the result under the same license (ODC-ODbL)."
- 各層の `metadata_*.txt` の Use Constraints も同じ文。ミラーの README の frontmatter も `license: odbl`。
- 広告付きのサイトでも使える(ODbL は営利を妨げない)。派生した表(下)は ODbL で公開する。
- 出典の書き方(サイトと派生物の LICENSE に同じ文を置く):
  "Contains information from Project NOAH (UP NOAH Center) made available under the Open Database License (ODbL) 1.0."
- 知的財産法 176 条: NOAH は UP の成果物で対象になり得るが、ODbL での公開の明言を事実上の承認と読む。念のため通知する
  (連絡先は未確認。報道由来で upri.webgis@up.edu.ph)。

## robots.txt / 取り方
- huggingface.co の robots.txt は `User-agent: * / Allow: /`(2026-09-27 実測)。
- 取るのは 3 層だけ: 洪水 100 年(`Flood/100yr/`)、土砂(`Landslide/LandslideHazards/`)、高潮 SSA4(`Storm Surge/StormSurgeAdvisory4/`)。
  州ごとの zip(ESRI Shapefile、EPSG:4326)。級は 1 = low / 2 = medium / 3 = high(列名は洪水 `Var`、土砂 `LH`、高潮 `HAZ`)。
- 一覧は HF の API(`/api/datasets/.../tree/main?recursive=true`)を 1 回。本体は `resolve/main/<path>`。sha256 は LFS の oid と照合する。
- 大きさ(2026-09-27 の一覧): 洪水 100 年 4.31 GB(80 州)、土砂 12.46 GB(82 州)、高潮 SSA4 0.52 GB(68 州)、計 17.29 GB。
  置き場所はどちらのリポジトリでもない手元の `ph_hazards_data/noah/`(MANIFEST.md に一覧と sha256)。
- **定期取得はしない。** NOAH の図は 2021-10 以降ほぼ更新されない。作り直すのは NOAH か町の境界が差し替わったときだけ。
- 既知の欠け: `Flood/100yr/TawiTawi.zip` は空。Guimaras・Siquijor・Sulu は洪水 100 年のファイルが無い。高潮は沿岸の州だけ。

## 派生物(公開)
- `data/hazard_susceptibility.csv` — 市町(PSGC)× 層ごとに、町の面積のうち high / medium / low 級の割合と区分。
  ライセンスは ODbL 1.0(`data/hazard_susceptibility.LICENSE`)。ポリゴン・地図画像は再配布しない。
- 町の境界は OCHA COD-AB(`docs/sources/cod-ab.md`)。計算は非公開側の 1 回きりのスクリプト(geopandas を使うので Actions には入れない)。
- 区分(label): high = high 級が 10% 以上 / medium = それ以外で high 級 2% 以上、または high + medium 10% 以上 /
  low = それ以外でどれかの級が 0.05% 以上 / none = どの級も 0.05% 未満。州にその層のファイルが無い町は行が無い。
- 面積は Philippines 向けの Albers 正積(標準緯線 8°/18°、中心 12°N 122°E)で測る。
- **2026-09-27 時点で入っているのは Metro Manila と Camiguin だけ**(全州 17.29 GB が取得の上限 12 GB を超えたため、
  試しの 2 州で止めている。全州を落とす承認が出たら同じ手順で作り直す)。

## 使い方の決まり
- サイトは区分と面積率だけを出し、"Indicative only; not an official hazard assessment." と出典を必ず添える。
- PHIVOLCS HazardHunterPH と MGB の地質災害図は規約上転載できない / ライセンスの明示が無いので、リンクだけにする。
