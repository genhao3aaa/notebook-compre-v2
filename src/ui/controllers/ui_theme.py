"""主题、响应式布局与侧边栏（A7 拆分自 main_window.py）。

历史教训：这些逻辑是 v5.2 为了「窗口窄了按钮被切掉 / 最小宽度 1873px」而加的，
`_apply_responsive_layout` 与 `_clamp_to_screen` 里的阈值都有实测依据，改动前先看 README 的 v5.2 小节。
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor,
                           QGuiApplication, QKeySequence, QShortcut)
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QFileDialog,
                               QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSlider, QSpinBox, QSplitter, QStatusBar,
                               QTabBar, QTabWidget, QToolButton, QVBoxLayout,
                               QWidget)
from src.core.colors import (DEFAULT_HIGHLIGHTER_COLOR, DEFAULT_PEN_COLOR,
                             HIGHLIGHTER_ALPHA, HIGHLIGHTER_COLOR_PRESETS,
                             PEN_COLOR_PRESETS, argb_hex, blend_over,
                             ink_contrast_color, normalize_hex, parse_rgba,
                             with_alpha)
from src.core.document_tab import DocumentTab, MD, NOTE, PDF, same_path
from src.core.note_document import (BACKGROUND_TYPES, BG_BLANK, BG_COLOR_PRESETS,
                                    BG_LABELS, NoteDocument)
from src.ui.layout_constants import APP_TITLE, COORD_LABEL_MIN_W, IDLE_CACHE_PAGES, MAX_RESTORED_TABS, SIDEBAR_AUTO_HIDE_W, SIDEBAR_MAX_W, SIDEBAR_MIN_W, WINDOW_MIN_H, WINDOW_MIN_W
from src.ui.theme import THEME_LABELS
from src.ui.window_registry import live_windows




class UiThemeMixin:
    def _apply_initial_geometry(self) -> None:
        """首次启动（没有历史几何）时按屏幕可用区决定窗口大小。

        不再硬编码 1280×860：150% 缩放的 1920×1080 屏，逻辑可用宽度只有 1280，
        硬编码尺寸会直接顶到屏幕边缘、甚至被裁掉一截。这里取可用区的 86% 并居中偏上。
        """
        if self._geo_restored:
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:                       # pragma: no cover - 无屏幕的极端环境
            self.resize(WINDOW_MIN_W + 360, WINDOW_MIN_H + 280)
            return
        avail = screen.availableGeometry()
        w = max(WINDOW_MIN_W, min(1360, int(avail.width() * 0.86)))
        h = max(WINDOW_MIN_H, min(920, int(avail.height() * 0.86)))
        self.resize(w, h)
        self.move(avail.x() + (avail.width() - w) // 2,
                  avail.y() + max(0, (avail.height() - h) // 3))
    def _clamp_to_screen(self) -> None:
        """把窗口限制在当前屏幕的可用区内（宽度/高度都不超出）。"""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:                       # pragma: no cover
            return
        avail = screen.availableGeometry()
        w = max(WINDOW_MIN_W, min(self.width(), avail.width()))
        h = max(WINDOW_MIN_H, min(self.height(), avail.height()))
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
    def _on_splitter_moved(self, pos: int, index: int) -> None:
        """记住用户拖出来的侧边栏宽度（下次启动沿用）。"""
        w = self.sidebar.width()
        if SIDEBAR_MIN_W <= w <= SIDEBAR_MAX_W:
            self.settings.set_sidebar_width(w)
    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._apply_responsive_layout()
    def _apply_responsive_layout(self) -> None:
        """窗口越窄，界面越精简（浏览器式降级）。

        * 侧边栏：跨过阈值收窄时自动收起，重新变宽再恢复 —— 只在「跨越阈值」时动作，
          所以用户手动展开/折叠过的状态不会被反复覆盖；
        * 状态栏坐标：窄窗口下没什么用，先让位给页码与缩放。

        顶栏的降级由 QToolBar 自己完成（放不下的控件进 « 溢出菜单），这里不用管。
        """
        narrow = self.width() < SIDEBAR_AUTO_HIDE_W
        if narrow != self._was_narrow:
            self._was_narrow = narrow
            if narrow and self.sidebar.isVisible():
                self.sidebar.setVisible(False)
                self._sidebar_auto_hidden = True
            elif not narrow and self._sidebar_auto_hidden:
                self.sidebar.setVisible(True)
                self._sidebar_auto_hidden = False
        if getattr(self, "lbl_coord", None) is not None:
            self.lbl_coord.setVisible(self.width() >= COORD_LABEL_MIN_W)
    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self.theme.qss())
        self._refresh_icons()
        # 主题作用于「所有」标签的画布，而不只是当前那一个
        for t in self._tabs:
            if t.canvas is None:
                continue
            if t.is_md:
                # 只换配色（MarkdownView.apply_theme 不再重解析文档）
                t.canvas.apply_theme(self.theme.colors())
            else:
                t.canvas.set_canvas_bg(self.theme.canvas_bg(),
                                      self.theme.colors().get("accent"))
            t.canvas.update()
        self._refresh_tab_icons()
        if getattr(self, "thumbnails", None) is not None:
            self.thumbnails.apply_theme(self.theme.colors())
        if hasattr(self, "_refresh_recent"):
            self._refresh_recent()      # 最近文件图标按新主题颜色重画
        active = getattr(self, "_active", None)
        if active is not None and active.is_md and not self.settings.md_bg_color():
            # 跟随主题模式：切主题后色块要跟着变（否则还停在上一个主题的纸色）
            self._set_bg_swatch(self.theme.colors().get("card", "#ffffff"))
        self._refresh_theme_actions()
        self.settings.set_theme(self.theme.theme)
    def _refresh_theme_actions(self) -> None:
        for key, act in getattr(self, "_theme_actions", {}).items():
            act.setChecked(key == self.theme.theme)
    def _refresh_icons(self) -> None:
        for btn, kind in self._icon_buttons:
            if not kind:
                continue
            # 深色主题下把「月亮」换成「太阳」，提示点一下会回到浅色
            shown = "sun" if kind == "moon" and self.theme.theme == "dark" else kind
            icon = self.theme.icon(shown)
            if not icon.isNull():
                btn.setIcon(icon)
        self._sync_read_mode_ui()
    def _set_theme(self, name: str) -> None:
        if name == self.theme.theme:
            return
        self.theme.set_theme(name)
        self._apply_theme()
        self._status(f"已切换到{THEME_LABELS.get(name, name)}主题", 2000)

    def _toggle_theme(self) -> None:
        """保留旧的「一键浅/深」入口（菜单/按钮现在走 _show_theme_menu）。"""
        cur = self.theme.theme
        self._set_theme("light" if cur in ("dark", "midnight") else "dark")

    def _show_theme_menu(self) -> None:
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for key, label in THEME_LABELS.items():
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(key == self.theme.theme)
            act.triggered.connect(lambda checked=False, k=key: self._set_theme(k))
            group.addAction(act)
            menu.addAction(act)
        menu.exec(self.btn_theme.mapToGlobal(self.btn_theme.rect().bottomLeft()))
    def _toggle_sidebar(self) -> None:
        """折叠/展开侧边栏（用户手动操作）。"""
        show = not self.sidebar.isVisible()
        self.sidebar.setVisible(show)
        if show:
            # 用户自己要看的：别在下次 resize 时又被自动收起
            self._sidebar_auto_hidden = False
            self._sidebar_user_hidden = False
        else:
            self._sidebar_user_hidden = True
    def _show_bg_color_menu(self) -> None:
        menu = QMenu(self)
        if self.mode == MD:
            # Markdown 是连续富文本：只有「底色」有意义，没有网格 / 横线
            follow = QAction("跟随主题", self)
            follow.setCheckable(True)
            follow.setChecked(not self.settings.md_bg_color())
            follow.triggered.connect(lambda checked=False: self._apply_bg_color(""))
            menu.addAction(follow)
            menu.addSeparator()
            for hexc, name in BG_COLOR_PRESETS:
                act = QAction(f"■  {name}", self)
                act.setData(hexc)
                act.triggered.connect(lambda checked=False, c=hexc: self._apply_bg_color(c))
                menu.addAction(act)
            menu.addSeparator()
            custom = QAction("自定义颜色…", self)
            custom.triggered.connect(self._choose_bg_color)
            menu.addAction(custom)
            menu.exec(self.btn_bg_color.mapToGlobal(self.btn_bg_color.rect().bottomLeft()))
            return
        if self.mode != NOTE:
            self._status("背景色仅适用于手写笔记本与 Markdown 阅读（PDF 请导出后修改）", 3500)
            return
        for hexc, name in BG_COLOR_PRESETS:
            act = QAction(f"■  {name}", self)
            act.setData(hexc)
            act.triggered.connect(lambda checked=False, c=hexc: self._apply_bg_color(c))
            menu.addAction(act)
        menu.addSeparator()
        custom = QAction("自定义颜色…", self)
        custom.triggered.connect(self._choose_bg_color)
        menu.addAction(custom)
        menu.exec(self.btn_bg_color.mapToGlobal(self.btn_bg_color.rect().bottomLeft()))
    def _apply_bg_color(self, color: str) -> None:
        if self.mode == MD:
            color = normalize_hex(color) if color else ""
            self.settings.set_md_bg_color(color)
            # 底色是全局阅读偏好：其他窗口已经打开的 Markdown 标签也要立即换
            for win in live_windows(exclude=self) + [self]:
                for tab in getattr(win, "_tabs", []):
                    if tab.is_md and tab.canvas is not None:
                        tab.canvas.set_reading_bg(color)
                active = getattr(win, "_active", None)
                if active is not None and active.is_md:
                    win._set_bg_swatch(
                        color or win.theme.colors().get("card", "#ffffff"))
            self._status("Markdown 阅读底色已更新" if color
                         else "Markdown 阅读底色已恢复跟随主题", 2500)
            return
        color = normalize_hex(color)
        if self.note_doc is None:
            return
        self.note_doc.set_background_color(color)
        self.canvas.set_background(self.note_doc.background, color)
        self.settings.set_note_bg_color(color)
        self._set_bg_swatch(color)
        self.thumbnails.set_note_doc(self.note_doc)
        self.thumbnails.set_current(self.current_page)
        self.mark_dirty()
    def _choose_bg_color(self) -> None:
        if self.mode == MD:
            cur = self.settings.md_bg_color() or self.theme.colors().get("card", "#ffffff")
            color = QColorDialog.getColor(QColor(cur), self,
                                          "选择 Markdown 阅读底色")
            if color.isValid():
                self._apply_bg_color(color.name())
            return
        if self.note_doc is None:
            return
        color = QColorDialog.getColor(QColor(self.note_doc.background_color), self,
                                      "选择背景色")
        if color.isValid():
            self._apply_bg_color(color.name())
    def _set_bg_swatch(self, color: str) -> None:
        line = self.theme.colors().get("text_secondary", "#888")
        self.btn_bg_color.setStyleSheet(
            f"background-color: {color}; border: 2px solid {line}; border-radius: 7px;")
        self.btn_bg_color.setIcon(
            self.theme.svg_icon_colored("droplet", ink_contrast_color(color), 13))
        self.btn_bg_color.setIconSize(QSize(13, 13))
