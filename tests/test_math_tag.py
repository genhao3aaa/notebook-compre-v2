"""公式编号 ``\\tag`` 与声明式字体 ``\\rm`` 的回归测试。

线上缺陷（2026-11，用户附《新概念热学》第一章讲义反馈）：Markdown 里的
``$$... \\tag{1.9}$$`` 被渲染成正文里凭空多出的 ``tag1.9``，``^{\\rm mol}``
渲染成 ``rmmol``。根因不是渲染失败，而是 ``math_formula._parse_atom`` 的
「未知命令兜底」把命令名当成正体文字输出，再和后面的参数拼在一起。

这里同时守住三件事：
1. 编号必须保留（正文会引用「由 (1.8)(1.9) 得…」），但命令名绝不能出现；
2. ``\\rm`` 等声明式命令只切换字体，作用域到分组结束，本身不产生字形；
3. 未知命令保留反斜杠原样，不再伪装成正文单词。
"""
from __future__ import annotations

import re

import pytest
from PySide6.QtGui import QFont

from src.core.math_formula import (Tag, mask_math, math_to_plain,
                                   parse_math)
from src.ui.math_render import math_box

# 讲义里实际出现的形态（浓缩版）：行间公式、编号带逗号、\boxed + \tag、
# 上/下标里的 \rm（含中文）、\text + \quad + \tag、两个编号并列等。
LECTURE = r"""
# 第一章 热学基本概念

$$\lim_{p_0\to0}\alpha_p=\alpha=\frac1{t_0} \tag{1.4, 1.5}$$

$$\frac{p}{T}=\frac{p_0}{T_0}=\text{常量}\quad(V\ \text{给定}) \tag{1.9}$$

$$\frac{p_1V_1}{T_1}=\frac{p_2V_2}{T_2}\quad\Longrightarrow\quad \frac{pV}{T}=\text{常量} \tag{1.12, 1.13}$$

摩尔热容 $C^{\rm mol}=C/\nu$，潜热 $\Lambda^{\rm mol}$，下标 $K_{\rm c}$，
临界系数 $K_{\rm c}$，中文下标 $\Lambda_{\rm 熔化}$，体积 $V_G^{\rm mol}$。

$$\boxed{\ \bar\varepsilon=\frac32kT\ }\tag{1.32}\qquad\boxed{\ p=nkT\ }\tag{1.33}$$

$$p=\frac13 n\,\bar\varepsilon \tag{1.29R}$$

$$K=\frac32\frac{R}{N_A},\qquad k\equiv\frac{R}{N_A} \tag{1.31}$$

$$\boldsymbol R(l_1,l_2,l_3)=l_1\boldsymbol a_1 \tag{1.39}$$
"""


# ---------------------------------------------------------------------- #
# 解析层
# ---------------------------------------------------------------------- #
def test_tag_is_a_number_node_not_text():
    node = parse_math(r"E=mc^2 \tag{1.9}")
    tags = [n for n in node.items if isinstance(n, Tag)]
    assert len(tags) == 1
    assert tags[0].text == "1.9"
    assert tags[0].star is False
    assert tags[0].label == "(1.9)"
    # 顶层不能残留任何内容是字面 "tag" 的字形
    assert not any(getattr(n, "text", "") == "tag" for n in node.items)


def test_tag_star_omits_parentheses():
    tags = [n for n in parse_math(r"x \tag*{A}").items if isinstance(n, Tag)]
    assert len(tags) == 1 and tags[0].star is True
    assert tags[0].label == "A"


def test_tag_keeps_multi_number_and_letters():
    for src, expect in (
        (r"\tag{1.12, 1.13}", "1.12, 1.13"),
        (r"\tag{1.29N}", "1.29N"),
        (r"\tag{1.4, 1.5}", "1.4, 1.5"),
    ):
        tags = [n for n in parse_math(src).items if isinstance(n, Tag)]
        assert len(tags) == 1 and tags[0].text == expect


def test_tag_allows_space_before_group():
    tags = [n for n in parse_math(r"x \tag {1.7}").items if isinstance(n, Tag)]
    assert len(tags) == 1 and tags[0].text == "1.7"


def test_tag_inside_boxed_and_after_text():
    tree = parse_math(r"\boxed{\ p=nkT\ }\tag{1.33}")
    assert any(isinstance(n, Tag) for n in tree.items)
    assert "(1.33)" in math_to_plain(r"\boxed{\ p=nkT\ }\tag{1.33}")


def test_multiple_tags_on_one_line():
    tags = [n for n in parse_math(r"a \tag{1.32}\qquad b \tag{1.33}").items
            if isinstance(n, Tag)]
    assert [t.text for t in tags] == ["1.32", "1.33"]


def test_rm_is_a_declaration_not_a_glyph():
    # \rm 不产生 "rm" 字面文字，而是把组内后续字符切成正体
    assert "rm" not in math_to_plain(r"C^{\rm mol}")
    assert math_to_plain(r"C^{\rm mol}") == "C^(mol)"
    assert math_to_plain(r"\Lambda_{\rm 熔化}") == "Λ_(熔化)"
    assert math_to_plain(r"K_{\rm c}") == "K_(c)"
    assert math_to_plain(r"V_G^{\rm mol}") == "V_(G)^(mol)"


