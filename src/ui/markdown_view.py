"""Markdown 只读阅读视图（基于 QTextBrowser）。

设计要点
--------
* **零新依赖**：用 PySide6 自带 QTextDocument 的 Markdown 解析器
  （标题 / 列表 / 表格 / 引用 / 代码块 / 链接 / 图片 / 粗斜体）。
* **与 PageCanvas duck-type 兼容**：MainWindow 里大量通用代码会无差别地往
  「当前标签的 canvas」发消息（切标签、主题刷新、工具样式、资源释放、
  多窗口搬运）。MarkdownView 实现同名的最小桩，让这些路径对 Markdown
  标签安全且无副作用；真正的业务分流（保存 / 翻页 / 批注 / 搜索）在
  controllers 里按 `tab.is_md` 显式处理。
* **复用现有侧栏**：标题大纲接「目录」、全文检索接「搜索」，不另起面板。
"""
from __future__ import annotations

import bisect
import os
import re
from typing import List, Optional, Sequence

from PySide6.QtCore import (QEvent, QMimeData, QPoint, QRectF, QTimer, Qt,
                           QUrl, Signal)
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont,
                           QPainter, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextFormat,
                           QTextFrameFormat, QTextOption, QTextTable,
                           QTextTableFormat)
from PySide6.QtWidgets import QFrame, QTextBrowser, QTextEdit, QWidget

from src.core.colors import ink_contrast_color, is_dark
from src.core.markdown_document import (MdHeading, MdSearchHit, is_markdown,
                                        parse_headings)
from src.core.math_formula import mask_math
from src.ui.math_render import (DISPLAY_PROP, MATH_OBJECT_TYPE, SOURCE_PROP,
                                MathObjectHandler)

#: 正文 15px × 0.75 = 11.25px；再小会落到 8px 以下，中文字形必然发虚。
_ZOOM_MIN = 0.75
_ZOOM_MAX = 3.0
#: 页面边缘多宽算作拖拽命中区（含正文内部一点点，方便满宽时抓取）
_EDGE_HIT = 10


def _escaped_markdown(text: str, index: int) -> bool:
    """index 处的字符是否被奇数个反斜杠转义。"""
    back = 0
    i = index - 1
    while i >= 0 and text[i] == "\\":
        back += 1
        i -= 1
    return back % 2 == 1


class _BoundaryOverlay(QWidget):
    """整页透明覆盖层：只画阅读区左右边界，不接收鼠标。

    旧方案用两个子控件当手柄，宽度/遮罩/层叠顺序互相牵制，边界偶尔会消失。
    这里把绘制和交互拆开：这一层只负责稳定地画两条线，鼠标完全穿透；
    拖拽命中由 MarkdownView 自己在 viewport / 留白上处理。
    """

    def __init__(self, view: "MarkdownView") -> None:
        super().__init__(view)
        self._view = view
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, e) -> None:
        view = self._view
        if not view._text:
            return
        left, right = view._edge_positions()
        if right - left <= 4:
            return
        active = view._edge_hot or view._edge_drag
        accent = QColor(view._highlight_fg)
        line = QColor(accent)
        line.setAlpha(220 if active else 140)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if active:
            fill = QColor(accent)
            fill.setAlpha(14)
            if active == "left" and left > 0:
                p.fillRect(QRectF(0, 0, left, self.height()), fill)
            elif active == "right" and right < self.width():
                p.fillRect(QRectF(right, 0, self.width() - right,
                                  self.height()), fill)
        p.fillRect(QRectF(left, 0, 2, self.height()), line)
        p.fillRect(QRectF(right - 2, 0, 2, self.height()), line)
        p.end()


