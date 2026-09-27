"""PAGASA の台風公報。発令中だけ本文を残す。構造化は collector/tcb_parse.py。docs/sources/pagasa-tcb.md

本文の整え方(文言は変えない。ページの飾りと、コメントアウトされた HTML の残りだけを落とす):
- HTML コメント `<!-- … -->` を先に消す。以前はタグの正規表現がコメントの頭だけを食べて、
  中身(「TOS」ボタン、「Tropical Cyclone: ALERT」、有効時刻の行の重複)と「-->」が本文に残っていた。
- 台風が複数あるとページはタブ(`tab-pane`)に分かれる。1 タブ = 1 公報として別々に残す。
- 「Tropical Cyclone Bulletin Archive」(過去の PDF の一覧)から後ろは公報ではないので落とす。
  一覧は公報が変わらなくても伸びるので、残すと同じ公報が別の sha で 2 回入る。

sha は整えた本文の sha256 の先頭 16 桁(公報を 1 つに決める鍵)。
2026-09 の整える前に入った行は、`collector/tcb_clean.py` で本文だけ整え、sha は最初に入れたときの物を残した
(D1 の cyclone_bulletins と sha で突き合わせられるように)。同じ公報を取り直しても重ならないよう、
追記の前に本文そのもので既存の行と比べる(`collector/run.py`)。
"""
from __future__ import annotations

import hashlib
import re

from .htmlutil import block_text

KEY = "pagasa-tcb"
URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin"
MIN_INTERVAL_MIN = 29

_NO_ACTIVE = re.compile(r"No Active Tropical Cyclone", re.I)
_BODY = re.compile(r'<div class="[^"]*article-content[^"]*">(.*)', re.S | re.I)
_CUT = re.compile(r"We always find ways to improve|<footer", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_PANE = re.compile(r'<div[^>]*\bclass="[^"]*\btab-pane\b[^"]*"[^>]*>', re.I)
_ARCHIVE = re.compile(r"Tropical Cyclone Bulletin Archive", re.I)

# 整える前の行に残っていた、コメントの残り(tcb_clean が使う。新しい行には出ない)
_LEGACY_DROP = re.compile(r"^(TOS|-->|Previous Next)$")


def clean_text(text: str) -> str:
    """本文を整える。何度かけても同じ結果になる(新しい行にかけても何も変わらない)。

    - 過去の一覧(「Tropical Cyclone Bulletin Archive」から後ろ)を落とす
    - コメントの残りの行(「TOS」「-->」「Previous Next」、行末が「-->」の行 = コメントアウトされていた行)を空行にする
    - 空行をはさんで同じ行が続くときは 1 つにする(タブの見出しと h3 の題、有効時刻の 2 行目)
    """
    m = _ARCHIVE.search(text)
    if m:
        text = text[: m.start()]
    out: list[str] = []
    last = None  # 直前の空でない行
    for ln in text.split("\n"):
        s = ln.strip()
        if _LEGACY_DROP.match(s) or s.endswith("-->"):
            s = ""  # 消した行は空行として扱う(コメントを消した新しいページと同じ形になる)
        if s and s == last:
            while out and not out[-1]:
                out.pop()
            continue
        if s or (out and out[-1]):
            out.append(s)
        if s:
            last = s
    return "\n".join(out).strip()


def sha_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def parse_all(page: str) -> list[dict]:
    """発令中の公報を 1 タブ 1 件で返す。発令なしなら空。"""
    m = _BODY.search(page)
    body = m.group(1) if m else page
    cut = _CUT.search(body)
    if cut:
        body = body[: cut.start()]
    body = _COMMENT.sub(" ", body)
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    starts = [p.end() for p in _PANE.finditer(body)]
    panes = [body[a:b] for a, b in zip(starts, starts[1:] + [len(body)])] if starts else [body]
    out: list[dict] = []
    for pane in panes:
        text = clean_text(block_text(pane))
        if _NO_ACTIVE.search(text) or len(text) < 200:
            continue
        out.append({"sha": sha_of(text), "text": text})
    return out


def parse(page: str) -> dict | None:
    """発令なしなら None。複数あるときは最初の 1 件(収集は parse_all を使う)。"""
    items = parse_all(page)
    return items[0] if items else None
