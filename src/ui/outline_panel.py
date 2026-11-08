"""PDF 书签 / Markdown 标题目录侧栏。

* 用 QTreeWidget 展示多级条目（level 1 为顶层）。
* 单击条目 → PDF 跳到对应页 / Markdown 跳到对应标题。
* 翻页时高亮「当前页所在章节」：取文档顺序里最后一个起始页 ≤ 当前页的条目，
  而不是要求页码完全相等——绝大多数书签只标章节首页，等值匹配会导致
  两章之间整段没有高亮。
* Markdown 目录里的公式用与正文相同的盒模型直接绘制（QStyledItemDelegate），
  不再显示 $pK_{\\mathrm{a}}$ 这样的源码；纯文字版本留给工具提示与无障碍。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QLabel, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from src.core.markdown_document import plain_math_title
from src.core.math_formula import mask_math
from src.render.pdf_engine import OutlineEntry
from src.ui.math_render import math_box, paint_math_box

#: Markdown 条目的原始标题（含 $...$）。PDF 条目不写这个字段。
MATH_TITLE_ROLE = Qt.ItemDataRole.UserRole + 11


def _title_runs(title: str) -> List[Tuple[str, str]]:
    """把标题拆成 [(text|math, 内容)]；公式位置用 mask_math 的同一套规则。"""
    _masked, segs = mask_math(title)
    if not segs:
        return [("text", title)] if title else []
    runs: List[Tuple[str, str]] = []
    pos = 0
    for seg in segs:
        if seg.start > pos:
            runs.append(("text", title[pos:seg.start]))
        runs.append(("math", seg.source))
        pos = seg.end
    if pos < len(title):
        runs.append(("text", title[pos:]))
    return runs


class _OutlineItemDelegate(QStyledItemDelegate):
    """目录条目绘制：普通条目走默认样式，Markdown 条目把公式排成矢量字形。"""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index) -> None:
        raw = index.data(MATH_TITLE_ROLE)
        if not isinstance(raw, str) or not raw:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # 背景 / 选中 / 悬停 / QSS 圆角交给样式画，文字由我们自己排版
        opt.text = ""
        font = opt.font
        # 先把整行排好再落笔：公式排版万一失败，直接退回默认绘制，
        # 不会留下画了一半的条目。
        try:
            prepared = [(kind, value,
                         math_box(value, font) if kind == "math" else None)
                        for kind, value in _title_runs(raw)]
        except Exception:                 # pragma: no cover - 防御性
            super().paint(painter, option, index)
            return

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter,
                          opt.widget)

        color = opt.palette.color(QPalette.ColorRole.Text)
        if not (opt.state & QStyle.StateFlag.State_Enabled):
            color = opt.palette.color(QPalette.ColorRole.PlaceholderText)
        fm = QFontMetricsF(font)
        left = opt.rect.left() + 7.0
        right = opt.rect.right() - 7.0
        baseline = opt.rect.center().y() + (fm.ascent() - fm.descent()) / 2.0
        if right <= left:
            return

        painter.save()
        painter.setClipRect(opt.rect)
        x = left
        truncated = False
        for kind, value, box in prepared:
            if kind == "text":
                if not value:
                    continue
                remaining = right - x
                if remaining <= 0:
                    truncated = True
                    break
                width = fm.horizontalAdvance(value)
                if width <= remaining:
                    painter.setFont(font)
                    painter.setPen(color)
                    painter.drawText(QPointF(x, baseline), value)
                    x += width
                else:
                    elided = fm.elidedText(value, Qt.TextElideMode.ElideRight,
                                           int(remaining))
                    painter.setFont(font)
                    painter.setPen(color)
                    painter.drawText(QPointF(x, baseline), elided)
                    x = right
                    break
            else:
                if x + box.w > right:
                    if x <= left + 0.5:
                        # 整行只有一条比面板还宽的公式：退回纯文字，
                        # 至少让用户看到标题说的是什么。
                        fallback = index.data(Qt.ItemDataRole.DisplayRole) or ""
                        elided = fm.elidedText(fallback,
                                               Qt.TextElideMode.ElideRight,
                                               int(right - left))
                        painter.setFont(font)
                        painter.setPen(color)
                        painter.drawText(QPointF(left, baseline), elided)
                    else:
                        truncated = True
                    break
                paint_math_box(painter, box, x, baseline, color)
                x += box.w + 2.0
        if truncated:
            ell = "…"
            width = fm.horizontalAdvance(ell)
            if right - width > left:
                painter.setFont(font)
                painter.setPen(color)
                painter.drawText(QPointF(right - width, baseline), ell)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        base = super().sizeHint(option, index)
        if index.data(MATH_TITLE_ROLE):
            fm = QFontMetricsF(option.font)
            return QSize(base.width(), max(base.height(),
                                           int(fm.height() + 10)))
        return base


class OutlinePanel(QWidget):
    """书签 / 标题目录树。"""

    page_selected = Signal(int, object)   # (page_index, top_y or None)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: List[OutlineEntry] = []
        self._items: List[QTreeWidgetItem] = []
        self._current: Optional[QTreeWidgetItem] = None
        self._math_mode = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.tip = QLabel("该 PDF 没有书签目录")
        self.tip.setObjectName("SideTitle")
        self.tip.setWordWrap(True)
        self.tip.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.tip)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.setItemDelegate(_OutlineItemDelegate(self.tree))
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemActivated.connect(self._on_clicked)
        layout.addWidget(self.tree, 1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("SideTitle")
        layout.addWidget(self.count_label)

        self.clear()

    # ------------------------------------------------------------------ #
    def clear(self) -> None:
        self._entries = []
        self._items = []
        self._current = None
        self._math_mode = False
        self.tree.clear()
        self.tree.setVisible(False)
        self.count_label.setText("")
        self.tip.setVisible(True)
        self.tip.setText("未打开 PDF")

    def set_unavailable(self, reason: str) -> None:
        self._entries = []
        self._items = []
        self._current = None
        self._math_mode = False
        self.tree.clear()
        self.tree.setVisible(False)
        self.count_label.setText("")
        self.tip.setVisible(True)
        self.tip.setText(reason)

    def set_outline(self, entries: List[OutlineEntry], noun: str = "书签",
                    show_page: bool = True, math: bool = False) -> None:
        """按 level 重建目录树；扁平列表 + level 表示层级。

        PDF 用默认参数（行为与旧版逐字一致）；Markdown 标题大纲传
        `noun="标题", show_page=False, math=True`：条目文字用公式的纯文字
        降级版，真正的公式由 delegate 画；`top` 借来存「第几个标题」。
        """
        self._entries = list(entries or [])
        self._items = []
        self._current = None
        self._math_mode = bool(math)
        self.tree.clear()
        if not self._entries:
            self.tree.setVisible(False)
            self.count_label.setText("")
            self.tip.setVisible(True)
            self.tip.setText(
                "该 PDF 没有书签目录\n（可用左侧「页面」标签浏览）" if show_page
                else f"该文档没有{noun}\n（可用「搜索」查找内容）")
            return

        self.tip.setVisible(False)
        self.tree.setVisible(True)
        # 扁平列表 + level 还原为树：stack[k] 存放「第 k+1 层」的最后一个节点
        stack: List[QTreeWidgetItem] = []
        for e in self._entries:
            level = max(1, int(e.level))
            parent = stack[level - 2] if (level >= 2 and len(stack) >= level - 1) else None
            label = plain_math_title(e.display) if math else e.display
            item = QTreeWidgetItem(parent if parent is not None else self.tree,
                                   [label])
            item.setData(0, Qt.UserRole, (e.page, e.top))
            if math:
                item.setData(0, MATH_TITLE_ROLE, e.display)
                item.setToolTip(0, label)
            else:
                item.setToolTip(
                    0, f"{e.display}  →  第 {e.page + 1} 页" if show_page else e.display)
            item.setExpanded(level == 1)
            self._items.append(item)
            del stack[level - 1:]
            stack.append(item)
        self.count_label.setText(f"共 {len(self._entries)} 个{noun}")

    # ------------------------------------------------------------------ #
    def current_item(self) -> Optional[QTreeWidgetItem]:
        """当前高亮条目（点击跳转后要用它恢复「点的就是它」）。"""
        return self._current

    def highlight_item(self, item: Optional[QTreeWidgetItem]) -> None:
        self._highlight(item)

    def set_current_page(self, index: int, follow: bool = True) -> None:
        """高亮「当前页所在章节」。

        页码完全相等只是特例：书签通常只标章节首页，页与页之间必须回退到
        最近一个起始页 ≤ 当前页的条目（同页多条取文档顺序更靠后的那条）。
        页码在第一个书签之前时清除高亮，不留下上一节的假高亮。
        """
        if self._math_mode or not self._items:
            return
        best: Optional[QTreeWidgetItem] = None
        best_page = -1
        for item in self._items:
            data = item.data(0, Qt.UserRole)
            if not isinstance(data, (tuple, list)) or not data:
                continue
            try:
                page = int(data[0])
            except (TypeError, ValueError):
                continue
            if page <= index and page >= best_page:
                best, best_page = item, page
        self._highlight(best, follow)

    def set_current_heading(self, index: int, follow: bool = True) -> None:
        """高亮第 index 个标题（Markdown 按文档顺序，-1 = 第一个标题之前）。"""
        if not self._math_mode:
            return
        if 0 <= index < len(self._items):
            self._highlight(self._items[index], follow)
        elif index < 0:
            self._highlight(None, follow)

    def _highlight(self, item: Optional[QTreeWidgetItem],
                   follow: bool = True) -> None:
        if item is self._current:
            return
        self._current = item
        self.tree.blockSignals(True)
        try:
            if item is None:
                self.tree.setCurrentItem(None)
                self.tree.clearSelection()
            else:
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.setCurrentItem(item)
                if follow:
                    self.tree.scrollToItem(
                        item, QAbstractItemView.ScrollHint.EnsureVisible)
        finally:
            self.tree.blockSignals(False)

    # ------------------------------------------------------------------ #
    def _on_clicked(self, item: QTreeWidgetItem, column: int = 0) -> None:
        # 用户点的这条就是新的「当前章节」，先记下来再发跳转信号
        self._current = item
        data = item.data(0, Qt.UserRole)
        if isinstance(data, (tuple, list)) and data:
            self.page_selected.emit(int(data[0]), data[1] if len(data) > 1 else None)


def _walk_items(tree: QTreeWidget) -> List[QTreeWidgetItem]:
    """深度优先展开所有节点（保留给外部测试 / 兼容旧调用）。"""
    out: List[QTreeWidgetItem] = []
    root = tree.invisibleRootItem()

    def _collect(item: QTreeWidgetItem) -> None:
        out.append(item)
        for i in range(item.childCount()):
            _collect(item.child(i))

    for i in range(root.childCount()):
        _collect(root.child(i))
    return out
