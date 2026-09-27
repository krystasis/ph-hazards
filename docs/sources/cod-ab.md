# OCHA COD-AB Philippines(市町の境界)— ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `cod-ab` |
| base_url | https://data.humdata.org/dataset/cod-ab-phl |
| 想定層 | 手作業(1 回きり。定期取得はしない) |
| 暫定 tier | green |
| **status** | **approved(1 回きりの手作業のみ)** |
| gate_reviewed_at | 2026-09-27 |
| gate_reviewed_by | Claude(実測)/ 開発者の最終確認待ち |

## ライセンス
- HDX のデータセットの license: **CC BY-IGO 3.0**(`cc-by-igo`、http://creativecommons.org/licenses/by/3.0/igo/legalcode)。
  出典の表記: "OCHA Field Information Services Section (FISS); National Mapping and Resource Information Authority (NAMRIA),
  Philippine Statistics Authority (PSA)"。
- GADM は非営利ライセンスなので使わない。
- 境界そのものは公開側に置かない(使うのは町の面積を測る分母と、NOAH の図と重ねる形だけ)。

## robots.txt / 取り方(2026-09-27 実測)
- data.humdata.org の robots.txt は `/api/` と `*.shp` `*.geojson` などを Disallow、`Crawl-Delay: 10`。
  `.gdb.zip` の resource の download は禁止されていない。
- 2026-09-27 に手で 1 回: メタデータ(CKAN の `package_show`、1 リクエスト。`/api/` は robots で Disallow なので、次からはデータセットのページで確かめる)と
  `phl_admin_boundaries.gdb.zip`(360,586,879 bytes、sha256 `e7fc18f1383a21066ecfbe595c5c1d77375c93341dedf7284f09d66dbd28c5ad`)を 1 回。
- 版: HDX の更新 2026-05-28。`phl_admin3` は 1,642 町、`version` v03、`valid_on` 2025-02-13。CRS は EPSG:4326。

## PSGC への当て方
- `adm3_pcode` は旧式の 7 桁(`PH0102801`)。PSGC の 10 桁 = 7 桁 + `000` だが、**番号が振り直された町がある**
  (Maguindanao の 2022 年の分割、HUC、Negros Island Region)。番号で当たっても名前(`places/gazetteer.py` の鍵)が違えば捨てる。
- 当たらない物は、州・市町の 5 桁が一意で名前も同じ → 州か地域の中で名前 → 全国で一意な名前、の順。手で 2 つ
  (City of Isabela、Bacungan (Leon T. Postigo))。
- 当たらない 8 区画: `Special Geographic Area - Carmen` ほか(BARMM の SGA)。2024 年に新設された 8 町(Kapalawan など)とは
  区切りが違うので当てない。この 8 町は行が無い。
- Manila の 14 区は COD-AB に無い(City of Manila の 1 区画)。
