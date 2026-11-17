"""HTML 文档模型：读取、标题大纲、文档标题。

与 `markdown_document` 同层，是**纯 Python**（不 import Qt），方便单测；
富文本渲染仍复用 `src/ui/markdown_view.MarkdownView`（QTextBrowser 对
Markdown / HTML 只是导入方式不同，阅读底色、宽度、缩放、搜索、目录全部共用）。

安全边界
--------
Qt 的 `QTextDocument` 只支持 HTML4 / CSS2 的一个子集，**不执行 JavaScript**；
实测 `<script>` / `<style>` 的内容不会进入正文（不会被当成文字显示），因此这里
不做额外的 HTML 清洗——清洗反而会把讲义里的 `<style>` 排版信息误删。
真正的安全边界在渲染层：远程资源不会主动联网下载，只有文档同目录的相对路径
图片会被 `setSearchPaths()` 解析。

标题解析
--------
目录（侧栏）需要 `<h1>`~`<h6>` 的层级、纯文字标题与源码行号。用标准库
`html.parser` 而不是正则：标题里常有 `<em>` / `<span>` / 公式图片 / 实体
（`&amp;`），正则既容易漏也容易把标签当正文。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional

from src.core.markdown_document import read_text_file

#: 阅读器接受的 HTML 后缀（大小写不敏感）
HTML_SUFFIXES = (".html", ".htm", ".xhtml")

#: 超过这个体积就不渲染：QTextDocument 对富文本的排版成本远高于纯文本。
#: 单个 HTML 讲义通常 < 2 MB；带内联 base64 图片的「单文件网页」可能很大，
#: 16 MB 足够覆盖正常阅读，又不至于让界面卡死。
MAX_HTML_BYTES = 16 * 1024 * 1024

_H_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "template"}
_WS_RE = re.compile(r"\s+")


def is_html(path: Optional[str]) -> bool:
    """路径后缀是否属于阅读器支持的 HTML 格式。"""
    if not path:
        return False
    return os.path.splitext(path)[1].lower() in HTML_SUFFIXES


def read_html(path: str) -> str:
    """把 .html / .htm / .xhtml 读成文本；编码逐个探测，最后 latin-1 兜底。"""
    return read_text_file(path, MAX_HTML_BYTES, "HTML")


@dataclass
class HtmlHeading:
    """一个标题：层级 1~6、纯文字标题、0-based 源码行号。"""

    level: int
    title: str
    line: int


def _collapse(text: str, limit: int = 300) -> str:
    """折叠空白并限长：目录条目 / 窗口标题不需要整段原文。"""
    text = _WS_RE.sub(" ", (text or "").replace("\u200b", "")).strip()
    return text[:limit]


class _HeadingParser(HTMLParser):
    """提取 `<h1>`~`<h6>` 与 `<title>`。

    * 标题里允许嵌套 `<em>` / `<span>` / `<code>`：只收文本节点；
    * `<script>` / `<style>` / `<template>` 整段跳过（它们的文本不是标题）；
    * 标签没闭合 / 层级写错时尽量保住已读到的内容，不抛异常；
    * `convert_charrefs=True` 让 `&amp;`、`&#x4e2d;` 直接变成正常文字。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._level = 0
        self._line = 0
        self._buf: List[str] = []
        self._skip = 0
        self._in_title = False
        self._title_buf: List[str] = []
        self.items: List[HtmlHeading] = []

    # -- 内部 ---------------------------------------------------------- #
    def _flush(self) -> None:
        if not self._level:
            return
        title = _collapse("".join(self._buf))
        if title:
            self.items.append(HtmlHeading(self._level, title, self._line))
        self._level = 0
        self._buf = []

    # -- HTMLParser 回调 ----------------------------------------------- #
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in _H_TAGS:
            self._flush()                     # 上一个标题没闭合：先收掉
            self._level = int(tag[1])
            self._line = max(0, self.getpos()[0] - 1)
            self._buf = []
        elif tag == "br" and self._level:
            self._buf.append(" ")

    def handle_startendtag(self, tag: str, attrs) -> None:
        """自闭合标签：`<br/>` 当换行，`<h2/>` 这种空标题直接跳过。"""
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            return
        if tag in _H_TAGS:
            self._flush()
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in _H_TAGS and self._level == int(tag[1]):
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self._title_buf.append(data)
        elif self._level:
            self._buf.append(data)

    # -- 结果 ---------------------------------------------------------- #
    @property
    def title(self) -> str:
        return _collapse("".join(self._title_buf))


def _parse(text: str) -> _HeadingParser:
    parser = _HeadingParser()
    try:
        parser.feed(text or "")
        parser.close()
    except Exception:          # pragma: no cover - HTMLParser 极少数畸形输入
        pass
    return parser


def parse_html_headings(text: str) -> List[HtmlHeading]:
    """提取 `<h1>`~`<h6>` 作为目录条目（按文档顺序）。"""
    return list(_parse(text).items)


def document_title(text: str, fallback: str) -> str:
    """优先 `<title>`，其次第一个 `<h1>`，都没有就用文件名。"""
    parser = _parse(text)
    if parser.title:
        return parser.title
    for h in parser.items:
        if h.level == 1:
            return h.title
    return fallback
