"""HTML 文档模型：后缀 / 编码 / 标题大纲 / <title>。"""
from __future__ import annotations

import pytest

from src.core.html_document import (HTML_SUFFIXES, document_title, is_html,
                                    parse_html_headings, read_html)


def test_is_html_suffixes():
    for suffix in HTML_SUFFIXES:
        assert is_html("doc" + suffix)
        assert is_html("DOC" + suffix.upper())
    assert not is_html("doc.md")
    assert not is_html("doc.pdf")
    assert not is_html("doc.note")
    assert not is_html("")


def test_read_html_encodings(tmp_path):
    p = tmp_path / "u.html"
    p.write_text("<h1>中文</h1>", encoding="utf-8")
    assert "中文" in read_html(str(p))

    bom = tmp_path / "b.html"
    bom.write_bytes(b"\xef\xbb\xbf<h1>BOM</h1>")
    assert read_html(str(bom)) == "<h1>BOM</h1>"

    gbk = tmp_path / "g.html"
    gbk.write_bytes("<h1>GBK 中文</h1>".encode("gbk"))
    assert "GBK" in read_html(str(gbk))


def test_read_html_size_guard(tmp_path, monkeypatch):
    import src.core.html_document as h

    monkeypatch.setattr(h, "MAX_HTML_BYTES", 8)
    p = tmp_path / "big.html"
    p.write_text("<h1>很长的内容</h1>", encoding="utf-8")
    with pytest.raises(ValueError):
        read_html(str(p))


def test_parse_html_headings_levels_nested_and_entities():
    text = """<h1>第一章 <em>绪论</em></h1>
    <h2>1.2 变色原理 &amp; pK<sub>a</sub></h2>
    <h3>公式<br/>换行</h3>
    <h4>未闭合
    <h2>第二章</h2>"""
    got = [(h.level, h.title) for h in parse_html_headings(text)]
    assert got == [(1, "第一章 绪论"), (2, "1.2 变色原理 & pKa"),
                   (3, "公式 换行"), (4, "未闭合"), (2, "第二章")]


def test_parse_html_headings_skips_script_style_template():
    text = """<style>h1{color:red}</style>
    <script>var x = '<h1>假标题</h1>';</script>
    <template><h2>模板</h2></template>
    <h1>真标题</h1>"""
    assert [(h.level, h.title) for h in parse_html_headings(text)] == [(1, "真标题")]


def test_parse_html_headings_ignores_non_heading_tags():
    text = "<p>正文</p><div><span>不是标题</span></div>"
    assert parse_html_headings(text) == []


def test_document_title_prefers_title_then_h1():
    assert document_title(
        "<title>课程 &amp; 讲义</title><h1>正文标题</h1>", "x.html") == "课程 & 讲义"
    assert document_title("<h1>只有一级标题</h1>", "x.html") == "只有一级标题"
    assert document_title("<p>无标题</p>", "x.html") == "x.html"
