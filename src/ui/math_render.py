"""把公式语法树排版并绘制成 QTextDocument 里的内联对象。

分两层：
* 这里的 Box 类只负责几何（宽 / 基线以上 / 基线以下），用 QPainter 画；
* MathObjectHandler 实现 QTextObjectInterface，让公式跟随字号与缩放，
  并且始终是矢量的（不是预渲染图片）。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                           QPen, QPyTextObject, QTextFormat)

from src.core.math_formula import (ENV_DELIMS, Accent, BigOp, Boxed, Delim,
                                   Frac, Func, LineBreak, Matrix, Script, Seq,
                                   Space, Sqrt, Sym, parse_math)

#: 自定义内联对象类型 / 属性键（只在本模块与 MarkdownView 之间约定）
MATH_OBJECT_TYPE = QTextFormat.ObjectTypes.UserObject + 41
SOURCE_PROP = QTextFormat.Property.UserProperty + 1
DISPLAY_PROP = QTextFormat.Property.UserProperty + 2


# ---------------------------------------------------------------------- #
# 几何盒
# ---------------------------------------------------------------------- #
class _Box:
    __slots__ = ("w", "asc", "desc")

    def __init__(self, w: float = 0.0, asc: float = 0.0, desc: float = 0.0):
        self.w = w
        self.asc = asc
        self.desc = desc

    def draw(self, p: QPainter, x: float, base: float) -> None:
        pass


class _Empty(_Box):
    pass


class _Pad(_Box):
    def __init__(self, inner: _Box, pad: float):
        super().__init__(inner.w + 2 * pad, inner.asc, inner.desc)
        self.inner = inner
        self.pad = pad

    def draw(self, p: QPainter, x: float, base: float) -> None:
        self.inner.draw(p, x + self.pad, base)


class _Glyph(_Box):
    def __init__(self, text: str, font: QFont):
        fm = QFontMetricsF(font)
        super().__init__(fm.horizontalAdvance(text), fm.ascent(), fm.descent())
        self.text = text
        self.font = font

    def draw(self, p: QPainter, x: float, base: float) -> None:
        p.setFont(self.font)
        p.drawText(QPointF(x, base), self.text)


class _HBox(_Box):
    def __init__(self, parts: Sequence[Tuple[_Box, float]]):
        self.parts = list(parts)
        w = 0.0
        asc = 0.0
        desc = 0.0
        for box, x in self.parts:
            w = max(w, x + box.w)
            asc = max(asc, box.asc)
            desc = max(desc, box.desc)
        super().__init__(w, asc, desc)

    def draw(self, p: QPainter, x: float, base: float) -> None:
        for box, dx in self.parts:
            box.draw(p, x + dx, base)


class _Scaled(_Box):
    """把过宽的公式整体等比缩到可用宽度内（阅读视图没有横向滚动）。"""

    def __init__(self, inner: _Box, scale: float):
        self.inner = inner
        self.scale = max(0.01, float(scale))
        super().__init__(inner.w * self.scale, inner.asc * self.scale,
                         inner.desc * self.scale)

    def draw(self, p: QPainter, x: float, base: float) -> None:
        p.save()
        p.translate(x, base)
        p.scale(self.scale, self.scale)
        self.inner.draw(p, 0.0, 0.0)
        p.restore()


class _Stack(_Box):
    """多行公式：每行按最宽行居中，基线与第一行一致。"""

    def __init__(self, rows: Sequence[_Box], gap: float):
        self.rows = list(rows)
        self.gap = gap
        width = max((r.w for r in self.rows), default=0.0)
        first = self.rows[0].asc if self.rows else 0.0
        total = sum(r.asc + r.desc for r in self.rows)
        total += gap * max(0, len(self.rows) - 1)
        super().__init__(width, first, max(0.0, total - first))

    def draw(self, p: QPainter, x: float, base: float) -> None:
        y = base
        for i, row in enumerate(self.rows):
            row.draw(p, x + (self.w - row.w) / 2, y)
            y += row.desc + self.gap
            if i + 1 < len(self.rows):
                y += self.rows[i + 1].asc


class _Frac(_Box):
    def __init__(self, num: _Box, den: _Box, em: float, bar: bool = True):
        t = max(1.0, 0.05 * em) if bar else 0.0
        self.bar = bar
        axis = 0.26 * em
        gap = 0.16 * em
        self.num = num
        self.den = den
        self.t = t
        self.axis = axis
        self.num_base = -(axis + t / 2 + gap + num.desc)
        self.den_base = -axis + t / 2 + gap + den.asc
        super().__init__(max(num.w, den.w) + 0.24 * em,
                         axis + t / 2 + gap + num.asc + num.desc,
                         max(0.0, self.den_base + den.desc))

    def draw(self, p: QPainter, x: float, base: float) -> None:
        pad = (self.w - max(self.num.w, self.den.w)) / 2
        self.num.draw(p, x + pad + (max(self.num.w, self.den.w) - self.num.w) / 2,
                      base + self.num_base)
        self.den.draw(p, x + pad + (max(self.num.w, self.den.w) - self.den.w) / 2,
                      base + self.den_base)
        if self.bar:
            y = base - self.axis - self.t / 2
            p.fillRect(QRectF(x + 0.12 * self.axis, y,
                              self.w - 0.24 * self.axis, self.t),
                       p.pen().color())


class _Sqrt(_Box):
    def __init__(self, body: _Box, index: Optional[_Box], em: float):
        self.body = body
        self.index = index
        self.em = em
        self.rad = 0.72 * em
        self.bar_y = -(body.asc + 0.10 * em)
        idx_w = (index.w + 0.10 * em) if index is not None else 0.0
        self.body_x = idx_w + self.rad
        self.idx_x = 0.0
        self.idx_base = self.bar_y - 0.02 * em
        asc = -self.bar_y
        if index is not None:
            asc = max(asc, -self.idx_base + index.asc)
        super().__init__(self.body_x + body.w + 0.10 * em,
                         asc, max(body.desc, 0.04 * em))

    def draw(self, p: QPainter, x: float, base: float) -> None:
        if self.index is not None:
            self.index.draw(p, x + self.idx_x, base + self.idx_base)
        self.body.draw(p, x + self.body_x, base)
        em = self.em
        path = QPainterPath()
        path.moveTo(x + 0.02 * em, base + self.bar_y + 0.42 * em)
        path.lineTo(x + 0.18 * em, base + self.bar_y + 0.36 * em)
        path.lineTo(x + 0.38 * em, base + 0.01 * em)
        path.lineTo(x + 0.60 * em, base + self.bar_y)
        path.lineTo(x + self.w, base + self.bar_y)
        pen = QPen(p.pen())
        pen.setWidthF(max(1.0, 0.035 * em))
        p.save()
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.restore()


class _ScriptBox(_Box):
    def __init__(self, base_box: _Box, sup: Optional[_Box], sub: Optional[_Box],
                 em: float, limits: bool):
        self.base = base_box
        self.sup = sup
        self.sub = sub
        self.limits = limits
        gap = 0.10 * em
        if limits:
            w = max(base_box.w, sup.w if sup else 0.0, sub.w if sub else 0.0)
            self.base_x = (w - base_box.w) / 2
            self.sup_x = (w - (sup.w if sup else 0.0)) / 2
            self.sub_x = (w - (sub.w if sub else 0.0)) / 2
            self.sup_base = -(base_box.asc + gap + (sup.desc if sup else 0.0))
            self.sub_base = base_box.desc + gap + (sub.asc if sub else 0.0)
            asc = base_box.asc
            desc = base_box.desc
            if sup is not None:
                asc = max(asc, -self.sup_base + sup.asc)
            if sub is not None:
                desc = max(desc, self.sub_base + sub.desc)
            super().__init__(w, asc, desc)
        else:
            self.base_x = 0.0
            self.sup_x = base_box.w + 0.02 * em
            self.sub_x = base_box.w + 0.02 * em
            # 基座很高（分式 / 括号）时上标跟着抬高，避免压在基座中间
            self.sup_base = -max(0.42 * em, base_box.asc * 0.62)
            self.sub_base = max(0.20 * em, base_box.desc * 0.55)
            asc = base_box.asc
            desc = base_box.desc
            if sup is not None:
                asc = max(asc, -self.sup_base + sup.asc)
            if sub is not None:
                desc = max(desc, self.sub_base + sub.desc)
            super().__init__(max(base_box.w, self.sup_x + (sup.w if sup else 0.0),
                                 self.sub_x + (sub.w if sub else 0.0)), asc, desc)

    def draw(self, p: QPainter, x: float, base: float) -> None:
        self.base.draw(p, x + self.base_x, base)
        if self.sup is not None:
            self.sup.draw(p, x + self.sup_x, base + self.sup_base)
        if self.sub is not None:
            self.sub.draw(p, x + self.sub_x, base + self.sub_base)


class _DelimBox(_Box):
    """可纵向拉伸的括号。横向不拉伸，避免笔画变粗。"""

    def __init__(self, text: str, target_h: float, font: QFont, em: float):
        fm = QFontMetricsF(font)
        nat = max(1.0, fm.ascent() + fm.descent())
        self.text = text
        self.font = font
        self.k = max(1.0, target_h / nat)
        self.w = fm.horizontalAdvance(text)
        self.asc_n = fm.ascent()
        self.desc_n = fm.descent()
        body_center = 0.0
        glyph_center = (self.desc_n - self.asc_n) * self.k / 2
        self.shift = body_center - glyph_center
        top = self.shift - self.asc_n * self.k
        bottom = self.shift + self.desc_n * self.k
        super().__init__(self.w, max(0.0, -top), max(0.0, bottom))

    def draw(self, p: QPainter, x: float, base: float) -> None:
        p.save()
        p.translate(x, base + self.shift)
        p.scale(1.0, self.k)
        p.setFont(self.font)
        p.drawText(QPointF(0.0, 0.0), self.text)
        p.restore()


class _MatrixBox(_Box):
    def __init__(self, rows: List[List[_Box]], col_gap: float, row_gap: float,
                 axis: float):
        self.rows = rows
        ncol = max((len(r) for r in rows), default=1)
        self.col_w = [max((r[j].w for r in rows if j < len(r)), default=0.0)
                      for j in range(ncol)]
        self.row_asc = [max((b.asc for b in r), default=0.0) for r in rows]
        self.row_desc = [max((b.desc for b in r), default=0.0) for r in rows]
        self.col_gap = col_gap
        self.row_gap = row_gap
        self.axis = axis
        content_w = sum(self.col_w) + col_gap * max(0, ncol - 1)
        content_h = (sum(self.row_asc) + sum(self.row_desc)
                     + row_gap * max(0, len(rows) - 1))
        self.col_x: List[float] = []
        x = 0.0
        for w in self.col_w:
            self.col_x.append(x)
            x += w + col_gap
        self.top = -(content_h / 2 + axis)
        super().__init__(content_w, content_h / 2 + axis,
                         max(0.0, content_h / 2 - axis))

    def draw(self, p: QPainter, x: float, base: float) -> None:
        y = base + self.top
        for ri, row in enumerate(self.rows):
            row_base = y + self.row_asc[ri]
            for ci, cell in enumerate(row):
                cx = x + self.col_x[ci] + (self.col_w[ci] - cell.w) / 2
                cell.draw(p, cx, row_base)
            y += self.row_asc[ri] + self.row_desc[ri] + self.row_gap


class _AccentBox(_Box):
    def __init__(self, kind: str, body: _Box, em: float):
        self.kind = kind
        self.body = body
        self.em = em
        if kind == "underline":
            super().__init__(max(body.w, 0.3 * em), body.asc,
                             body.desc + 0.18 * em)
        else:
            extra = 0.26 if kind in ("vec", "hat", "tilde") else 0.18
            super().__init__(max(body.w, 0.3 * em), body.asc + extra * em,
                             body.desc)

    def draw(self, p: QPainter, x: float, base: float) -> None:
        self.body.draw(p, x, base)
        em = self.em
        cx = x + self.body.w / 2
        w = max(0.25 * em, min(self.body.w, 0.7 * em))
        pen = QPen(p.pen())
        pen.setWidthF(max(1.0, 0.045 * em))
        p.save()
        p.setPen(pen)
        if self.kind == "underline":
            y = base + self.body.desc + 0.10 * em
            p.drawLine(QPointF(x, y), QPointF(x + self.body.w, y))
        elif self.kind in ("bar", "overline"):
            y = base - self.body.asc - 0.08 * em
            p.drawLine(QPointF(x, y), QPointF(x + self.body.w + 0.02 * em, y))
        elif self.kind == "vec":
            y = base - self.body.asc - 0.10 * em
            p.drawLine(QPointF(cx - w / 2, y), QPointF(cx + w / 2, y))
            p.drawLine(QPointF(cx + w / 2, y), QPointF(cx + w / 2 - 0.12 * em, y - 0.08 * em))
            p.drawLine(QPointF(cx + w / 2, y), QPointF(cx + w / 2 - 0.12 * em, y + 0.08 * em))
        elif self.kind in ("dot", "ddot"):
            r = max(0.9, 0.04 * em)
            y = base - self.body.asc - 0.12 * em
            p.setBrush(p.pen().color())
            p.drawEllipse(QPointF(cx, y), r, r)
            if self.kind == "ddot":
                p.drawEllipse(QPointF(cx - 0.20 * em, y), r, r)
        elif self.kind == "tilde":
            y = base - self.body.asc - 0.12 * em
            path = QPainterPath()
            path.moveTo(cx - w / 2, y)
            path.cubicTo(cx - w / 4, y - 0.10 * em, cx, y + 0.10 * em, cx + w / 2, y)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        else:  # hat
            y = base - self.body.asc - 0.11 * em
            p.drawLine(QPointF(cx - w / 2, y), QPointF(cx, y - 0.12 * em))
            p.drawLine(QPointF(cx, y - 0.12 * em), QPointF(cx + w / 2, y))
        p.restore()


class _BoxedBox(_Box):
    """\boxed{...}：公式外画一个细边框，内边距按 em 缩放。

    边框用当前画笔颜色（随主题 / 阅读底色变化），线宽按字号缩放；
    所有几何都留在对象矩形内，避免缩放或贴近行首时被裁掉。
    """

    def __init__(self, body: _Box, em: float):
        self.body = body
        self.em = em
        self.pad_x = 0.30 * em
        self.pad_y = 0.22 * em
        self.thickness = max(1.0, 0.045 * em)
        super().__init__(body.w + 2 * self.pad_x,
                         body.asc + self.pad_y,
                         body.desc + self.pad_y)

    def draw(self, p: QPainter, x: float, base: float) -> None:
        self.body.draw(p, x + self.pad_x, base)
        t = self.thickness
        pen = QPen(p.pen())
        pen.setWidthF(t)
        p.save()
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(x + t / 2.0, base - self.asc + t / 2.0,
                          max(1.0, self.w - t), max(1.0, self.asc + self.desc - t)))
        p.restore()


# ---------------------------------------------------------------------- #
# 排版
# ---------------------------------------------------------------------- #
def _font_size(font: QFont) -> Tuple[float, bool]:
    """返回 (字号, 是否像素模式)。全局 QSS 用 px 指定字号时 pointSize 是 -1。"""
    ps = font.pointSizeF()
    if ps > 0:
        return ps, False
    px = font.pixelSize()
    if px > 0:
        return float(px), True
    return 10.0, False


class _Ctx:
    def __init__(self, base: QFont, size: float, display: bool,
                 pixel_mode: bool = False):
        self.base = QFont(base)
        self.size = max(4.0, float(size))
        self.display = display
        self.pixel_mode = pixel_mode
        self._fonts: Dict[Tuple[str, float], QFont] = {}
        fm = QFontMetricsF(self.font("math", self.size))
        self.em = max(6.0, fm.height() * 0.86)

    def font(self, style: str, size: float) -> QFont:
        key = (style, round(size, 2))
        cached = self._fonts.get(key)
        if cached is not None:
            return cached
        f = QFont(self.base)
        if self.pixel_mode:
            f.setPixelSize(max(1, int(round(size))))
        else:
            f.setPointSizeF(max(1.0, float(size)))
        if style in ("math", "it"):
            f.setItalic(True)
        elif style in ("up", "text"):
            f.setItalic(False)
        if style == "bf":
            f.setBold(True)
            f.setItalic(False)
        self._fonts[key] = f
        return f


def _gap_cls(pc: Optional[str], cc: str, em: float) -> float:
    if pc is None:
        return 0.0
    if cc == "bin":
        # 一元正负号（开头 / 括号后 / 关系符后）两侧都不留空格
        if pc in ("open", "rel", "bin", "punct", "op"):
            return 0.0
        return 0.20 * em
    if pc == "bin":
        return 0.20 * em
    if pc == "rel" or cc == "rel":
        return 0.26 * em
    if pc == "punct":
        return 0.15 * em
    if pc == "op":
        # 函数名后面留一个细空格；脚本属于函数名，空格加在脚本之后
        return 0.167 * em
    return 0.0


def _gap(prev: Optional[object], cur: object, em: float) -> float:
    if prev is None:
        return 0.0
    return _gap_cls(_cls(prev), _cls(cur), em)


def _cls(node: object) -> str:
    if isinstance(node, Sym):
        return node.cls
    if isinstance(node, (Func, BigOp)):
        return "op"
    if isinstance(node, Script):
        return _cls(node.base)      # log_2 / sin^2 仍算函数，后面要留空格
    return "ord"


def _layout_items(items: Sequence[object], ctx: _Ctx, size: float) -> _Box:
    parts: List[Tuple[_Box, float]] = []
    x = 0.0
    prev_cls: Optional[str] = None
    for item in items:
        cls = _cls(item)
        unary = (cls == "bin"
                 and (prev_cls is None
                      or prev_cls in ("open", "rel", "bin", "punct", "op")))
        eff_cls = "ord" if unary else cls
        x += _gap_cls(prev_cls, cls, ctx.em)
        box = _layout(item, ctx, size)
        parts.append((box, x))
        x += box.w
        prev_cls = eff_cls
    return _HBox(parts)


def _layout_sym(node: Sym, ctx: _Ctx, size: float) -> _Box:
    if not node.text:
        return _Empty()
    # 只把拉丁 / 希腊 / 西里尔字母斜体化；中文、日文等保持正体
    if node.style == "math" and all(c.isalpha() and ord(c) < 0x2E80
                                    for c in node.text):
        font = ctx.font("it", size)
    elif node.style in ("math", "up", "text"):
        font = ctx.font("up", size)
    else:
        font = ctx.font(node.style, size)
    return _Glyph(node.text, font)


def _layout(node: object, ctx: _Ctx, size: float) -> _Box:
    if isinstance(node, Seq):
        if any(isinstance(item, LineBreak) for item in node.items):
            rows: List[List[object]] = [[]]
            for item in node.items:
                if isinstance(item, LineBreak):
                    rows.append([])
                else:
                    rows[-1].append(item)
            while len(rows) > 1 and not rows[-1]:
                rows.pop()             # 行尾 <br> 不额外留一个空行
            while len(rows) > 1 and not rows[0]:
                rows.pop(0)
            return _Stack([_layout_items(row, ctx, size) for row in rows],
                          0.36 * ctx.em)
        return _layout_items(node.items, ctx, size)
    if isinstance(node, Sym):
        return _layout_sym(node, ctx, size)
    if isinstance(node, Space):
        return _Box(max(0.0, node.em) * ctx.em)
    if isinstance(node, Func):
        return _Glyph(node.text, ctx.font("up", size))
    if isinstance(node, Frac):
        sub_size = size * (0.94 if ctx.display else 0.84)
        num = _layout(node.num, ctx, sub_size)
        den = _layout(node.den, ctx, sub_size)
        return _Frac(num, den, ctx.em, node.bar)
    if isinstance(node, Sqrt):
        body = _layout(node.body, ctx, size)
        index = None
        if node.index is not None:
            index = _layout(node.index, ctx, size * 0.62)
        return _Sqrt(body, index, ctx.em)
    if isinstance(node, Script):
        base = _layout(node.base, ctx, size)
        sup_size = size * 0.68
        sub_size = size * 0.68
        sup = _layout(node.sup, ctx, sup_size) if node.sup is not None else None
        sub = _layout(node.sub, ctx, sub_size) if node.sub is not None else None
        # 行内不把求和 / 极限的上下标压到正下方（TeX 的 textstyle 也是放右侧）
        limits = (isinstance(node.base, BigOp) and node.base.limits
                  and ctx.display)
        return _ScriptBox(base, sup, sub, ctx.em, limits)
    if isinstance(node, Delim):
        body = _layout(node.body, ctx, size)
        target = body.asc + body.desc + 0.10 * ctx.em
        parts: List[Tuple[_Box, float]] = []
        x = 0.0
        if node.left:
            d = _DelimBox(node.left, target, ctx.font("up", size), ctx.em)
            parts.append((d, x))
            x += d.w + 0.04 * ctx.em
        parts.append((body, x))
        x += body.w
        if node.right:
            d = _DelimBox(node.right, target, ctx.font("up", size), ctx.em)
            x += 0.04 * ctx.em
            parts.append((d, x))
            x += d.w
        return _HBox(parts)
    if isinstance(node, BigOp):
        scale = 1.0
        if node.limits and node.text in "∑∏∐⋃⋂⊕⊗":
            scale = 1.7 if ctx.display else 1.35
        elif node.text in "∫∬∭∮":
            scale = 1.6 if ctx.display else 1.3
        font = ctx.font("up", size * scale)
        return _Glyph(node.text, font)
    if isinstance(node, Accent):
        return _AccentBox(node.kind, _layout(node.body, ctx, size), ctx.em)
    if isinstance(node, Boxed):
        return _BoxedBox(_layout(node.body, ctx, size), ctx.em)
    if isinstance(node, Matrix):
        rows = [[_layout(cell, ctx, size) for cell in row] for row in node.rows]
        body = _MatrixBox(rows, 0.70 * ctx.em, 0.36 * ctx.em, 0.25 * ctx.em)
        left, right = ENV_DELIMS.get(node.env, ("", ""))
        if not left and not right:
            return body
        target = body.asc + body.desc + 0.12 * ctx.em
        parts: List[Tuple[_Box, float]] = []
        x = 0.0
        if left:
            d = _DelimBox(left, target, ctx.font("up", size), ctx.em)
            parts.append((d, x))
            x += d.w + 0.04 * ctx.em
        parts.append((body, x))
        x += body.w
        if right:
            d = _DelimBox(right, target, ctx.font("up", size), ctx.em)
            x += 0.04 * ctx.em
            parts.append((d, x))
        return _HBox(parts)
    return _Empty()


# ---------------------------------------------------------------------- #
# 公共排版入口：正文对象 / 目录树共用同一套盒模型
# ---------------------------------------------------------------------- #
_BOX_CACHE: Dict[Tuple, _Box] = {}


def math_box(source: str, font: QFont, display: bool = False,
             max_width: float = 0.0) -> _Box:
    """把一段 LaTeX 排成一个几何盒（带缓存）。

    display=True 走行间公式的字号规则（分式不缩小、大运算符放大）；
    max_width > 0 时，超宽公式整体等比缩到该宽度内。
    """
    ps, pixel_mode = _font_size(font)
    limit = int(round(max_width)) if max_width > 0 else 0
    key = (source, display, round(ps, 2), pixel_mode,
           tuple(font.families()) or (font.family(),),
           int(font.weight()), font.italic(), limit)
    box = _BOX_CACHE.get(key)
    if box is None:
        ctx = _Ctx(font, ps, display, pixel_mode)
        box = _layout(parse_math(source), ctx, ps)
        if not display:
            box = _Pad(box, 0.08 * ctx.em)
        if max_width > 0 and box.w > max_width:
            box = _Scaled(box, max_width / box.w)
        if len(_BOX_CACHE) > 768:
            _BOX_CACHE.clear()
        _BOX_CACHE[key] = box
    return box


def paint_math_box(painter: QPainter, box: _Box, x: float, baseline: float,
                   color: QColor) -> None:
    """在任意 QPainter 上画公式（目录树等非文档控件复用）。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setPen(color)
    painter.setBrush(color)
    box.draw(painter, x, baseline)
    painter.restore()


