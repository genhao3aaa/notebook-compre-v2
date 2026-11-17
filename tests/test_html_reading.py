"""HTML 阅读：渲染 / 标题目录 / 搜索 / 源码模式 / 主窗口集成。"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from src.core.settings import AppSettings
from src.ui.markdown_view import MarkdownView

HTML_DOC = """<!doctype html>
<html><head><title>示例讲义</title><style>h1{color:red}</style></head>
<body>
  <h1>第一章 <em>绪论</em></h1>
  <p>正文 alpha 与 <b>粗体</b></p>
  <h2 id="sec2">第二节</h2>
  <ul><li>条目 alpha</li></ul>
  <blockquote>引用</blockquote>
  <pre>code</pre>
  <table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
  <script>alert(1)</script>
</body></html>"""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _window(tmp_path):
    from src.ui.main_window import MainWindow

    return MainWindow(settings=AppSettings(path=str(tmp_path / "s.ini")),
                      restore_session=False, restore_geometry=False)


# ---------------------------------------------------------------------- #
# 渲染视图
# ---------------------------------------------------------------------- #
def test_html_view_render_headings_and_find(qapp):
    v = MarkdownView()
    v.set_html(HTML_DOC, "")
    assert v.document_kind() == "html"
    assert [(h.level, h.title) for h in v.headings()] == [
        (1, "第一章 绪论"), (2, "第二节")]
    plain = v.toPlainText()
    assert "alpha" in plain and "条目" in plain
    assert "alert(1)" not in plain          # 脚本不进入正文
    assert "color:red" not in plain         # 样式不进入正文
    hits = v.find_all("alpha")
    assert len(hits) == 2
    v.highlight_hits(hits, 0)
    v.focus_hit(hits[1].position)
    v.clear_search()


def test_html_view_source_mode_and_zoom(qapp):
    v = MarkdownView()
    v.apply_theme({"card": "#ffffff", "text": "#111111", "accent": "#0a7",
                   "highlight": "#dfd", "hover": "#eee", "border": "#ccc",
                   "text_secondary": "#666"})
    v.set_html(HTML_DOC, "")
    v.zoom_to(1.2)
    assert v.scale > 1.0
    v.actual_size()
    assert abs(v.scale - 1.0) < 1e-6
    v.set_view_mode("source")
    assert v.view_mode() == "source" and "<h1>" in v.toPlainText()
    v.set_view_mode("render")
    assert "第一章" in v.toPlainText()


def test_html_view_heading_layout_matches_outline(qapp):
    """目录条目必须能和渲染后的 heading 块对上（含 <br> 标题）。"""
    v = MarkdownView()
    v.set_html("<h1>第一章</h1><p>x</p>"
               "<h2>公式<br/>换行</h2><p>y</p>"
               "<h3>第三节</h3>", "")
    pairs = v._heading_layout()
    assert [i for i, _ in pairs] == [0, 1, 2]


def test_html_view_local_link_resolves_against_document_dir(qapp, tmp_path):
    from PySide6.QtCore import QUrl

    a = tmp_path / "a.html"
    a.write_text("<h1>A</h1>", encoding="utf-8")
    b = tmp_path / "b.html"
    b.write_text("<h1>B</h1>", encoding="utf-8")

    v = MarkdownView()
    v.set_html('<p><a href="b.html">B</a></p>', str(a))
    got = []
    v.open_local_document_requested.connect(got.append)
    v._on_anchor(QUrl("b.html"))
    assert got == [str(b)]


# ---------------------------------------------------------------------- #
# 主窗口集成
# ---------------------------------------------------------------------- #
def test_open_html_tab(qapp, tmp_path):
    w = _window(tmp_path)
    p = tmp_path / "doc.html"
    p.write_text(HTML_DOC, encoding="utf-8")
    try:
        tab = w.open_html(str(p))
        assert tab is not None and tab.kind == "html" and w.mode == "html"
        assert tab.text_source.startswith("<!doctype")
        assert [(h.level, h.title) for h in tab.text_headings] == [
            (1, "第一章 绪论"), (2, "第二节")]
        assert w.side_title.text() == "HTML 阅读"
        assert w.btn_bg_color.toolTip() == "HTML 阅读底色"
        assert w.outline_panel.count_label.text() == "共 2 个标题"
        # 同一份文件重复打开复用已有标签
        assert w.open_html(str(p)) is tab
        assert str(p) in w.settings.recent_files()
    finally:
        w.close()


def test_open_path_dispatches_html(qapp, tmp_path):
    w = _window(tmp_path)
    p = tmp_path / "a.htm"
    p.write_text("<h1>A</h1>", encoding="utf-8")
    try:
        tab = w.open_path(str(p))
        assert tab is not None and tab.kind == "html"
    finally:
        w.close()


def test_html_recent_kind_and_icon(qapp, tmp_path):
    w = _window(tmp_path)
    p = tmp_path / "r.html"
    p.write_text("<h1>R</h1>", encoding="utf-8")
    try:
        assert w._recent_kind(str(p)) == "html"
        assert not w._recent_icon(str(p)).isNull()
    finally:
        w.close()


def test_html_lazy_materialize(qapp, tmp_path):
    w = _window(tmp_path)
    p = tmp_path / "lazy.html"
    p.write_text(HTML_DOC, encoding="utf-8")
    try:
        tab = w.open_html(str(p), activate=False, lazy=True)
        assert tab.text_pending is True
        assert tab.text_source, "文本仍应读入（只是不排版）"
        assert "第一章" not in tab.canvas.toPlainText()
        w._materialize_text(tab)
        assert tab.text_pending is False
        assert "第一章" in tab.canvas.toPlainText()
        assert tab.text_headings
    finally:
        w.close()
