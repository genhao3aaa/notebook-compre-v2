"""目录同步回归：PDF 当前章节、Markdown 当前标题、目录内公式排版。

这几条都是「界面看起来没反应」类问题，必须锁住：
* PDF 书签只标章节首页，当前页落在两章之间时不能没有高亮；
* Markdown 滚动 / 目录跳转后，左侧高亮必须跟着走；
* 标题里的 $...$ 不能在目录里显示成源码，也不能被 Markdown 清洗删掉 _。
"""
from __future__ import annotations

import os

import pymupdf as fitz
import pytest
from PySide6.QtWidgets import QApplication

from src.core.markdown_document import parse_headings, plain_math_title
from src.core.settings import AppSettings
from src.render.pdf_engine import OutlineEntry
from src.ui.main_window import MainWindow
from src.ui.outline_panel import MATH_TITLE_ROLE, OutlinePanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _window(tmp_path):
    return MainWindow(settings=AppSettings(path=str(tmp_path / "s.ini")),
                      restore_session=False, restore_geometry=False)


def _panel():
    panel = OutlinePanel()
    panel.resize(240, 420)
    panel.show()
    return panel


def _label(panel) -> str:
    item = panel.current_item()
    return item.text(0) if item is not None else ""


# ---------------------------------------------------------------------- #
# 纯逻辑：标题里的公式不能被 Markdown 清洗破坏
# ---------------------------------------------------------------------- #
def test_heading_keeps_formula_source():
    h = parse_headings("## 1.2 变色原理：$pK_{\\mathrm{a}} \\pm 1$ 怎么来的\n")[0]
    assert "$pK_{\\mathrm{a}} \\pm 1$" in h.title
    assert "pKₐ ± 1" in plain_math_title(h.title)
    assert "$" not in plain_math_title(h.title)


# ---------------------------------------------------------------------- #
# PDF：最近章节高亮
# ---------------------------------------------------------------------- #
def test_pdf_outline_highlights_section_between_bookmarks(qapp):
    panel = _panel()
    try:
        panel.set_outline([
            OutlineEntry(1, "第一章", 2),
            OutlineEntry(2, "1.1 节", 5),
            OutlineEntry(1, "第二章", 10),
        ])
        panel.set_current_page(0)
        assert _label(panel) == "", "第一个书签之前不应用上一节冒充当前章节"
        panel.set_current_page(2)
        assert _label(panel) == "第一章"
        panel.set_current_page(7)
        assert _label(panel) == "1.1 节", "两章之间必须回退到最近一个起始页"
        panel.set_current_page(9)
        assert _label(panel) == "1.1 节"
        panel.set_current_page(10)
        assert _label(panel) == "第二章"
        panel.set_current_page(40)
        assert _label(panel) == "第二章"
    finally:
        panel.close()


def test_pdf_outline_same_page_prefers_deeper_entry(qapp):
    panel = _panel()
    try:
        panel.set_outline([
            OutlineEntry(1, "第三章", 5),
            OutlineEntry(2, "3.1 节", 5),
            OutlineEntry(2, "3.2 节", 8),
        ])
        panel.set_current_page(5)
        assert _label(panel) == "3.1 节", "同一页有父子书签时取更具体的子节"
        # 用户点的就是「第三章」时，跳转后要保住点中的这一条
        panel._on_clicked(panel._items[0])
        panel.highlight_item(panel._items[0])
        assert _label(panel) == "第三章"
    finally:
        panel.close()


def test_pdf_outline_follows_continuous_scroll(qapp, tmp_path):
    """真实 PDF：翻页 / 连续滚动都更新高亮（不再要求页码完全相等）。"""
    pdf = tmp_path / "toc.pdf"
    d = fitz.open()
    for i in range(12):
        d.new_page().insert_text((72, 100), f"page {i + 1}")
    d.set_toc([[1, "第一章", 1], [2, "1.1 节", 3], [1, "第二章", 8]])
    d.save(str(pdf))
    d.close()
    w = _window(tmp_path)
    try:
        w.show()
        qapp.processEvents()
        tab = w.open_pdf(str(pdf))
        qapp.processEvents()
        w.goto_page(4)               # 1.1 节（第 3 页）与第二章（第 8 页）之间
        qapp.processEvents()
        assert w.outline_panel.current_item().text(0) == "1.1 节"
        w._set_read_mode("continuous")
        tab.canvas.set_scroll_fraction(True, 0.95)
        qapp.processEvents()
        qapp.processEvents()
        assert w.outline_panel.current_item().text(0) == "第二章"
    finally:
        w.close()