# ---------------------------------------------------------------------- #
# QTextDocument 内联对象
# ---------------------------------------------------------------------- #
class MathObjectHandler(QPyTextObject):
    """把公式对象画进 QTextDocument；字号 / 缩放 / 颜色都跟着文档走。"""

    def __init__(self) -> None:
        super().__init__()
        self.fg = QColor("#2b2a26")
        self._cache: Dict[Tuple, _Box] = {}

    def clear_cache(self) -> None:
        self._cache.clear()
        _BOX_CACHE.clear()

    def _box(self, source: str, display: bool, font: QFont,
             max_width: float = 0.0) -> _Box:
        return math_box(source, font, display, max_width)

    # -- QTextObjectInterface ---------------------------------------- #
    def intrinsicSize(self, doc, pos_in_document, fmt) -> QSizeF:  # noqa: N802
        cf = fmt.toCharFormat() if isinstance(fmt, QTextFormat) else fmt
        source = cf.property(SOURCE_PROP)
        if not isinstance(source, str) or not source:
            return QSizeF(0.0, 0.0)
        display = bool(cf.property(DISPLAY_PROP))
        width = float(doc.textWidth()) if doc is not None else 0.0
        box = self._box(source, display, cf.font(),
                        max(0.0, width - 4.0) if width > 0 else 0.0)
        return QSizeF(box.w, box.asc + box.desc)

    def drawObject(self, painter, rect, doc, pos_in_document, fmt) -> None:  # noqa: N802
        cf = fmt.toCharFormat() if isinstance(fmt, QTextFormat) else fmt
        source = cf.property(SOURCE_PROP)
        if not isinstance(source, str) or not source:
            return
        display = bool(cf.property(DISPLAY_PROP))
        width = float(doc.textWidth()) if doc is not None else 0.0
        box = self._box(source, display, cf.font(),
                        max(0.0, width - 4.0) if width > 0 else 0.0)
        brush = cf.foreground()
        color = brush.color() if brush.style() != Qt.BrushStyle.NoBrush else QColor(self.fg)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(color)
        painter.setBrush(color)
        base = rect.top() + box.asc if display else rect.bottom()
        box.draw(painter, rect.left(), base)
        painter.restore()
