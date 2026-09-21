# panahon.gov.ph 暑さ指数 — ソース確認ゲート

| 項目 | 値 |
|---|---|
| key | `panahon-heat` |
| base_url | https://www.panahon.gov.ph/heat_index.html |
| 想定層 | http |
| 暫定 tier | yellow |
| **status** | **hold(取らない)** |
| gate_reviewed_at | 2026-09-21 |
| gate_reviewed_by | Claude(実測) |

## robots.txt(実測日: 2026-09-21)
- `User-agent: * / Disallow:`(全面許可)。

## サイト構造
- 観測所別の 1 時間値(observed_at / heat_index / temperature / humidity)が JSON でページに埋め込まれている。
- ただしページの JavaScript が難読化されている。取り出されることを想定していない可能性がある。

## 判断
- PAGASA への承認依頼(知的財産法176条)に暑さ指数を含め、返事が来るまで取得しない。