class MarkdownView(QTextBrowser):
    """渲染 Markdown 的只读富文本视图。"""

    #: 点击了指向另一份本地 .md 的链接 → 让主窗口在新标签打开
    open_markdown_requested = Signal(str)
    #: 缩放比例变化（Ctrl+滚轮 / 工具栏）；主窗口用它同步顶栏数字
    zoom_changed = Signal(float)
    #: 拖拽左右留白后请求的新阅读宽度（px；0 = 自动铺满）
    reading_width_changed = Signal(int)
    #: 当前页面允许的最大阅读宽度变化（窗口 / 滚动条尺寸变了）
    reading_width_max_changed = Signal(int)
    #: 视口顶部所在的标题序号变化（-1 = 还在第一个标题之前）
    current_heading_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        # 自己处理链接：避免 QTextBrowser 把相对链接 setSource 成乱码盖掉当前文档
        self.setOpenLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        # 阅读视图不需要横向滚动：文字按阅读栏宽度折行
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setUndoRedoEnabled(False)
        self.setTabStopDistance(28.0)
        self.anchorClicked.connect(self._on_anchor)
        self._base_font = QFont(self.font())
        # 阅读字号比 UI 字号大一点（正文 15px），更像阅读器而不是表格
        if self._base_font.pixelSize() > 0:
            self._base_font.setPixelSize(15)
        else:
            self._base_font.setPointSizeF(11.25)
        self._gutter = 0               # 阅读栏左右额外留白（随窗口宽度居中）
        self._column_width = 0         # 0 = 自动铺满；>0 = 固定正文宽度
        self._max_column_width = 0
        self._column_timer = QTimer(self)
        self._column_timer.setSingleShot(True)
        self._column_timer.timeout.connect(self._apply_text_width)
        # 纵向滚动条出现/消失会改变视口宽度（不触发 resizeEvent）
        self.verticalScrollBar().rangeChanged.connect(self._on_vscroll_range)

        self._text: str = ""
        self._masked: str = ""
        self._segments: list = []
        self._path: str = ""
        self._headings: List[MdHeading] = []
        # 目录高亮：视口顶部 → 当前标题（缓存标题块位置，避免滚动时整篇扫描）
        self._heading_pairs: List[tuple] = []   # [(标题序号, 文档位置)]
        self._heading_cache_key: tuple = (-1, -1, -1)
        self._heading_index: int = -2        # -2 = 本次渲染还没发过信号
        self._heading_timer = QTimer(self)
        self._heading_timer.setSingleShot(True)
        self._heading_timer.setInterval(0)
        self._heading_timer.timeout.connect(self._emit_current_heading)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self._heading_timer.start())
        self._hits: List[MdSearchHit] = []
        self._hit_index: int = -1
        self._mode: str = "render"          # render / source
        self._zoom: float = 1.0
        self._reading_bg: str = ""
        self._colors: dict = {}
        self._highlight_fg = QColor("#c96442")
        self._highlight_bg = QColor("#f2e4da")
        self._hit_text = QColor("#ffffff")
        self._hit_alt_text = QColor("#2b2a26")
        self._style_colors: dict = {}
        self._code_fonts: list = []

        # ---- PageCanvas 兼容桩（见模块说明） ----
        self.scale = 1.0
        self.current_index = 0
        self.total_pages = 1
        self.read_mode = "single"
        self.rotation = 0
        self.undo_mgr = None
        self.tool = None
        # 工具栏状态栏会读当前标签的笔样式；Markdown 只读，给个无害默认值即可
        self.pen_color = "#000000"
        self.highlighter_color = "#ffff00"
        self.stroke_provider = None
        self.on_page_request = None
        self._render_cache = None
        self.canvas_bg = ""

        # 公式对象：注册一次，之后 setMarkdown 重建文档时仍然有效
        self._math = MathObjectHandler()
        self.document().documentLayout().registerHandler(MATH_OBJECT_TYPE,
                                                         self._math)

        self._edge_drag = ""
        self._edge_hot = ""
        self._drag_start_x = 0.0
        self._drag_start_width = 0
        self._drag_scroll_frac = 0.0
        self._overlay = _BoundaryOverlay(self)
        self._overlay.setGeometry(self.rect())
        self._apply_stylesheet({})
        self.viewport().installEventFilter(self)
        self.viewport().setMouseTracking(True)
        self.setMouseTracking(True)
        self._sync_overlay()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._sync_reading_column()

    def set_reading_width(self, width: int) -> None:
        """设置正文宽度（px）；0 = 自动铺满，正数夹在 520–20000。"""
        width = int(width)
        width = 0 if width <= 0 else max(520, min(20000, width))
        if width == self._column_width:
            return
        # 重新折行会让滚动条范围变化；按比例恢复，避免阅读位置跳走
        frac = self.scroll_offset_frac() if self._text else 0.0
        self._column_width = width
        self._sync_reading_column()
        if frac > 0.0 and not self._edge_drag:
            self.restore_scroll_frac(frac)

    def _max_reading_width(self) -> int:
        """当前窗口能容纳的最大正文宽度。"""
        sb = self.verticalScrollBar().sizeHint().width()
        return max(1, self.width() - sb)

    def _effective_reading_width(self) -> int:
        maximum = self._max_reading_width()
        if self._column_width <= 0 or self._column_width >= maximum:
            return maximum
        return self._column_width

    def _sync_reading_column(self) -> None:
        """用 viewport margins 居中正文，而不是反复改 QSS padding。

        margins 只改变实际视口，不再触发全局样式重算；宽度拖动时只重排文本。
        最大宽度由当前窗口动态决定，所以 1099 → 1100 这种边界不会跳变。
        """
        avail = self._max_reading_width()
        width = self._effective_reading_width()
        pad = max(0, (avail - width) // 2)
        if pad != self._gutter:
            self._gutter = pad
            self.setViewportMargins(pad, 0, pad, 0)
        if avail != self._max_column_width:
            self._max_column_width = avail
            self.reading_width_max_changed.emit(avail)
        self._apply_text_width()
        self._column_timer.start(0)    # 布局稳定后再按真实视口对一次

    def _apply_text_width(self) -> None:
        """文档宽度跟随实际视口（margins / 滚动条变化不会自动重排）。"""
        self.document().setTextWidth(max(1, self.viewport().width()))
        self._sync_overlay()

    def _edge_positions(self):
        """返回正文阅读区在 MarkdownView 坐标里的左右边界。"""
        vp = self.viewport()
        origin = vp.mapTo(self, QPoint(0, 0))
        return origin.x(), origin.x() + max(1, vp.width())

    def _sync_overlay(self) -> None:
        if not hasattr(self, "_overlay"):
            return
        self._overlay.setGeometry(self.rect())
        show = bool(self._text)
        self._overlay.setVisible(show)
        if show:
            self._overlay.raise_()
        self._overlay.update()

    def _edge_at(self, global_x: float) -> str:
        if not self._text:
            return ""
        pos = self.mapFromGlobal(QPoint(int(round(global_x)), 0)).x()
        if pos < 0 or pos > self.width():
            return ""
        left, right = self._edge_positions()
        if pos <= left + _EDGE_HIT:
            return "left"
        if pos >= right - _EDGE_HIT:
            return "right"
        return ""

    def _set_edge_state(self, side: str, from_viewport: bool) -> None:
        if side != self._edge_hot:
            self._edge_hot = side
            self._overlay.update()
        target = self.viewport() if from_viewport else self
        if side:
            target.setCursor(Qt.CursorShape.SplitHCursor)
        elif from_viewport:
            target.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            target.setCursor(Qt.CursorShape.ArrowCursor)

    def _start_edge_drag(self, side: str, global_x: float) -> None:
        self._edge_drag = side
        self._edge_hot = side
        self._drag_start_x = float(global_x)
        self._drag_start_width = self._effective_reading_width()
        self._drag_scroll_frac = self.scroll_offset_frac()
        self._overlay.update()
        self.viewport().setCursor(Qt.CursorShape.SplitHCursor)

    def _move_edge_drag(self, global_x: float) -> None:
        if not self._edge_drag:
            return
        delta = float(global_x) - self._drag_start_x
        # 两侧对称：左边界右拖 / 右边界左拖都会缩小正文
        width = self._drag_start_width - 2 * delta
        if self._edge_drag == "right":
            width = self._drag_start_width + 2 * delta
        width = int(round(width))
        if width >= self._max_reading_width():
            width = 0                 # 拖回最外沿 = 自动铺满
        self.set_reading_width(width)

    def _end_edge_drag(self) -> None:
        if not self._edge_drag:
            return
        self._edge_drag = ""
        self._overlay.update()
        if self._drag_scroll_frac > 0.0:
            self.restore_scroll_frac(self._drag_scroll_frac)
            self._drag_scroll_frac = 0.0
        self.reading_width_changed.emit(self._column_width)

    def _reset_reading_width(self) -> None:
        self.set_reading_width(0)
        self.reading_width_changed.emit(self._column_width)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport():
            etype = event.type()
            if etype == QEvent.Type.Resize:
                self._apply_text_width()
            elif etype == QEvent.Type.MouseMove:
                gx = event.globalPosition().x()
                if self._edge_drag:
                    self._move_edge_drag(gx)
                    return True
                side = self._edge_at(gx)
                self._set_edge_state(side, True)
            elif etype == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    side = self._edge_at(event.globalPosition().x())
                    if side:
                        self._start_edge_drag(side, event.globalPosition().x())
                        event.accept()
                        return True
            elif etype == QEvent.Type.MouseButtonRelease:
                if self._edge_drag and event.button() == Qt.MouseButton.LeftButton:
                    self._end_edge_drag()
                    event.accept()
                    return True
            elif etype == QEvent.Type.MouseButtonDblClick:
                if self._edge_at(event.globalPosition().x()):
                    self._reset_reading_width()
                    event.accept()
                    return True
            elif etype == QEvent.Type.Leave and not self._edge_drag:
                self._set_edge_state("", True)
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, e) -> None:
        if self._edge_drag:
            self._move_edge_drag(e.globalPosition().x())
            e.accept()
            return
        self._set_edge_state(self._edge_at(e.globalPosition().x()), False)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            side = self._edge_at(e.globalPosition().x())
            if side:
                self._start_edge_drag(side, e.globalPosition().x())
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self._edge_drag and e.button() == Qt.MouseButton.LeftButton:
            self._end_edge_drag()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        if self._edge_at(e.globalPosition().x()):
            self._reset_reading_width()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def leaveEvent(self, e) -> None:
        if not self._edge_drag:
            self._set_edge_state("", False)
        super().leaveEvent(e)

    def _on_vscroll_range(self, _min: int, _max: int) -> None:
        if abs(self.document().textWidth() - self.viewport().width()) > 0.5:
            self._apply_text_width()

    # ------------------------------------------------------------------ #
    # 文档装载 / 模式
    # ------------------------------------------------------------------ #
    def set_markdown(self, text: str, path: str = "") -> None:
        self._text = text or ""
        self._masked, self._segments = mask_math(self._text)
        self._masked = self._prepare_markdown(self._masked)
        self._path = path or ""
        self._headings = parse_headings(self._text)
        self._heading_index = -2
        self._heading_cache_key = (-1, -1)
        self._hits = []
        self._hit_index = -1
        if self._path:
            folder = os.path.dirname(os.path.abspath(self._path))
            self.setSearchPaths([folder])
            self.document().setMetaInformation(
                QTextDocument.MetaInformation.DocumentUrl,
                QUrl.fromLocalFile(os.path.abspath(self._path)).toString())
        self._rerender(keep_frac=False)

    def source_text(self) -> str:
        return self._text

    def path(self) -> str:
        return self._path

    def headings(self) -> List[MdHeading]:
        return list(self._headings)

    def view_mode(self) -> str:
        return self._mode

    def set_view_mode(self, mode: str) -> None:
        mode = "source" if mode == "source" else "render"
        if mode != self._mode:
            self._mode = mode
            self._rerender()

    def _rerender(self, keep_frac: bool = True) -> None:
        frac = self.scroll_offset_frac() if keep_frac else 0.0
        self._rerender_content()
        if frac > 0.0:
            QTimer.singleShot(0, lambda f=frac: self.restore_scroll_frac(f))

    def _rerender_content(self) -> None:
        if self._mode == "source":
            self._code_fonts = []
            self.setFont(self._base_font)
            self.setPlainText(self._text)
            cur = QTextCursor(self.document())
            cur.select(QTextCursor.SelectionType.Document)
            fmt = QTextCharFormat()
            fmt.setFontFamilies(["Cascadia Mono", "Consolas",
                                 "Microsoft YaHei Mono", "Courier New", "monospace"])
            fmt.setFontPointSize(10.0 + (self._zoom - 1.0) * 10.0)
            cur.mergeCharFormat(fmt)
        else:
            self.setFont(self._base_font)
            self.setMarkdown(self._masked or self._text)
            self._apply_zoom_step()
            self._fix_unparsed_bold()
            self._remove_markdown_markers()
            self._embed_math()
            self._restyle_document()
            self._collect_code_fonts()
            self._apply_code_zoom()
        self.setExtraSelections([])
        self._apply_text_width()          # setMarkdown 会把文档宽度重置回控件宽度
        self._apply_hits_highlight()
        self._heading_timer.start()       # 重排后视口顶部所在的标题可能变了

    # ------------------------------------------------------------------ #
    # 主题 / 缩放
    # ------------------------------------------------------------------ #
    def apply_theme(self, colors: dict) -> None:
        """由主窗口下发 ThemeManager.colors()。

        换主题只换配色：不重新解析 Markdown、不重排公式，滚动位置也完全不动。
        （旧实现每次切主题都重新 _rerender() 一遍，长文档要等好几秒。）
        """
        self._apply_stylesheet(colors or {})
        if self._text and self._mode == "render":
            self._restyle_document()
            self._apply_hits_highlight()

    def set_canvas_bg(self, color: str) -> None:
        """`_apply_theme` 对所有标签统一调用；Markdown 的配色走 apply_theme。"""
        self.canvas_bg = color

    def set_reading_bg(self, color: str) -> None:
        """设置 Markdown 阅读底色；传空字符串恢复「跟随主题」。"""
        col = QColor(color) if color else QColor()
        self._reading_bg = col.name() if col.isValid() else ""
        self._apply_stylesheet(self._colors)
        self._restyle_document()
        self._apply_hits_highlight()      # 搜索命中前景色按新底色重算

    def _restyle_document(self) -> None:
        """把主题配色写进 Markdown 导入后的文档格式。

        Qt 的 Markdown 导入器不读 QTextDocument.defaultStyleSheet：链接固定是
        系统蓝、代码块没有底色、引用没有灰字、表格没有边框。换深色纸时这些都会
        变得不可读，所以在文档生成后统一刷一遍。
        """
        if self._mode != "render" or not self._text or not self._style_colors:
            return
        c = self._style_colors
        muted, border = c["muted"], c["border"]
        hover, accent = c["hover"], c["accent"]
        doc = self.document()
        char_ops = []
        block_ops = []
        block = doc.begin()
        while block.isValid():
            bf = block.blockFormat()
            level = bf.headingLevel()
            quote = bool(bf.property(QTextFormat.Property.BlockQuoteLevel))
            # 首次导入时用 nonBreakableLines 识别代码块；之后已经被我们改成
            # 可换行（否则缩放后代码行会被右侧裁掉），改用块底色识别。
            code_block = (bf.nonBreakableLines()
                          or bf.background().style() != Qt.BrushStyle.NoBrush)
            list_item = block.textList() is not None
            has_object = False
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if frag.length() > 0 and fmt.objectType() == 0:
                    new = QTextCharFormat(fmt)
                    changed = False
                    if fmt.isAnchor():
                        new.setForeground(QColor(accent))
                        changed = True
                    elif quote:
                        new.setForeground(QColor(muted))
                        changed = True
                    mono = (fmt.fontFixedPitch()
                            or "Courier New" in fmt.font().families())
                    if level and not mono:
                        # 标题用衬线体（拉丁 Georgia，中文回退雅黑），更像 Claude 的排版
                        hf = QFont(fmt.font())
                        hf.setFamilies(["Georgia", "Microsoft YaHei UI", "Segoe UI"])
                        hf.setBold(True)
                        if self._zoom <= 1.0:
                            hf.setHintingPreference(
                                QFont.HintingPreference.PreferFullHinting)
                        new.setFont(hf)
                        changed = True
                    if not code_block and mono:
                        new.setBackground(QBrush(QColor(hover)))
                        changed = True
                    if changed:
                        char_ops.append((frag.position(), frag.length(), new))
                elif fmt.objectType():
                    has_object = True
                it += 1

            nb = QTextBlockFormat(bf)
            if code_block:
                nb.setBackground(QBrush(QColor(hover)))
                # 阅读视图没有横向滚动条：代码行必须跟随阅读栏换行，
                # 否则字号放大后右侧内容会被直接裁掉。
                nb.setNonBreakableLines(False)
                nb.setTopMargin(5.0)
                nb.setBottomMargin(5.0)
                nb.setLeftMargin(12.0)
                nb.setRightMargin(12.0)
                line_h = 150.0
            elif level:
                nb.setTopMargin(18.0 if level == 1 else 12.0)
                nb.setBottomMargin(8.0 if level == 1 else 5.0)
                line_h = 135.0
            elif quote:
                nb.setLeftMargin(22.0)
                nb.setTopMargin(2.0)
                nb.setBottomMargin(8.0)
                line_h = 165.0
            else:
                nb.setTopMargin(0.0)
                nb.setBottomMargin(2.0 if list_item else 9.0)
                line_h = 150.0 if list_item else 160.0
            if not has_object:      # 行内公式比行高时，别让固定行高裁掉它
                nb.setLineHeight(
                    line_h,
                    QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            block_ops.append((block.position(), nb))
            block = block.next()

        for pos, length, fmt in char_ops:
            cur = QTextCursor(doc)
            cur.setPosition(pos)
            cur.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            cur.mergeCharFormat(fmt)
        for pos, bf in block_ops:
            cur = QTextCursor(doc)
            cur.setPosition(pos)
            cur.setBlockFormat(bf)
        for frame in doc.rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                tf = QTextTableFormat(frame.format())
                tf.setBorder(1.0)
                tf.setBorderBrush(QBrush(QColor(border)))
                tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
                tf.setCellPadding(6)
                frame.setFormat(tf)

    def _apply_stylesheet(self, colors: dict) -> None:
        c = colors or {}
        theme_bg = c.get("card") or "#ffffff"
        bg = self._reading_bg or theme_bg
        # 用户选的底色和主题明暗相反时（浅色主题配夜黑纸），文字要跟着反过来，
        # 否则黑字黑底看不见；同明暗则沿用主题配色。
        if self._reading_bg and is_dark(bg) != is_dark(theme_bg):
            if is_dark(bg):
                fg, muted = "#f2eee4", "#aaa396"
                border, hover = "#3a3832", "#302e29"
                accent, highlight = "#d97757", "#3b2c25"
            else:
                fg, muted = "#2b2a26", "#736e64"
                border, hover = "#e4dfd3", "#ece7db"
                accent, highlight = "#c96442", "#f2e4da"
        else:
            fg = c.get("text") or "#2b2a26"
            muted = c.get("text_secondary") or "#736e64"
            border = c.get("border") or "#e4dfd3"
            hover = c.get("hover") or "#ece7db"
            accent = c.get("accent") or "#c96442"
            highlight = c.get("highlight") or "#f2e4da"
        self._colors = dict(c)
        self._highlight_fg = QColor(accent)
        self._highlight_bg = QColor(highlight)
        self._hit_text = QColor(ink_contrast_color(accent))
        self._hit_alt_text = QColor(ink_contrast_color(highlight))
        self._math.fg = QColor(fg)
        self._style_colors = {"fg": fg, "muted": muted, "border": border,
                              "hover": hover, "accent": accent,
                              "highlight": highlight}
        # 注意：QTextDocument.setDefaultStyleSheet 只对 HTML 导入生效，Markdown
        # 导入器不读 CSS。代码块 / 引用 / 链接 / 表格的配色在 _restyle_document()
        # 里直接写进文档格式。
        self.setStyleSheet(
            f"QTextBrowser {{ background-color: {bg}; color: {fg}; border: none; "
            f"font-size: 15px; padding: 24px 0; "
            f"selection-background-color: {highlight}; "
            f"selection-color: {ink_contrast_color(highlight)}; }}")
        if hasattr(self, "_overlay"):
            self._overlay.update()

    def _embed_math(self) -> None:
        """把占位符换成真正的公式对象（Qt 负责排版，绘制由 MathObjectHandler 做）。"""
        if not self._segments or self._mode != "render":
            return
        doc = self.document()
        pos = 0
        for seg in self._segments:
            found = doc.find(seg.token, pos)
            if found.isNull():
                continue
            start = found.selectionStart()
            block = doc.findBlock(start)
            alone = block.text().strip() == seg.token
            cur = QTextCursor(doc)
            cur.setPosition(start)
            cur.setPosition(start + len(seg.token),
                            QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat(cur.charFormat())
            cur.removeSelectedText()
            fmt.setObjectType(MATH_OBJECT_TYPE)
            fmt.setVerticalAlignment(
                QTextCharFormat.VerticalAlignment.AlignNormal)
            fmt.setProperty(SOURCE_PROP, seg.source)
            fmt.setProperty(DISPLAY_PROP, bool(seg.display and alone))
            cur.insertText("￼", fmt)
            pos = start + 1
            if seg.display and alone:
                bf = doc.findBlock(start).blockFormat()
                bf.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                QTextCursor(doc.findBlock(start)).setBlockFormat(bf)

    def _collect_code_fonts(self) -> None:
        """记下代码片段在 100% 时的字体。

        Markdown 导入器把代码的等宽字体字号写成了显式格式（不随文档默认字体
        变化），所以缩放时要单独按比例改一遍。
        """
        self._code_fonts = []
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            bf = block.blockFormat()
            code_block = (bf.nonBreakableLines()
                          or bf.background().style() != Qt.BrushStyle.NoBrush)
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if frag.length() > 0 and fmt.objectType() == 0:
                    if code_block or fmt.fontFixedPitch() or \
                            "Courier New" in fmt.font().families():
                        self._code_fonts.append(
                            (frag.position(), frag.length(), QFont(fmt.font())))
                it += 1
            block = block.next()

    def _apply_code_zoom(self) -> None:
        if not self._code_fonts:
            return
        doc = self.document()
        # 基准取「文档当前默认字体」：它就是正文此刻的字号（已含缩放），
        # 避免导入时视图还没被主题 QSS polish 造成的 9pt / 13px 两套基准。
        body = QFont(self.document().defaultFont())
        body_px = body.pixelSize()
        body_pt = body.pointSizeF()
        for pos, length, base in self._code_fonts:
            f = QFont(base)
            if body_px > 0:
                f.setPixelSize(max(1, body_px))
            else:
                f.setPointSizeF(max(1.0, body_pt))
            fmt = QTextCharFormat()
            fmt.setFont(f)
            cur = QTextCursor(doc)
            cur.setPosition(pos)
            cur.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            cur.mergeCharFormat(fmt)
        # Qt 6.11：含表格的长文档里，mergeCharFormat 走增量重排时会把一批后续
        # block 的 QTextLayout 清空却不再重建（高度 0、文字不绘制，放大后尤其明显）。
        # 只有“代码 + 表格”会触发，普通文档不必付整篇重排的开销。
        if any(isinstance(f, QTextTable) for f in doc.rootFrame().childFrames()):
            doc.markContentsDirty(0, doc.characterCount())

    def _apply_zoom_step(self) -> None:
        """把累计缩放写进文档默认字体。

        不能再用 QTextEdit.zoomIn：主题 QSS 给 QWidget 设了 px 字号，控件字体是
        像素模式（pointSizeF == -1），zoomIn 对像素字体不起作用。
        标题字号是相对默认字体的，跟着一起放大。
        """
        f = QFont(self.font())
        if f.pixelSize() > 0:
            f.setPixelSize(max(1, int(round(f.pixelSize() * self._zoom))))
        else:
            f.setPointSizeF(max(1.0, f.pointSizeF() * self._zoom))
        if self._zoom <= 1.0:
            # 100% 及以下开启完整 hinting，笔画边缘更实，减少灰糊感。
            f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        self.document().setDefaultFont(f)

    def zoom_to(self, factor: float) -> None:
        new_zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * float(factor)))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        # 用「视口第一行在文档里的位置」做锚点：字号变化后滚动条范围会先变大
        # 再收缩，按百分比恢复会越缩越偏。
        anchor = self.cursorForPosition(QPoint(1, 1)).position()
        self._zoom = new_zoom
        self.scale = new_zoom
        if self._mode == "source":
            # 源码视图的字号写在字符格式里，重建一次才会生效
            self._rerender_content()
        else:
            self._apply_zoom_step()
            self._apply_code_zoom()
        self.zoom_changed.emit(new_zoom)
        QTimer.singleShot(0, lambda p=anchor: self._restore_anchor(p))

    def _restore_anchor(self, pos: int) -> None:
        """把文档位置 pos 所在行贴回视口顶部，再等一帧校正。

        Qt 缩放后先给一个临时的滚动范围、随后收缩，单次 singleShot 往往太早。
        """
        def _once() -> None:
            doc = self.document()
            if doc.characterCount() <= 0:
                return
            cur = QTextCursor(doc)
            cur.setPosition(max(0, min(int(pos), doc.characterCount() - 1)))
            rect = self.cursorRect(cur)
            sb = self.verticalScrollBar()
            target = sb.value() + int(round(rect.top() - 1))
            sb.setValue(max(sb.minimum(), min(sb.maximum(), target)))
        _once()
        QTimer.singleShot(0, _once)

    def wheelEvent(self, e) -> None:
        """Ctrl+滚轮缩放（QTextBrowser 默认不处理，与画布保持同一手感）。"""
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y() or e.pixelDelta().y()
            if dy:
                self.zoom_to(1.1 if dy > 0 else 1.0 / 1.1)
                e.accept()
                return
        super().wheelEvent(e)

    def actual_size(self) -> None:
        self.zoom_to(1.0 / self._zoom if self._zoom else 1.0)

    # ------------------------------------------------------------------ #
    # Markdown 导入修补：引用后紧跟表格会丢第一个表头单元格（Qt 导入器 bug）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_table_delimiter(line: str) -> bool:
        st = line.strip()
        return bool(st) and "|" in st and "---" in st and set(st) <= set("|-: " + chr(9))

    def _prepare_markdown(self, text: str) -> str:
        nl = chr(10)
        zw = chr(0x200B)
        lines = text.splitlines(keepends=True)
        out = []
        fence = ""
        for i, line in enumerate(lines):
            st = line.strip()
            if fence:
                out.append(line)
                if st.startswith(fence):
                    fence = ""
                continue
            if st.startswith("```") or st.startswith("~~~"):
                fence = st[:3]
                out.append(line)
                continue
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if (nxt and self._is_table_delimiter(nxt)
                    and not st.startswith(">")):
                j = len(out) - 1
                while j >= 0 and not out[j].strip():
                    j -= 1
                if j >= 0 and out[j].lstrip().startswith(">"):
                    if out and not out[-1].endswith(nl):
                        out[-1] += nl
                    # 零宽段落：让 Qt 的表格解析器与引用块断开，导入后再删掉
                    out.append(zw + nl + nl)
            out.append(line)
        return "".join(out)

    def _remove_markdown_markers(self) -> None:
        zw = chr(0x200B)
        doc = self.document()
        while True:
            pos = -1
            block = doc.begin()
            while block.isValid():
                if block.text() == zw:
                    pos = block.position()
                    break
                block = block.next()
            if pos < 0:
                return
            cur = QTextCursor(doc)
            cur.setPosition(pos)
            cur.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
            cur.setPosition(pos)
            if pos > 0:
                cur.deletePreviousChar()      # 合并掉空的标记段落

    # ------------------------------------------------------------------ #
    # Markdown 导入修补：中文标点紧挨 ** 时 Qt 不识别粗体
    # ------------------------------------------------------------------ #
    def _fix_unparsed_bold(self) -> None:
        """补上 Qt Markdown 导入器漏掉的 ``**粗体**``。

        按 CommonMark 的 flanking 规则，``**……。**后面`` 的收尾标记右侧是汉字、
        左侧是标点，不算 right-flanking，于是原文里的 ``**`` 被当普通字符留下。
        中文写作里这种写法非常常见，所以导入后把残留的成对 ``**`` 收掉并加粗。
        """
        doc = self.document()
        blocks = []
        block = doc.begin()
        while block.isValid():
            if "**" in block.text() and not block.blockFormat().nonBreakableLines():
                blocks.append(block.position())
            block = block.next()
        for pos in reversed(blocks):
            block = doc.findBlock(pos)
            text = block.text()
            # 行内代码里的 ** 是内容，不能当粗体标记
            fixed = []
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.fontFixedPitch() or "Courier New" in fmt.font().families():
                    fixed.append((frag.position() - pos,
                                  frag.position() - pos + frag.length()))
                it += 1

            def in_code(offset: int) -> bool:
                return any(a <= offset < b for a, b in fixed)

            marks = []
            start = text.find("**")
            while start >= 0:
                if not in_code(start) and not _escaped_markdown(text, start):
                    marks.append(start)
                start = text.find("**", start + 2)
            pairs = []
            i = 0
            while i + 1 < len(marks):
                open_off, close_off = marks[i], marks[i + 1]
                if close_off > open_off + 2:
                    pairs.append((open_off, close_off))
                    i += 2
                else:
                    i += 1

            for open_off, close_off in reversed(pairs):
                open_pos = pos + open_off
                close_pos = pos + close_off
                cur = QTextCursor(doc)
                cur.setPosition(close_pos)
                cur.setPosition(close_pos + 2, QTextCursor.MoveMode.KeepAnchor)
                cur.removeSelectedText()
                fmt = QTextCharFormat()
                fmt.setFontWeight(QFont.Weight.Bold)
                cur.setPosition(open_pos + 2)
                cur.setPosition(close_pos, QTextCursor.MoveMode.KeepAnchor)
                cur.mergeCharFormat(fmt)
                cur.setPosition(open_pos)
                cur.setPosition(open_pos + 2, QTextCursor.MoveMode.KeepAnchor)
                cur.removeSelectedText()

    # ------------------------------------------------------------------ #
    # 复制：公式对象还原成 LaTeX 源码
    # ------------------------------------------------------------------ #
    def createMimeDataFromSelection(self):  # noqa: N802 - Qt 虚函数
        cur = self.textCursor()
        if cur.hasSelection() and "\ufffc" in cur.selectedText():
            # 新建一份 MimeData：直接改 super() 返回的对象在 PySide 里会被丢掉
            data = QMimeData()
            data.setText(self._selection_text_with_formulas(cur))
            return data
        return super().createMimeDataFromSelection()

    def _selection_text_with_formulas(self, cur: QTextCursor) -> str:
        doc = self.document()
        start, end = cur.selectionStart(), cur.selectionEnd()
        out = []
        i = start
        while i < end:
            ch = doc.characterAt(i)
            if ch == "\ufffc":
                cc = QTextCursor(doc)
                cc.setPosition(i)
                cc.setPosition(i + 1, QTextCursor.MoveMode.KeepAnchor)
                fmt = cc.charFormat()
                src = fmt.property(SOURCE_PROP)
                if isinstance(src, str) and src:
                    delim = "$$" if fmt.property(DISPLAY_PROP) else "$"
                    out.append(delim + src + delim)
                else:
                    out.append(ch)
            elif ch == "\u2029":
                out.append("\n")
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    # ------------------------------------------------------------------ #
    # 滚动位置（阅读进度）
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # 当前标题（Markdown 目录高亮）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _heading_pattern(title: str) -> str:
        """目录标题 → 渲染文本模式：把每个公式压成一个对象字符。"""
        _masked, segs = mask_math(title)
        if not segs:
            return title.strip()
        out: List[str] = []
        pos = 0
        for seg in segs:
            out.append(title[pos:seg.start])
            out.append("\ufffc")
            pos = seg.end
        out.append(title[pos:])
        return "".join(out).strip()

    @staticmethod
    def _rendered_heading_text(text: str) -> str:
        text = text.replace("\u200b", "").strip()
        return re.sub("\ue000\\d+\ue001", "\ufffc", text)

    def _heading_layout(self) -> List[tuple]:
        """[(目录序号, 标题块位置)]：按层级 + 文本对齐。

        Qt 会把引用块里的 `> # 标题` 也渲染成 heading 块，而 parse_headings
        不把它算目录项；直接按块序号取会整体错位。这里逐块对齐，匹配不上
        的额外 heading 块（引用里的伪标题）跳过。
        """
        doc = self.document()
        key = (doc.characterCount(), doc.blockCount(), len(self._headings))
        if key != self._heading_cache_key:
            patterns = [(h.level, self._heading_pattern(h.title))
                        for h in self._headings]
            pairs: List[tuple] = []
            hidx = 0
            b = doc.begin()
            while b.isValid() and hidx < len(patterns):
                level = b.blockFormat().headingLevel()
                if level > 0:
                    text = self._rendered_heading_text(b.text())
                    # 允许跳过 1–2 个被 Qt 丢掉的标题（极少见），
                    # 但不会为了匹配跨过大量标题。
                    for skip in range(3):
                        j = hidx + skip
                        if j < len(patterns) and patterns[j] == (level, text):
                            pairs.append((j, b.position()))
                            hidx = j + 1
                            break
                b = b.next()
            self._heading_pairs = pairs
            self._heading_cache_key = key
        return self._heading_pairs

    def _heading_block_positions(self) -> List[int]:
        """目录标题对应块的位置（按文档顺序；不含引用里的伪标题）。"""
        return [pos for _idx, pos in self._heading_layout()]

    def current_heading_index(self) -> int:
        """视口顶部所在的标题序号；在第一个标题之前返回 -1。"""
        if self._mode != "render" or not self._headings:
            return -1
        pairs = self._heading_layout()
        if not pairs:
            return -1
        positions = [pos for _idx, pos in pairs]
        top = self.cursorForPosition(QPoint(2, 2)).position()
        slot = bisect.bisect_right(positions, top) - 1
        sb = self.verticalScrollBar()
        if sb.value() >= sb.maximum() - 1 and sb.maximum() > sb.minimum():
            # 贴底时最后一个标题无法滚到视口顶部（后面没有内容了），
            # 只按顶部算会永远高亮倒数第二个；改为取「视口里能看到的最后一个」。
            bottom = self.cursorForPosition(
                QPoint(2, max(2, self.viewport().height() - 4))).position()
            slot = max(slot, bisect.bisect_right(positions, bottom) - 1)
        if slot < 0:
            return -1
        return pairs[min(slot, len(pairs) - 1)][0]

    def _emit_current_heading(self) -> None:
        if not self._text or self._mode != "render":
            return
        idx = self.current_heading_index()
        if idx != self._heading_index:
            self._heading_index = idx
            self.current_heading_changed.emit(idx)

    def scroll_offset_frac(self) -> float:
        sb = self.verticalScrollBar()
        rng = sb.maximum() - sb.minimum()
        if rng <= 0:
            return 0.0
        return max(0.0, min(1.0, (sb.value() - sb.minimum()) / float(rng)))

    def restore_scroll_frac(self, frac: float) -> None:
        def _do() -> None:
            sb = self.verticalScrollBar()
            rng = sb.maximum() - sb.minimum()
            if rng <= 0:
                return
            sb.setValue(int(sb.minimum() + max(0.0, min(1.0, float(frac))) * rng))
        # 文档刚装载时布局还没算完，等一拍再设，否则会被拉回顶部
        QTimer.singleShot(0, _do)

    # ------------------------------------------------------------------ #
    # 目录 / 搜索
    # ------------------------------------------------------------------ #
    def scroll_to_heading(self, index: int) -> None:
        """跳到第 index 个标题，并把标题行贴到视口顶部。

        以「标题块序号」为准，而不是在正文里找标题文字：同名标题、标题里带
        公式（渲染后文字与源码对不上）都能正确定位。定位后立即发一次
        current_heading_changed，目录高亮不会等到滚动事件才追上。
        """
        if self._mode != "render" or not (0 <= index < len(self._headings)):
            return
        doc = self.document()
        pos = next((p for i, p in self._heading_layout() if i == index), None)
        block = doc.findBlock(pos) if pos is not None else None
        if block is None or not block.isValid():
            # Qt 丢弃了某个标题块时的兜底：按原文标题文字找
            h = self._headings[index]
            nth = sum(1 for x in self._headings[:index] if x.title == h.title)
            pos = 0
            cur = QTextCursor()
            for _ in range(nth + 1):
                cur = doc.find(h.title, pos)
                if cur.isNull():
                    break
                pos = cur.selectionEnd()
            if cur.isNull():
                return
            block = doc.findBlock(cur.position())
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        self.setTextCursor(cur)
        y = doc.documentLayout().blockBoundingRect(block).top()
        sb = self.verticalScrollBar()
        sb.setValue(max(sb.minimum(), min(sb.maximum(), int(round(y)) - 2)))
        self.setFocus()
        self._heading_index = index
        self.current_heading_changed.emit(index)

    def find_all(self, query: str, case_sensitive: bool = False,
                 whole_word: bool = False, max_hits: int = 1000) -> List[MdSearchHit]:
        """在渲染后的文档里全文检索（位置准，可直接用于高亮/跳转）。"""
        q = (query or "").strip()
        if not q:
            self.clear_search()
            return []
        flags = QTextDocument.FindFlags()
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_word:
            flags |= QTextDocument.FindFlag.FindWholeWords
        doc = self.document()
        out: List[MdSearchHit] = []
        pos = 0
        total = doc.characterCount()
        while len(out) < max_hits:
            cur = doc.find(q, pos, flags)
            if cur.isNull():
                break
            start, end = cur.selectionStart(), cur.selectionEnd()
            ctx_cur = QTextCursor(doc)
            ctx_cur.setPosition(max(0, start - 24))
            # setPosition 超出 characterCount()-1 会被 Qt 整条忽略（选中区间变空），
            # 夹到「最后一个字符」的位置，别用 characterCount() 本身。
            ctx_cur.setPosition(min(max(total - 1, 0), end + 24),
                                QTextCursor.MoveMode.KeepAnchor)
            context = ctx_cur.selectedText().replace("\u2029", " ").strip()
            out.append(MdSearchHit(context=context, position=start, length=len(q)))
            pos = end
        return out

    def focus_hit(self, position: int) -> None:
        cur = QTextCursor(self.document())
        cur.setPosition(position)
        self.setTextCursor(cur)
        self.ensureCursorVisible()
        self.setFocus()

    def highlight_hits(self, hits: Sequence[MdSearchHit], current_index: int = -1) -> None:
        self._hits = list(hits or [])
        self._hit_index = current_index
        self._apply_hits_highlight()

    def _apply_hits_highlight(self) -> None:
        if not self._hits:
            self.setExtraSelections([])
            return
        doc = self.document()
        sels = []
        for i, h in enumerate(self._hits):
            cur = QTextCursor(doc)
            cur.setPosition(h.position)
            cur.setPosition(h.position + (h.length or 1),
                            QTextCursor.MoveMode.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cur
            fmt = QTextCharFormat()
            if i == self._hit_index:
                fmt.setBackground(self._highlight_fg)
                fmt.setForeground(self._hit_text)
            else:
                fmt.setBackground(self._highlight_bg)
                fmt.setForeground(self._hit_alt_text)
            sel.format = fmt
            sels.append(sel)
        self.setExtraSelections(sels)

    def clear_search(self) -> None:
        self._hits = []
        self._hit_index = -1
        self.setExtraSelections([])

    def set_search_results(self, hits, current_index: int = 0,
                           page_index: Optional[int] = None) -> None:
        """兼容 `_apply_search_highlight` 的统一调用。"""
        self.highlight_hits(hits, current_index)

    # ------------------------------------------------------------------ #
    # 链接
    # ------------------------------------------------------------------ #
    def _on_anchor(self, url: QUrl) -> None:
        if url.toString().startswith("#"):
            return  # 文档内锚点：Qt 的 Markdown 不生成对应目标，忽略
        if url.isLocalFile():
            path = url.toLocalFile()
        elif not url.scheme():
            path = url.path()
        else:
            QDesktopServices.openUrl(url)
            return
        path = os.path.abspath(path)
        if is_markdown(path) and os.path.isfile(path):
            self.open_markdown_requested.emit(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ #
    # PageCanvas 兼容桩：通用代码无差别调用，Markdown 一律无副作用
    # ------------------------------------------------------------------ #
    def detach_pdf(self, *a, **k) -> None:
        pass

    def set_pen_color(self, *a, **k) -> None:
        pass

    def set_pen_width(self, *a, **k) -> None:
        pass

    def set_eraser_width(self, *a, **k) -> None:
        pass

    def set_highlighter_color(self, *a, **k) -> None:
        pass

    def set_highlighter_width(self, *a, **k) -> None:
        pass

    def set_tool(self, *a, **k) -> None:
        pass

    def set_read_mode(self, mode: str) -> None:
        self.read_mode = "single"

    def set_page_info(self, *a, **k) -> None:
        pass

    def set_note_content(self, *a, **k) -> None:
        pass

    def set_pdf_page(self, *a, **k) -> None:
        pass

    def set_rotation(self, *a, **k) -> None:
        pass

    def set_background(self, *a, **k) -> None:
        pass

    def set_canvas_bg_color(self, *a, **k) -> None:
        pass

    def focus_page_rect(self, *a, **k) -> None:
        pass

    def zoom_at(self, *a, **k) -> None:
        pass

    def pan_by(self, *a, **k) -> None:
        pass

    def rotate_by(self, *a, **k) -> None:
        pass

    def clear_pdf_cache(self, *a, **k) -> None:
        pass

    def rebuild_pixmap(self, *a, **k) -> None:
        pass

    def reset_zoom_policy(self, *a, **k) -> None:
        pass

    def fit_to_view(self, *a, **k) -> None:
        pass

    def fit_width(self, *a, **k) -> None:
        pass

    def undo(self, *a, **k) -> None:
        pass

    def redo(self, *a, **k) -> None:
        pass

    def clear_page(self, *a, **k) -> None:
        pass

    def refresh_tools(self, *a, **k) -> None:
        pass

    def available_tools(self):
        return []

    def current_tool_id(self) -> str:
        return "pen"

    def update(self, *a, **k) -> None:
        super().update()