def test_rm_scope_restores_after_group():
    # {\rm a}b：a 正体，分组外的 b 仍是数学斜体
    tree = parse_math(r"{\rm a}b")
    outer = tree.items[-1]
    assert getattr(outer, "style", None) == "math"


def test_decl_styles_are_applied():
    from src.core.math_formula import Seq, Sym

    tree = parse_math(r"{\bf x}")
    syms = [n for n in tree.items if isinstance(n, Seq)
            for n in n.items if isinstance(n, Sym)]
    assert syms and all(s.style == "bf" for s in syms)


def test_invisible_commands_produce_no_text():
    for cmd in ("\\limits", "\\displaystyle", "\\nonumber", "\\notag",
                "\\qquad", "\\quad", "\\,", "\\!"):
        assert math_to_plain(cmd) == "", cmd
    # \label 连同参数一起吞掉
    assert math_to_plain(r"x\label{eq:1}y") == "xy"


def test_unknown_command_keeps_backslash():
    # 关键回归：不能把命令名吐成正文（否则 \tag → "tag1.9"）
    assert math_to_plain(r"\notacommand") == "\\notacommand"
    assert not math_to_plain(r"\notacommand{1.9}").startswith("notacommand")


# ---------------------------------------------------------------------- #
# 纯文本降级（目录 / 搜索 / 无障碍）
# ---------------------------------------------------------------------- #
def test_plain_text_never_leaks_command_names():
    _, segs = mask_math(LECTURE)
    assert len(segs) >= 10
    for seg in segs:
        plain = math_to_plain(seg.source)
        assert "tag" not in plain, seg.source
        # 只匹配「rm 后紧跟内容」（命令名泄漏），不匹配 thermoscope 之类正文词
        assert not re.search(r"(?<![A-Za-z])rm[A-Za-z\u4e00-\u9fff]", plain), seg.source
    # 编号仍在（8 处 \tag 分布在 7 个公式段里，(1.32)(1.33) 同段）
    numbers = [math_to_plain(s.source) for s in segs]
    assert sum("(1." in n for n in numbers) == 7
    assert any("(1.12, 1.13)" in n for n in numbers)
    assert any("(1.29R)" in n for n in numbers)


def test_full_lecture_has_no_visible_tag_or_rm():
    """浓缩讲义整篇扫描：任何一个公式段都不出现命令名字样。"""
    _, segs = mask_math(LECTURE)
    bad = [s.source for s in segs
           if "tag" in math_to_plain(s.source)
           or re.search(r"(?<![A-Za-z])rm[A-Za-z\u4e00-\u9fff]",
                        math_to_plain(s.source))]
    assert not bad, bad


# ---------------------------------------------------------------------- #
# 渲染层
# ---------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_math_box_renders_tag_without_error(qapp):
    font = QFont("Times New Roman", 14)
    for display in (False, True):
        box = math_box(r"E=mc^2 \tag{1.9}", font, display=display,
                       max_width=600.0)
        # 缩放是浮点乘法，不同机器的字体度量会让结果溢出 max_width 约 1e-14
        assert box.w > 0 and box.w <= 600.0 + 1e-6


def test_math_box_tag_right_aligned_when_room(qapp):
    font = QFont("Times New Roman", 14)
    with_tag = math_box(r"E=mc^2 \tag{1.9}", font, display=True,
                        max_width=600.0)
    without_tag = math_box(r"E=mc^2", font, display=True, max_width=600.0)
    # 有编号时盒子占满可用宽度（编号贴右边缘），无编号时只占公式本身
    assert with_tag.w > without_tag.w


def test_math_box_tag_degrades_when_narrow(qapp):
    font = QFont("Times New Roman", 14)
    box = math_box(r"\frac{a}{b}+\frac{c}{d}+\frac{e}{f} \tag{1.9}", font,
                   display=True, max_width=60.0)
    assert box.w <= 60.0 + 1e-6


def test_math_box_all_lecture_formulas(qapp):
    """整篇讲义的每一段公式都能排版（不抛异常、宽度合理）。"""
    font = QFont("Times New Roman", 14)
    _, segs = mask_math(LECTURE)
    for seg in segs:
        box = math_box(seg.source, font, display=seg.display, max_width=600.0)
        assert box.w > 0, seg.source
        assert box.asc + box.desc > 0, seg.source


# ---------------------------------------------------------------------- #
# 视图集成：渲染后的文档里不该出现 "tag" 字样
# ---------------------------------------------------------------------- #
def test_view_renders_lecture_without_tag_literal(qapp, tmp_path):
    import os
    from PySide6.QtWidgets import QApplication

    from src.ui.markdown_view import MarkdownView

    path = str(tmp_path / "lecture.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(LECTURE)
    view = MarkdownView()
    view.resize(900, 700)
    view.set_markdown(LECTURE, path)
    QApplication.processEvents()
    text = view.toPlainText()
    assert "tag" not in text
    assert "(1." not in text        # 编号是矢量公式对象，不是普通文本
    assert view.document().blockCount() > 0
    view.close()
