"""標準ライブラリだけで足りる範囲の HTML 補助。"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v\u00a0]+")  # 行内の空白(改行は含めない)
_WS_NL = re.compile(r"[\s\u00a0]+")


def cell_text(fragment: str) -> str:
    """タグを落として空白を 1 つに畳む。"""
    return _WS_NL.sub(" ", html.unescape(_TAG.sub(" ", fragment))).strip()


def block_text(fragment: str) -> str:
    """<br> を改行として残し、段落の形を保つ。"""
    s = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    s = html.unescape(_TAG.sub(" ", s))
    lines = [_WS.sub(" ", ln).strip() for ln in s.replace("\r", "").split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


class _ById(HTMLParser):
    def __init__(self, target_id: str):
        super().__init__(convert_charrefs=False)
        self.target_id = target_id
        self.depth = 0
        self.parts: list[str] = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if self.depth:
            self.parts.append(self.get_starttag_text() or "")
            if tag not in ("br", "img", "hr", "input", "meta", "link"):
                self.depth += 1
        elif dict(attrs).get("id") == self.target_id:
            self.depth = 1

    def handle_startendtag(self, tag, attrs):
        if self.depth and not self.done:
            self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if not self.depth or self.done:
            return
        self.depth -= 1
        if self.depth == 0:
            self.done = True
        else:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.depth and not self.done:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.depth and not self.done:
            self.parts.append(f"&{name};")

    def handle_charref(self, name):
        if self.depth and not self.done:
            self.parts.append(f"&#{name};")


def inner_html_by_id(page: str, element_id: str) -> str | None:
    """id が一致する最初の要素の中身を返す。無ければ None。"""
    p = _ById(element_id)
    p.feed(page)
    return "".join(p.parts) if (p.done or p.parts) else None