# ---------------------------------------------------------------------- #
# Markdown：滚动 / 跳转 → 目录高亮
# ---------------------------------------------------------------------- #
def _write_md(path):
    body = []
    for i in range(6):
        body.append(f"## 第 {i} 节\n")
        body.append(("这是一段用来撑开滚动距离的正文。" * 6 + "\n\n") * 3)
    path.write_text("# 总标题\n\n" + "".join(body), encoding="utf-8")


def test_markdown_outline_follows_scroll(qapp, tmp_path):
    md = tmp_path / "toc.md"
    _write_md(md)
    w = _window(tmp_path)
    try:
        w.show()
        qapp.processEvents()
        tab = w.open_markdown(str(md))
        qapp.processEvents()
        view = tab.canvas
        positions = view._heading_block_positions()
        doc = view.document()
        y = doc.documentLayout().blockBoundingRect(
            doc.findBlock(positions[4])).top()
        view.verticalScrollBar().setValue(int(y) + 8)
        qapp.processEvents()
        qapp.processEvents()
        assert view.current_heading_index() == 4
        # 目录第 0 项是文档标题，所以第 4 个标题对应「第 3 节」
        assert w.outline_panel.current_item().text(0) == \
            w.outline_panel._items[4].text(0)
        assert w.outline_panel.current_item().text(0).startswith("第 3 节")
    finally:
        w.close()


def test_markdown_outline_jump_highlights_item(qapp, tmp_path):
    md = tmp_path / "jump.md"
    _write_md(md)
    w = _window(tmp_path)
    try:
        w.show()
        qapp.processEvents()
        tab = w.open_markdown(str(md))
        qapp.processEvents()
        w._on_outline_jump(0, 3.0)
        qapp.processEvents()
        assert tab.canvas.current_heading_index() == 3
        assert w.outline_panel.current_item().text(0) == \
            w.outline_panel._items[3].text(0)
        assert w.outline_panel.current_item().text(0).startswith("第 2 节")
    finally:
        w.close()


def test_markdown_outline_renders_formula(qapp, tmp_path):
    md = tmp_path / "math.md"
    md.write_text(
        "# 公式 $pK_{\\mathrm{a}} \\pm 1$ 标题\n\n正文\n\n"
        "## 第二 $10^{14}$\n\n正文\n", encoding="utf-8")
    w = _window(tmp_path)
    try:
        w.show()
        qapp.processEvents()
        w.open_markdown(str(md))
        qapp.processEvents()
        items = w.outline_panel._items
        assert items[0].text(0) == "公式 pKₐ ± 1 标题"
        assert "$" not in items[0].text(0)
        assert items[0].data(0, MATH_TITLE_ROLE) == "公式 $pK_{\\mathrm{a}} \\pm 1$ 标题"
        assert items[1].text(0) == "第二 10¹⁴"
    finally:
        w.close()


def test_markdown_outline_ignores_quote_headings(qapp, tmp_path):
    """Qt 会把 `> # 标题` 也渲染成 heading 块，目录不能因此整体错位。"""
    md = tmp_path / "quote.md"
    md.write_text(
        "> # 引用伪标题\n>\n> 一段引用正文。\n\n"
        "# 正常一\n\n正文一\n\n## 正常二\n\n正文二\n", encoding="utf-8")
    w = _window(tmp_path)
    try:
        w.show()
        qapp.processEvents()
        tab = w.open_markdown(str(md))
        qapp.processEvents()
        view = tab.canvas
        assert len(w.outline_panel._items) == 2
        assert [i for i, _pos in view._heading_layout()] == [0, 1]
        w._on_outline_jump(0, 1.0)
        qapp.processEvents()
        assert view.textCursor().block().text() == "正常二"
    finally:
        w.close()
