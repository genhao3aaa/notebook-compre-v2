"""Markdown 公式：扫描 / 解析 / 视图集成，以及背景功能对 Markdown 的适用性。

公式渲染不引入新依赖：解析在 src/core/math_formula.py，排版绘制在
src/ui/math_render.py（QTextDocument 自定义内联对象）。
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from src.core.math_formula import (Boxed, Frac, Matrix, Script, Sqrt, Sym,
                                   mask_math, math_to_plain, parse_math)
from src.core.settings import AppSettings
from src.ui.markdown_view import MarkdownView
from src.ui.math_render import (MATH_OBJECT_TYPE, SOURCE_PROP, math_box,
                                paint_math_box)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _window(tmp_path):
    from src.ui.main_window import MainWindow

    return MainWindow(settings=AppSettings(path=str(tmp_path / "s.ini")),
                      restore_session=False, restore_geometry=False)


def _formula_objects(view):
    """返回 [(文档位置, 公式字符格式)]，跳过普通文本。"""
    doc = view.document()
    out = []
    pos = 0
    while True:
        found = doc.find("\ufffc", pos)
        if found.isNull():
            break
        out.append((found.selectionStart(), found.charFormat()))
        pos = found.selectionStart() + 1
    return out


# ---------------------------------------------------------------------- #
# 扫描：哪些美元符号算公式
# ---------------------------------------------------------------------- #
def test_mask_math_inline_and_display():
    text = "公式 $E=mc^2$ 与\n\n$$\\frac{a}{b}$$\n"
    masked, segs = mask_math(text)
    assert [s.source for s in segs] == ["E=mc^2", "\\frac{a}{b}"]
    assert [s.display for s in segs] == [False, True]
    assert "$" not in masked.replace("\ue000", "").replace("\ue001", "")
    for seg in segs:
        assert seg.token in masked
        assert text[seg.start:seg.end].startswith("$")


def test_mask_math_skips_code_and_escaped():
    fence = chr(96) * 3
    tick = chr(96)
    text = (fence + "\n$x$\n" + fence + "\n\n"
            "行内 " + tick + "$y$" + tick + " 不算；价格 \\$100 不算。\n")
    masked, segs = mask_math(text)
    assert segs == []
    assert masked == text


def test_mask_math_paren_delimiters():
    text = "行内 \\(a+b\\) 与行间 \\[c+d\\]\n"
    _, segs = mask_math(text)
    assert [(s.source, s.display) for s in segs] == [("a+b", False),
                                                    ("c+d", True)]


def test_mask_math_requires_content():
    assert mask_math("单个 $ 符号\n")[1] == []
    assert mask_math("空公式 $$  $$ 忽略\n")[1] == []


# ---------------------------------------------------------------------- #
# 解析：LaTeX 子集
# ---------------------------------------------------------------------- #
def test_parse_math_structures():
    node = parse_math("\\frac{a}{b}").items[0]
    assert isinstance(node, Frac)
    node = parse_math("x_1^2").items[0]
    assert isinstance(node, Script) and node.sub and node.sup
    node = parse_math("\\sqrt[3]{x+1}").items[0]
    assert isinstance(node, Sqrt) and node.index is not None
    node = parse_math("\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}").items[0]
    assert isinstance(node, Matrix)
    assert len(node.rows) == 2 and len(node.rows[0]) == 2


def test_parse_math_greek_and_unknown():
    assert parse_math("\\alpha").items[0] == Sym("α", "math", "ord")
    # 未知命令不抛异常，按正体文字显示
    assert parse_math("\\notacommand").items[0].text == "notacommand"


def test_function_names_are_atoms():
    from src.core.math_formula import Func

    node = parse_math(r"\log_2 x").items[0]
    assert isinstance(node, Script) and isinstance(node.base, Func)
    assert node.base.text == "log"
    node = parse_math(r"\sin^2 x").items[0]
    assert isinstance(node, Script) and isinstance(node.base, Func)
    assert isinstance(parse_math(r"\operatorname{softmax}").items[0], Func)


def test_binom_has_no_fraction_bar():
    from src.core.math_formula import Delim

    node = parse_math(r"\binom{n}{k}").items[0]
    assert isinstance(node, Delim)
    frac = node.body.items[0]
    assert isinstance(frac, Frac) and frac.bar is False


def test_text_keeps_edge_spaces():
    sym = parse_math(r"\text{if }").items[0].items[0]
    assert sym.style == "text" and sym.text == "if "


def test_cjk_is_upright_in_math(qapp):
    from PySide6.QtGui import QFont

    from src.ui.math_render import _Ctx, _layout

    ctx = _Ctx(QFont("Microsoft YaHei UI"), 12, False)
    cjk = _layout(parse_math("速"), ctx, 12)
    latin = _layout(parse_math("v"), ctx, 12)
    assert not cjk.parts[0][0].font.italic()
    assert latin.parts[0][0].font.italic()


def test_common_relation_and_arrow_commands():
    """讲义的化学式大量用到 ⇌ / ⟹ / ≫，不能退化成命令名文字。"""
    cases = {
        r"\rightleftharpoons": "⇌",
        r"\leftrightharpoons": "⇋",
        r"\Longrightarrow": "⟹",
        r"\longrightarrow": "⟶",
        r"\Longleftrightarrow": "⟺",
        r"\gg": "≫",
        r"\ll": "≪",
        r"\because": "∵",
        r"\therefore": "∴",
    }
    for source, glyph in cases.items():
        node = parse_math(source).items[0]
        assert isinstance(node, Sym) and node.text == glyph
        assert node.cls == "rel"


def test_formula_br_starts_a_new_row(qapp):
    from PySide6.QtGui import QFont

    from src.core.math_formula import LineBreak
    from src.ui.math_render import _Ctx, _layout

    br = "a<" + chr(92) + "mathrm{br}>b"
    node = parse_math(br)
    assert any(isinstance(item, LineBreak) for item in node.items)
    ctx = _Ctx(QFont("Microsoft YaHei UI"), 15, True)
    box = _layout(node, ctx, 15)
    assert getattr(box, "rows", None) and len(box.rows) == 2
    assert box.desc > box.asc


def test_parse_math_is_total():
    for src in ("{", "\\frac{", "}{", "\\\\", "\\left(", "x^", "&&"):
        parse_math(src)     # 不抛异常即可


# ---------------------------------------------------------------------- #
# 视图：占位符 → 内联对象
# ---------------------------------------------------------------------- #
def test_actual_textbook_commands_render_as_symbols(qapp):
    """回归：真实讲义的化学平衡箭头不能变成 20 多个字母的长串。"""
    nl = chr(10)
    text = (r"化学反应 $2\mathrm{H}_{2}\mathrm{O} \rightleftharpoons "
            r"\mathrm{H}_{3}\mathrm{O}^{+} + \mathrm{OH}^{-}$。" + nl + nl
            + r"$$\Delta G^{\circ} = -RT\ \ln K^{\circ}"
              r"\quad \Longrightarrow \quad K^{\circ} = "
              r"\exp(-\Delta G^{\circ}/RT)$$" + nl + nl
            + r"当 $K_{\mathrm{a}}C \gg 20K_{\mathrm{w}}$ 时，水可忽略。")
    v = MarkdownView()
    v.set_markdown(text, "")
    plain = v.toPlainText()
    for command in ("rightleftharpoons", "Longrightarrow", "gg"):
        assert command not in plain
    assert "⇌" not in plain          # 公式是对象，不是纯文字
    assert len(_formula_objects(v)) == 3


def test_bold_repair_keeps_formula_object(qapp):
    """中文粗体修补不能吃掉中间的公式占位符。"""
    v = MarkdownView()
    v.set_markdown(r"**（1）$K^{\circ}$ 是无量纲的。**因为活度。", "")
    assert "**" not in v.toPlainText()
    objs = _formula_objects(v)
    assert len(objs) == 1
    assert objs[0][1].property(SOURCE_PROP) == r"K^{\circ}"


def test_view_embeds_formula_objects(qapp):
    v = MarkdownView()
    v.set_markdown("正文 $E=mc^2$ 和 $\\frac{a}{b}$。\n", "")
    text = v.toPlainText()
    assert "$" not in text
    objects = _formula_objects(v)
    assert len(objects) == 2
    assert all(cf.objectType() == MATH_OBJECT_TYPE for _, cf in objects)
    assert [cf.property(SOURCE_PROP) for _, cf in objects] == ["E=mc^2",
                                                               "\\frac{a}{b}"]


def test_view_code_block_keeps_dollar(qapp):
    fence = chr(96) * 3
    v = MarkdownView()
    v.set_markdown(fence + "\n$x$\n" + fence + "\n", "")
    assert "$x$" in v.toPlainText()
    assert _formula_objects(v) == []


def test_source_mode_keeps_raw_formula(qapp):
    v = MarkdownView()
    v.set_markdown("正文 $E=mc^2$\n", "")
    v.set_view_mode("source")
    assert "$E=mc^2$" in v.toPlainText()
    assert _formula_objects(v) == []
    v.set_view_mode("render")
    assert len(_formula_objects(v)) == 1


def test_long_display_formula_fits_view(qapp):
    """放大字号后超宽的行间公式不能伸出阅读区被裁掉。"""
    v = MarkdownView()
    v.resize(600, 400)
    terms = " + ".join("x_{%d}" % i for i in range(1, 45))
    v.set_markdown("$$" + terms + " = 0$$", "")
    v.show()
    qapp.processEvents()
    objs = _formula_objects(v)
    assert objs
    pos, fmt = objs[0]
    size = v._math.intrinsicSize(v.document(), pos, fmt)
    assert size.width() <= v.document().textWidth() + 1

    v.zoom_to(2.0)
    qapp.processEvents()
    size = v._math.intrinsicSize(v.document(), pos, fmt)
    assert size.width() <= v.document().textWidth() + 1
    v.close()


def test_formula_follows_font_size_and_theme(qapp):
    from PySide6.QtGui import QTextCharFormat

    v = MarkdownView()
    v.set_markdown("正文 $\\frac{a}{b}$\n", "")
    objs = _formula_objects(v)
    assert objs
    pos, fmt = objs[0]
    h0 = v._math.intrinsicSize(v.document(), pos, fmt).height()
    assert h0 > 0

    # 字号变大（缩放最终也是走这条路）公式必须跟着变大
    big = QTextCharFormat(fmt)
    base_pt = fmt.font().pointSizeF() if fmt.font().pointSizeF() > 0 else 12.0
    big.setFontPointSize(base_pt * 1.5)
    h1 = v._math.intrinsicSize(v.document(), pos, big).height()
    assert h1 > h0 * 1.2

    v.apply_theme({"card": "#101010", "text": "#f5f5f5", "accent": "#0a7",
                   "highlight": "#2a4", "hover": "#222", "border": "#333",
                   "text_secondary": "#aaa"})
    assert len(_formula_objects(v)) == 1
    assert _formula_objects(v)[0][1].property(SOURCE_PROP) == "\\frac{a}{b}"


def test_heading_formula_is_larger(qapp, tmp_path):
    w = _window(tmp_path)
    p = tmp_path / "h.md"
    p.write_text("# 标题 $x$\n\n正文 $x$\n", encoding="utf-8")
    try:
        tab = w.open_markdown(str(p))
        objs = _formula_objects(tab.canvas)
        assert len(objs) == 2
        h_head = tab.canvas._math.intrinsicSize(tab.canvas.document(), *objs[0]).height()
        h_body = tab.canvas._math.intrinsicSize(tab.canvas.document(), *objs[1]).height()
        assert h_head > h_body * 1.3
    finally:
        w.close()


def test_heading_with_formula_still_jumps(qapp):
    v = MarkdownView()
    v.set_markdown("# 公式 $x^2$ 标题\n\n正文\n", "")
    v.scroll_to_heading(0)          # 渲染后标题文字对不上，走块序号兜底
    assert v.textCursor().position() <= 1
    v.scroll_to_heading(99)         # 越界不抛异常


# ---------------------------------------------------------------------- #
# 背景功能：笔记仍在，Markdown 不适用（连续富文本，没有「页」）
# ---------------------------------------------------------------------- #
def test_background_controls_per_format(qapp, tmp_path):
    w = _window(tmp_path)
    md = tmp_path / "bg.md"
    md.write_text("正文\n", encoding="utf-8")
    try:
        w.open_markdown(str(md))
        # Markdown：没有网格 / 横线，但可以单独换阅读底色
        assert not w.combo_bg.isEnabled()
        assert w.btn_bg_color.isEnabled()
        assert w.btn_bg_color.toolTip() == "Markdown 阅读底色"
        assert not w.side_tabs.isTabEnabled(0)      # 「页面」缩略图：Markdown 没有页

        w.new_tab_note()
        assert w.combo_bg.isEnabled()
        assert w.btn_bg_color.isEnabled()
        assert w.btn_bg_color.toolTip() == "笔记背景色"
        assert w.side_tabs.isTabEnabled(0)
    finally:
        w.close()


def test_markdown_background_setter_is_noop(qapp):
    v = MarkdownView()
    v.set_markdown("正文\n", "")
    before = v.toHtml()
    v.set_background("grid", "#123456")
    v.set_canvas_bg("#123456")
    assert v.toHtml() == before
    assert v.canvas_bg == "#123456"


# ---------------------------------------------------------------------- #
# \boxed：语法树、方框绘制、超宽缩放
# ---------------------------------------------------------------------- #
def test_boxed_parses_and_keeps_source():
    tree = parse_math(r"\boxed{x^2}")
    assert any(isinstance(x, Boxed) for x in tree.items)
    assert math_to_plain(r"\boxed{x^2}") == "x²"


def test_boxed_renders_in_view_without_command_text(qapp):
    v = MarkdownView()
    v.set_markdown("行内 $\boxed{x^2}$ 结束\n\n$$\boxed{\frac{a}{b}}$$\n", "")
    assert "boxed" not in v.toPlainText()
    objs = _formula_objects(v)
    assert len(objs) == 2
    assert objs[0][1].property(SOURCE_PROP).startswith("\boxed")


def test_boxed_draws_a_border(qapp):
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(20)
    img = QImage(320, 140, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    try:
        box = math_box(r"\boxed{x^2}", font)
        paint_math_box(p, box, 40, 90, QColor("black"))
    finally:
        p.end()

    def dark_ratio(y, x0, x1):
        vals = [QColor(img.pixel(x, y)).lightness() < 128
                for x in range(x0, x1)]
        return sum(vals) / max(1, len(vals))

    top = 90 - box.asc
    bottom = 90 + box.desc
    xs, xe = int(40 + box.w * 0.15), int(40 + box.w * 0.85)
    assert max(dark_ratio(y, xs, xe)
               for y in range(int(top) - 1, int(top) + 3)) > 0.6, "上边框没画出来"
    assert max(dark_ratio(y, xs, xe)
               for y in range(int(bottom) - 2, int(bottom) + 2)) > 0.6, "下边框没画出来"


def test_overwide_boxed_scales_to_width(qapp):
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(18)
    box = math_box(r"\boxed{" + "x+" * 60 + "x}", font, False, 160.0)
    assert box.w <= 160.5

