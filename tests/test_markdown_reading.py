"""Markdown 阅读体验：阅读底色与缩放（含 Ctrl+滚轮）。

底色是「阅读纸张」偏好：只影响 Markdown 标签，深底自动切浅色文字 / 公式；
缩放不能再依赖 QTextEdit.zoomIn（主题 QSS 用 px 固定字号，pointSize 为 -1）。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.core.settings import AppSettings
from src.ui.markdown_view import MarkdownView
from src.ui.math_render import SOURCE_PROP

LIGHT = {"card": "#ffffff", "text": "#1f2328", "accent": "#10a37f",
         "highlight": "#d7f0e8", "hover": "#eceef0", "border": "#e5e5e5",
         "text_secondary": "#6b7280"}
DARK = {"card": "#1e2124", "text": "#e8eaed", "accent": "#2dd4a8",
        "highlight": "#15463b", "hover": "#2a2d31", "border": "#3c4043",
        "text_secondary": "#a8adb5"}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _window(tmp_path):
    from src.ui.main_window import MainWindow

    return MainWindow(settings=AppSettings(path=str(tmp_path / "s.ini")),
                      restore_session=False, restore_geometry=False)


def _formula_height(view) -> float:
    doc = view.document()
    f = doc.find("\ufffc", 0)
    return view._math.intrinsicSize(doc, f.selectionStart(), f.charFormat()).height()


def _body_size(view) -> float:
    f = view.document().defaultFont()
    return float(f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF())


# ---------------------------------------------------------------------- #
# 阅读底色
# ---------------------------------------------------------------------- #
def test_md_bg_setting_roundtrip(tmp_path):
    s = AppSettings(path=str(tmp_path / "s.ini"))
    assert s.md_bg_color() == ""
    s.set_md_bg_color("#fdf6e3")
    assert s.md_bg_color() == "#fdf6e3"
    s.set_md_bg_color("")
    assert s.md_bg_color() == ""


def test_reading_bg_adapts_text_and_formula_color(qapp):
    v = MarkdownView()
    v.apply_theme(LIGHT)
    v.set_markdown("正文 $x^2$\n", "")

    v.set_reading_bg("#1e2124")
    sheet = v.styleSheet()
    assert "#1e2124" in sheet.lower()
    assert "color: #f2eee4" in sheet
    assert v._math.fg.name() == "#f2eee4"
    assert _formula_height(v) > 0

    v.set_reading_bg("#fdf6e3")        # 浅纸色 + 浅色主题：沿用主题深字
    assert "color: #1f2328" in v.styleSheet()
    assert v._math.fg.name() == "#1f2328"

    v.set_reading_bg("")               # 跟随主题
    assert "#ffffff" in v.styleSheet().lower()


def test_reading_bg_survives_theme_switch(qapp):
    v = MarkdownView()
    v.apply_theme(LIGHT)
    v.set_markdown("正文\n", "")
    v.set_reading_bg("#fdf6e3")
    v.apply_theme(DARK)                # 深色主题 + 浅色纸：仍是深字
    assert "#fdf6e3" in v.styleSheet().lower()
    assert "color: #2b2a26" in v.styleSheet()
    v.set_reading_bg("#1e2124")        # 深色主题 + 深色纸：沿用主题浅字
    assert "color: #e8eaed" in v.styleSheet()


def test_markdown_blocks_follow_theme_colors(qapp):
    v = MarkdownView()
    v.apply_theme(LIGHT)
    tick = chr(96)
    v.set_markdown("[链接](https://example.com) " + tick + "code" + tick
                   + "\n\n> 引用\n\n" + tick * 3 + "\nprint(1)\n" + tick * 3 + "\n", "")

    def styles():
        out = {}
        block = v.document().begin()
        while block.isValid():
            bf = block.blockFormat()
            # 代码块现在允许换行（避免缩放后裁切），改用块底色识别
            code_block = bool(bf.background().style())
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                key = frag.text()
                if key in ("链接", "code", "引用", "print(1)"):
                    out[key] = (fmt.foreground().color().name()
                                if fmt.foreground().style() else None,
                                fmt.background().color().name()
                                if fmt.background().style() else None,
                                code_block)
                it += 1
            block = block.next()
        return out

    s = styles()
    assert s["链接"][0] == "#10a37f"
    assert s["引用"][0] == "#6b7280"
    assert s["code"][1] == "#eceef0"
    assert s["print(1)"][2] is True        # 围栏代码：整块底色

    v.set_reading_bg("#1e2124")            # 深色纸：链接 / 引用 / 代码同步换色
    s2 = styles()
    assert s2["链接"][0] == "#d97757"
    assert s2["引用"][0] == "#aaa396"
    assert s2["code"][1] == "#302e29"


def test_bg_button_for_markdown(qapp, tmp_path):
    w = _window(tmp_path)
    md = tmp_path / "bg.md"
    md.write_text("正文\n", encoding="utf-8")
    try:
        tab = w.open_markdown(str(md))
        assert w.btn_bg_color.isEnabled()
        assert not w.combo_bg.isEnabled()
        assert w.btn_bg_color.toolTip() == "Markdown 阅读底色"

        w._apply_bg_color("#1e2124")
        assert w.settings.md_bg_color() == "#1e2124"
        assert "#1e2124" in tab.canvas.styleSheet().lower()
        assert w.settings.note_bg_color() == "#ffffff"   # 不污染笔记纸色

        md2 = tmp_path / "bg2.md"
        md2.write_text("另一份\n", encoding="utf-8")
        tab2 = w.open_markdown(str(md2))
        assert "#1e2124" in tab2.canvas.styleSheet().lower()

        w._apply_bg_color("")          # 跟随主题
        assert w.settings.md_bg_color() == ""
        assert "#1e2124" not in tab2.canvas.styleSheet().lower()
    finally:
        w.close()


# ---------------------------------------------------------------------- #
# 缩放
# ---------------------------------------------------------------------- #
def test_zoom_scales_text_and_formula(qapp, tmp_path):
    w = _window(tmp_path)
    p = tmp_path / "z.md"
    p.write_text("# 标题\n\n正文 $x^2$ 和 $\\frac{a}{b}$\n", encoding="utf-8")
    try:
        tab = w.open_markdown(str(p))
        v = tab.canvas
        before = _body_size(v)
        h0 = _formula_height(v)

        w._run_zoom(1.2)
        assert v.scale > 1.0
        assert _body_size(v) > before
        assert _formula_height(v) > h0

        w._run_zoom(1.2)
        assert _body_size(v) > before
        w._run_zoom(1 / 1.2)
        w._run_zoom(1 / 1.2)
        assert abs(_body_size(v) - before) < 1.0
        assert abs(v.scale - 1.0) < 1e-3
    finally:
        w.close()


def test_zoom_scales_code_fonts(qapp, tmp_path):
    w = _window(tmp_path)
    tick = chr(96)
    p = tmp_path / "code.md"
    p.write_text("# 标题\n\n" + tick + "inline" + tick + "\n\n"
                 + tick * 3 + "\nprint(1)\n" + tick * 3 + "\n", encoding="utf-8")
    try:
        tab = w.open_markdown(str(p))
        v = tab.canvas

        def code_sizes():
            out = []
            block = v.document().begin()
            while block.isValid():
                it = block.begin()
                while not it.atEnd():
                    frag = it.fragment()
                    f = frag.charFormat().font()
                    if frag.text() in ("inline", "print(1)"):
                        out.append(f.pixelSize() if f.pixelSize() > 0
                                   else f.pointSizeF())
                    it += 1
                block = block.next()
            return out

        before = code_sizes()
        assert len(before) == 2
        w._run_zoom(1.5)
        after = code_sizes()
        assert all(a > b for a, b in zip(after, before))
        body = v.document().defaultFont()
        body_size = body.pixelSize() if body.pixelSize() > 0 else body.pointSizeF()
        assert all(abs(a - body_size) < 0.6 for a in after)
    finally:
        w.close()


def test_zoom_keeps_scroll_position(qapp):
    v = MarkdownView()
    v.resize(480, 320)
    v.set_markdown("\n\n".join("第 %d 段：用来撑高页面的文字。" % i
                                for i in range(120)), "")
    v.show()
    qapp.processEvents()
    sb = v.verticalScrollBar()
    sb.setValue(int(sb.maximum() * 0.5))
    qapp.processEvents()
    before = v.scroll_offset_frac()
    for _ in range(3):
        v.zoom_to(1.1)
        for _ in range(3):
            qapp.processEvents()
    after = v.scroll_offset_frac()
    v.close()
    assert abs(after - before) < 0.05


def test_swatch_follows_theme_until_custom(qapp, tmp_path):
    w = _window(tmp_path)
    md = tmp_path / "sw.md"
    md.write_text("正文\n", encoding="utf-8")
    try:
        w.open_markdown(str(md))
        assert w.theme.colors()["card"] in w.btn_bg_color.styleSheet()
        w._toggle_theme()
        assert w.theme.colors()["card"] in w.btn_bg_color.styleSheet()

        w._apply_bg_color("#fdf6e3")
        w._toggle_theme()
        assert "#fdf6e3" in w.btn_bg_color.styleSheet()
    finally:
        w.close()


def test_bg_applies_to_other_window(qapp, tmp_path):
    from src.ui.main_window import MainWindow

    w1 = MainWindow(settings=AppSettings(path=str(tmp_path / "s1.ini")),
                    restore_session=False, restore_geometry=False)
    w2 = MainWindow(settings=AppSettings(path=str(tmp_path / "s2.ini")),
                    restore_session=False, restore_geometry=False)
    md1 = tmp_path / "w1.md"
    md2 = tmp_path / "w2.md"
    md1.write_text("窗口一\n", encoding="utf-8")
    md2.write_text("窗口二\n", encoding="utf-8")
    try:
        w1.show()
        w2.show()
        qapp.processEvents()
        w1.open_markdown(str(md1))
        tab2 = w2.open_markdown(str(md2))
        w1._apply_bg_color("#1e2124")
        assert "#1e2124" in tab2.canvas.styleSheet().lower()
    finally:
        w1.close()
        w2.close()


def test_actual_size_restores_100_percent(qapp):
    v = MarkdownView()
    v.set_markdown("正文\n", "")
    v.zoom_to(1.4)
    assert v.scale > 1.0
    v.actual_size()
    assert abs(v.scale - 1.0) < 1e-6


def test_ctrl_wheel_zooms(qapp):
    v = MarkdownView()
    v.set_markdown("正文\n", "")
    ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0),
                     QPoint(0, 120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.ControlModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    v.wheelEvent(ev)
    assert v.scale > 1.0
    ev2 = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0),
                      QPoint(0, -120), Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.ControlModifier,
                      Qt.ScrollPhase.NoScrollPhase, False)
    v.wheelEvent(ev2)
    assert abs(v.scale - 1.0) < 1e-6


def test_source_mode_zoom_changes_font(qapp):
    v = MarkdownView()
    v.set_markdown("# 标题\n\n正文\n", "")
    v.set_view_mode("source")

    def frag_size() -> float:
        block = v.document().begin()
        return block.begin().fragment().charFormat().font().pointSizeF()

    before = frag_size()
    v.zoom_to(1.3)
    assert frag_size() > before


def test_copy_restores_formula_source(qapp):
    from PySide6.QtGui import QTextCursor

    v = MarkdownView()
    v.set_markdown("正文 $x^2$ 结束\n", "")
    cur = QTextCursor(v.document())
    cur.select(QTextCursor.SelectionType.Document)
    v.setTextCursor(cur)
    data = v.createMimeDataFromSelection()
    assert data is not None
    assert "$x^2$" in data.text()
    assert "\ufffc" not in data.text()


def test_zoom_keeps_formula_source(qapp):
    v = MarkdownView()
    v.set_markdown("正文 $\\alpha + \\beta$\n", "")
    v.zoom_to(1.5)
    doc = v.document()
    f = doc.find("\ufffc", 0)
    assert not f.isNull()
    assert f.charFormat().property(SOURCE_PROP) == "\\alpha + \\beta"

def test_reading_width_slider(qapp, tmp_path):
    w = _window(tmp_path)
    md = tmp_path / "width.md"
    md.write_text("正文", encoding="utf-8")
    try:
        w.resize(1200, 800)
        w.show()
        qapp.processEvents()
        tab = w.open_markdown(str(md))
        qapp.processEvents()
        v = tab.canvas
        assert w.md_width_slider.isVisible()
        assert w.settings.md_column_width() == 0
        assert w.md_width_slider.maximum() == max(520, v._max_reading_width())
        assert w.md_width_slider.value() == w.md_width_slider.maximum()
        assert w.md_width_value.text() == "铺满"

        w.md_width_slider.setValue(900)
        qapp.processEvents()
        assert w.settings.md_column_width() == 900
        assert v._column_width == 900

        w.md_width_slider.setValue(560)
        qapp.processEvents()
        assert v._column_width == 560
        assert w.settings.md_column_width() == 560

        v._start_edge_drag("right", 0)
        v._move_edge_drag(40)
        v._end_edge_drag()
        qapp.processEvents()
        assert w.settings.md_column_width() == 640
        assert w.md_width_slider.value() == 640

        w.md_width_slider.setValue(w.md_width_slider.maximum())
        qapp.processEvents()
        assert w.settings.md_column_width() == 0
        assert v._column_width == 0
        assert v._gutter == 0
        assert "24px 0" in v.styleSheet()        # 拉到最大：左右不再保留内边距

        w.resize(1400, 800)
        qapp.processEvents()
        assert w.md_width_slider.maximum() == max(520, v._max_reading_width())
        assert w.md_width_slider.value() == w.md_width_slider.maximum()
    finally:
        w.close()


def test_theme_catalog(qapp):
    from src.ui.theme import THEME_LABELS, THEMES, ThemeManager

    assert set(THEMES) >= {"light", "dark", "mist", "forest", "midnight",
                           "classic", "classic_dark"}
    assert set(THEME_LABELS) == set(THEMES)
    assert ThemeManager("mist").colors()["bg"] == "#eef2f4"
    assert ThemeManager("midnight").colors()["text"] == "#e6edf3"
    classic = ThemeManager("classic").colors()
    assert classic["bg"] == "#f7f7f8" and classic["accent"] == "#10a37f"
    assert classic["canvas_bg"] == "#e9eaee" and classic["icon"] == "#374151"
    dark = ThemeManager("classic_dark").colors()
    assert dark["bg"] == "#1e1e1e" and dark["card"] == "#2d2d2d"
    assert dark["highlight_border"] == "#2dd4a8"


def test_theme_switch_does_not_reparse(qapp, tmp_path, monkeypatch):
    w = _window(tmp_path)
    p = tmp_path / "theme.md"
    p.write_text("\n".join(["# 标题", "", "正文 $x^2$"]), encoding="utf-8")
    try:
        tab = w.open_markdown(str(p))
        v = tab.canvas
        doc = v.document()
        calls = []
        monkeypatch.setattr(v, "set_markdown", lambda *a, **k: calls.append(1))

        w._set_theme("mist")
        qapp.processEvents()
        assert calls == [], "换主题不应重新解析 Markdown"
        assert v.document() is doc
        assert not v.document().find("￼", 0).isNull()
        assert w.settings.theme() == "mist"
        assert w.theme.colors()["bg"] == "#eef2f4"
    finally:
        w._set_theme("light")
        w.close()


def test_reading_edge_mouse_drag(qapp):
    v = MarkdownView()
    v.resize(1000, 600)
    v.set_markdown(("正文" + chr(10)) * 50, "")
    v.show()
    qapp.processEvents()

    start_width = v._effective_reading_width()
    vp = v.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(2, 100))
    assert v._edge_drag == "left"
    QTest.mouseMove(vp, QPoint(102, 100), 20)
    qapp.processEvents()
    assert v._column_width == max(520, start_width - 200)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, QPoint(102, 100))
    qapp.processEvents()
    assert not v._edge_drag
    v.close()


def test_zoom_relayouts_blocks_after_tables(qapp):
    """含表格 + 代码的文档缩放后不能留下零高度块（Qt 6.11 增量重排问题）。"""
    tick = chr(96) * 3
    lines = ["# 重排测试", "", "| 列一 | 列二 |", "| --- | --- |"]
    for i in range(8):
        lines.append("| %d | 内容 %d |" % (i, i))
    lines += ["", tick + "python", "x = 1 + 2 + 3", tick, ""]
    for i in range(80):
        lines += ["## 第 %d 节" % i, "", "这一段用来撑高文档，验证后续块仍有布局。", ""]
    v = MarkdownView()
    v.resize(900, 700)
    v.set_markdown("\n".join(lines), "")
    v.show()
    qapp.processEvents()
    v.zoom_to(2.0)
    for _ in range(3):
        qapp.processEvents()
    doc = v.document()
    before = doc.size().height()
    doc.markContentsDirty(0, doc.characterCount())
    for _ in range(3):
        qapp.processEvents()
    assert abs(doc.size().height() - before) < 1.0
    v.close()


def test_zoom_minimum_keeps_text_readable(qapp):
    v = MarkdownView()
    v.set_markdown("正文用于测试最小字号。\n", "")
    v.zoom_to(0.5)
    assert v.scale >= 0.74
    body = v.document().defaultFont()
    size = body.pixelSize() if body.pixelSize() > 0 else body.pointSizeF()
    assert size >= 10
    v.close()


def test_width_change_keeps_scroll_position(qapp):
    v = MarkdownView()
    v.resize(900, 500)
    v.set_markdown("\n\n".join("第 %d 段：滚动位置测试。" % i
                              for i in range(200)), "")
    v.show()
    qapp.processEvents()
    sb = v.verticalScrollBar()
    sb.setValue(sb.maximum() // 2)
    qapp.processEvents()
    before = v.scroll_offset_frac()

    v.set_reading_width(600)
    for _ in range(4):
        qapp.processEvents()
    assert abs(v.scroll_offset_frac() - before) < 0.03
    v.close()


def test_reading_edges_resize(qapp):
    v = MarkdownView()
    v.resize(1000, 600)
    v.set_markdown(("正文" + chr(10)) * 50, "")
    v.show()
    qapp.processEvents()
    assert v._overlay.isVisible()
    assert v._overlay.geometry() == v.rect()

    # 满宽时正文左右边界就是视口左右边界
    left_full, right_full = v._edge_positions()
    assert left_full == 0
    assert right_full == v.viewport().width()

    v.set_reading_width(600)
    qapp.processEvents()
    left, right = v._edge_positions()
    assert left > left_full and right < right_full
    assert abs((right - left) - 600) <= 20       # margins + scrollbar 的取整误差

    got = []
    v.reading_width_changed.connect(got.append)
    v._start_edge_drag("right", 0)
    v._move_edge_drag(80)
    v._end_edge_drag()
    assert v._column_width == 760 and got == [760]

    v._reset_reading_width()
    assert v._column_width == 0
    assert v._edge_positions() == (0, v.viewport().width())
    v.close()
