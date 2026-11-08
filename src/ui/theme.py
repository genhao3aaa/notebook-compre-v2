"""主题与样式（QSS）。

提供：
- 浅色 / 深色两套主题配色；
- 统一的 QSS 样式字符串（扁平化、圆角、柔和中性色，符合现代 AI 助手桌面端风格）；
- 图标工厂：优先使用内嵌 SVG（不依赖外部图片资源），部分动作回退到 Qt 标准图标。

样式与逻辑分离：本文件只负责「外观」，组件逻辑在各自模块中。
"""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyle

# 主色调：Claude 风格的暖赤陶（terracotta），代替原来的青绿
PRIMARY = "#c96442"
PRIMARY_HOVER = "#b35636"
PRIMARY_PRESS = "#9e4a2e"

_LIGHT: Dict[str, str] = {
    "bg": "#f5f2ea",
    "card": "#fdfcf8",
    "text": "#2b2a26",
    "text_secondary": "#736e64",
    "border": "#e4dfd3",
    "sidebar": "#f0ece2",
    "canvas_bg": "#e8e3d7",
    "hover": "#ece7db",
    "press": "#e1dbcc",
    "accent": PRIMARY,
    "accent_hover": PRIMARY_HOVER,
    "accent_press": PRIMARY_PRESS,
    "accent_text": "#fffdf9",
    "disabled": "#b7b0a2",
    "highlight": "#f2e4da",
    "highlight_border": PRIMARY,
    "icon": "#4b473f",
}

_DARK: Dict[str, str] = {
    "bg": "#1f1e1b",
    "card": "#262521",
    "text": "#f2eee4",
    "text_secondary": "#aaa396",
    "border": "#3a3832",
    "sidebar": "#1a1917",
    "canvas_bg": "#141310",
    "hover": "#302e29",
    "press": "#3b3831",
    "accent": "#d97757",
    "accent_hover": "#e08a6d",
    "accent_press": "#c96442",
    "accent_text": "#fffdf9",
    "disabled": "#6b655b",
    "highlight": "#3b2c25",
    "highlight_border": "#d97757",
    "icon": "#d7d0c3",
}


_MIST: Dict[str, str] = {
    "bg": "#eef2f4",
    "card": "#ffffff",
    "text": "#22303a",
    "text_secondary": "#64757f",
    "border": "#d8e2e7",
    "sidebar": "#e6edf0",
    "canvas_bg": "#dce6ea",
    "hover": "#e3ecef",
    "press": "#d3e0e6",
    "accent": "#3f7c9e",
    "accent_hover": "#356b89",
    "accent_press": "#2b5c77",
    "accent_text": "#ffffff",
    "disabled": "#a9b7be",
    "highlight": "#dbe9f1",
    "highlight_border": "#3f7c9e",
    "icon": "#33454f",
}

_FOREST: Dict[str, str] = {
    "bg": "#eef2e8",
    "card": "#fbfdf9",
    "text": "#263226",
    "text_secondary": "#68765f",
    "border": "#d9e2d1",
    "sidebar": "#e6ecdd",
    "canvas_bg": "#dce6d2",
    "hover": "#e3ebda",
    "press": "#d4e0c9",
    "accent": "#557a4a",
    "accent_hover": "#48683f",
    "accent_press": "#3b5633",
    "accent_text": "#ffffff",
    "disabled": "#aeb8a5",
    "highlight": "#dfead6",
    "highlight_border": "#557a4a",
    "icon": "#35422f",
}

_MIDNIGHT: Dict[str, str] = {
    "bg": "#141a21",
    "card": "#1c242d",
    "text": "#e6edf3",
    "text_secondary": "#9daab6",
    "border": "#2d3944",
    "sidebar": "#10151b",
    "canvas_bg": "#0b1014",
    "hover": "#26303a",
    "press": "#303c47",
    "accent": "#7aa2c8",
    "accent_hover": "#8fb3d4",
    "accent_press": "#6690b8",
    "accent_text": "#0f151a",
    "disabled": "#5d6a75",
    "highlight": "#22374a",
    "highlight_border": "#7aa2c8",
    "icon": "#cdd8e2",
}


_CLASSIC: Dict[str, str] = {
    # 2026-10 最早提交到 git 的配色（逐值保留）
    "bg": "#f7f7f8",
    "card": "#ffffff",
    "text": "#1f2328",
    "text_secondary": "#6b7280",
    "border": "#e5e5e5",
    "sidebar": "#fbfbfb",
    "canvas_bg": "#e9eaee",
    "hover": "#eceef0",
    "press": "#e2e4e7",
    "accent": "#10a37f",
    "accent_hover": "#0e8c6e",
    "accent_press": "#0b7a5f",
    "accent_text": "#ffffff",
    "disabled": "#b8bcc2",
    "highlight": "#d7f0e8",
    "highlight_border": "#10a37f",
    "icon": "#374151",
}

_CLASSIC_DARK: Dict[str, str] = {
    # 同上，最早版本的深色配色
    "bg": "#1e1e1e",
    "card": "#2d2d2d",
    "text": "#e6e6e6",
    "text_secondary": "#9aa0a6",
    "border": "#3a3a3a",
    "sidebar": "#262626",
    "canvas_bg": "#161616",
    "hover": "#3a3a3a",
    "press": "#454545",
    "accent": "#10a37f",
    "accent_hover": "#0e8c6e",
    "accent_press": "#0b7a5f",
    "accent_text": "#ffffff",
    "disabled": "#5a5a5a",
    "highlight": "#15463b",
    "highlight_border": "#2dd4a8",
    "icon": "#d4d4d4",
}

THEMES = ("light", "dark", "mist", "forest", "midnight", "classic", "classic_dark")

#: 主题下拉菜单里的中文名（顺序即菜单顺序）
THEME_LABELS = {
    "light": "暖纸",
    "dark": "暖炭",
    "mist": "雾蓝",
    "forest": "森绿",
    "midnight": "午夜",
    "classic": "经典浅色",
    "classic_dark": "经典深色",
}

_PALETTES = {
    "light": _LIGHT,
    "dark": _DARK,
    "mist": _MIST,
    "forest": _FOREST,
    "midnight": _MIDNIGHT,
    "classic": _CLASSIC,
    "classic_dark": _CLASSIC_DARK,
}


def _palette(theme: str) -> Dict[str, str]:
    return _PALETTES.get(theme, _LIGHT)


def build_qss(theme: str) -> str:
    """根据主题生成全局 QSS 字符串（暖纸色 / 赤陶强调 / 克制的圆角与描边）。"""
    c = _palette(theme)
    return f"""
    /* ---------- 基底 ---------- */
    QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 13px;
        selection-background-color: {c['highlight']};
        selection-color: {c['text']};
    }}
    QToolTip {{
        background-color: {c['text']};
        color: {c['card']};
        border: 1px solid {c['text']};
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
    }}

    /* ---------- 顶部工具栏 ---------- */
    QWidget#TopBar {{
        background-color: {c['card']};
        border-bottom: 1px solid {c['border']};
    }}
    QToolBar#TopBar {{
        background-color: {c['card']};
        border: none;
        border-bottom: 1px solid {c['border']};
        padding: 5px 10px;
        spacing: 4px;
    }}
    QToolBar#TopBar::separator {{
        background-color: {c['border']};
        width: 1px;
        margin: 8px 8px;
    }}
    QToolBar#TopBar QToolButton#qt_toolbar_ext_button {{
        padding: 4px 7px;
        min-height: 30px;
    }}
    QWidget#TopBar QToolButton {{
        background-color: transparent;
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: 9px;
        padding: 4px 6px;
        min-height: 30px;
    }}
    QWidget#TopBar QToolButton:hover {{
        background-color: {c['hover']};
    }}
    QWidget#TopBar QToolButton:pressed {{
        background-color: {c['press']};
    }}
    QWidget#TopBar QToolButton:checked {{
        background-color: {c['highlight']};
        color: {c['accent']};
        border: 1px solid {c['highlight_border']};
    }}
    QWidget#TopBar QToolButton:disabled {{
        color: {c['disabled']};
    }}
    QWidget#TopBar QLabel {{
        color: {c['text_secondary']};
        background-color: transparent;
    }}
    QWidget#TopBar QComboBox, QWidget#TopBar QSpinBox {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 3px 8px;
        min-height: 22px;
    }}
    QWidget#TopBar QComboBox:hover, QWidget#TopBar QSpinBox:hover {{
        border-color: {c['text_secondary']};
    }}
    QWidget#TopBar QSpinBox::up-button, QWidget#TopBar QSpinBox::down-button {{
        width: 0;
        border: none;
        background: transparent;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {c['highlight']};
        selection-color: {c['text']};
        outline: none;
    }}
    QWidget#TopBar QSlider::groove:horizontal {{
        height: 4px;
        border-radius: 2px;
        background: {c['border']};
    }}
    QWidget#TopBar QSlider::handle:horizontal {{
        width: 14px; height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        background: {c['accent']};
    }}

    /* ---------- 侧边栏 ---------- */
    QWidget#Sidebar {{
        background-color: {c['sidebar']};
        border-right: 1px solid {c['border']};
    }}
    QWidget#Sidebar QLabel, QWidget#Sidebar QCheckBox {{
        background: transparent;
    }}
    QWidget#Sidebar QLabel#DocTitle {{
        color: {c['text']};
        font-size: 16px;
        font-weight: 700;
        padding: 2px 2px 4px 2px;
    }}
    QWidget#Sidebar QLabel#SideTitle {{
        color: {c['text_secondary']};
        font-size: 11px;
        font-weight: 600;
        padding: 2px 2px;
    }}
    QWidget#Sidebar QPushButton#PrimaryBtn {{
        background-color: {c['accent']};
        color: {c['accent_text']};
        border: none;
        border-radius: 9px;
        padding: 9px 10px;
        font-weight: 600;
    }}
    QWidget#Sidebar QPushButton#PrimaryBtn:hover {{
        background-color: {c['accent_hover']};
    }}
    QWidget#Sidebar QPushButton#PrimaryBtn:pressed {{
        background-color: {c['accent_press']};
    }}
    QWidget#Sidebar QListWidget {{
        background-color: transparent;
        border: none;
        border-radius: 8px;
        outline: none;
    }}
    QWidget#Sidebar QListWidget::item {{
        padding: 7px 8px;
        border-radius: 7px;
        color: {c['text']};
    }}
    QWidget#Sidebar QListWidget::item:hover {{
        background-color: {c['hover']};
    }}
    QWidget#Sidebar QListWidget::item:selected {{
        background-color: {c['highlight']};
        color: {c['text']};
    }}

    /* ---------- 文档标签栏 ---------- */
    QTabWidget#DocTabs::pane {{
        border: none;
        background-color: {c['canvas_bg']};
    }}
    QTabWidget#DocTabs > QTabBar::tab {{
        background-color: transparent;
        color: {c['text_secondary']};
        border: none;
        border-top: 2px solid transparent;
        padding: 7px 12px;
        margin-right: 4px;
        border-radius: 9px 9px 0 0;
        min-width: 76px;
        max-width: 190px;
        min-height: 18px;
    }}
    QTabWidget#DocTabs > QTabBar::tab:!selected {{
        margin-top: 4px;
    }}
    QTabWidget#DocTabs > QTabBar::tab:hover {{
        background-color: {c['hover']};
        color: {c['text']};
    }}
    QTabWidget#DocTabs > QTabBar::tab:selected {{
        background-color: {c['canvas_bg']};
        color: {c['text']};
        font-weight: 600;
        border-top: 2px solid {c['accent']};
    }}
    /* 注意：这里**故意不写** QTabBar::close-button 的样式。
       QSS 一旦接管 close-button 子控件，Qt 就不再绘制按钮自身的图标，
       × 会变成一块空白（曾经的真实缺陷）；× 的图标改由 QIcon 提供，
       见 main_window._style_tab_close_buttons()。 */
    QTabWidget#DocTabs > QTabBar::tab {{
        padding-right: 4px;
    }}
    QToolButton#NewTabButton {{
        border: none;
        border-radius: 11px;
        padding: 2px 8px;
        color: {c['text_secondary']};
        font-size: 16px;
    }}
    QToolButton#NewTabButton:hover {{
        background-color: {c['hover']};
        color: {c['text']};
    }}

    /* ---------- 侧边栏分页（页面 / 目录 / 搜索） ---------- */
    QWidget#Sidebar QTabWidget::pane {{
        border: none;
        background: transparent;
    }}
    QWidget#Sidebar QTabBar::tab {{
        background: transparent;
        color: {c['text_secondary']};
        border: none;
        padding: 6px 12px;
        margin-right: 4px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 500;
    }}
    QWidget#Sidebar QTabBar::tab:hover {{
        background: {c['hover']};
        color: {c['text']};
    }}
    QWidget#Sidebar QTabBar::tab:selected {{
        background: {c['highlight']};
        color: {c['accent']};
        font-weight: 600;
    }}
    QWidget#Sidebar QTabBar::tab:disabled {{
        color: {c['disabled']};
    }}
    QWidget#Sidebar QLineEdit {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 6px 9px;
    }}
    QWidget#Sidebar QLineEdit:focus {{
        border-color: {c['accent']};
    }}
    QWidget#Sidebar QPushButton {{
        background-color: transparent;
        color: {c['text_secondary']};
        border: none;
        border-radius: 7px;
        padding: 6px 8px;
    }}
    QWidget#Sidebar QPushButton:hover {{
        background-color: {c['hover']};
        color: {c['text']};
    }}
    QWidget#Sidebar QPushButton:pressed {{
        background-color: {c['press']};
    }}
    QWidget#Sidebar QPushButton:disabled {{
        color: {c['disabled']};
    }}
    QWidget#Sidebar QTreeWidget {{
        background-color: transparent;
        border: none;
        border-radius: 8px;
        color: {c['text']};
        outline: none;
    }}
    QWidget#Sidebar QTreeWidget::item {{
        padding: 5px 7px;
        border-radius: 6px;
    }}
    QWidget#Sidebar QTreeWidget::item:hover {{
        background-color: {c['hover']};
    }}
    QWidget#Sidebar QTreeWidget::item:selected {{
        background-color: {c['highlight']};
        color: {c['text']};
    }}

    /* ---------- 状态栏 ---------- */
    QStatusBar {{
        background-color: {c['card']};
        color: {c['text_secondary']};
        border-top: 1px solid {c['border']};
        font-size: 12px;
        padding: 2px 8px;
    }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ padding-left: 14px; }}

    /* ---------- 菜单 ---------- */
    QMenuBar {{
        background-color: {c['card']};
        color: {c['text']};
        border-bottom: 1px solid {c['border']};
        padding: 2px 6px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 4px 10px;
        border-radius: 6px;
    }}
    QMenuBar::item:selected {{
        background-color: {c['highlight']};
        color: {c['text']};
    }}
    QMenu {{
        background-color: {c['card']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 6px 18px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background-color: {c['highlight']};
        color: {c['text']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: 5px 8px;
    }}

    /* ---------- 通用控件 ---------- */
    QMessageBox {{ background-color: {c['card']}; }}
    QMessageBox QLabel {{ color: {c['text']}; }}
    QPushButton#ColorButton {{
        border: 1px solid {c['border']};
        border-radius: 7px;
    }}
    QPushButton#ColorButton:hover {{ border-color: {c['accent']}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border']};
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['text_secondary']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['border']};
        border-radius: 4px;
        min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {c['text_secondary']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: {c['border']}; }}
    """


# ---------------------------------------------------------------------- #
# 内嵌 SVG 图标（不依赖外部资源）
# ---------------------------------------------------------------------- #
_SVGS = {
    # 工具栏：统一用单色线性图标，避免系统彩色图标（蓝色文件夹 / 软盘）破坏暖色主题
    "new": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5h8.5L18.5 7v13.5h-12.5z"/><path d="M14.5 3.5V7h4"/><path d="M12 10.5v6M9 13.5h6"/></svg>',
    "open": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 7.5h6l2 2h9v9.5h-17z"/><path d="M3.5 7.5V4.5h6l2 2"/></svg>',
    "save": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4.5h11l3 3v12H5z"/><path d="M8 4.5v5.5h7V4.5"/><path d="M8 19.5v-6h8v6"/></svg>',
    "export": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5v9"/><path d="M8.5 6.5 12 3l3.5 3.5"/><path d="M5 13v7h14v-7"/></svg>',
    "undo": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 7 4 12l5 5"/><path d="M4 12h9a6 6 0 0 1 6 6"/></svg>',
    "redo": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 7l5 5-5 5"/><path d="M20 12h-9a6 6 0 0 0-6 6"/></svg>',
    "prev": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6 14.5 12 8.5l6 6"/></svg>',
    "next": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9.5 12 15.5l6-6"/></svg>',
    "pen": '<svg viewBox="0 0 24 24" fill="{{c}}"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>',
    "droplet": '<svg viewBox="0 0 24 24" fill="{{c}}"><path d="M12 3.1c3.3 3.8 6.1 7.2 6.1 10.4a6.1 6.1 0 0 1-12.2 0C5.9 10.3 8.7 6.9 12 3.1z"/></svg>',
    "palette": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.4a8.6 8.6 0 1 0 0 17.2h1.1a1.8 1.8 0 0 0 1.2-3.1 1.8 1.8 0 0 1 1.2-3.1h2.4a3.7 3.7 0 0 0 3.7-3.7A7.4 7.4 0 0 0 12 3.4z"/><circle cx="7.4" cy="11.2" r="1"/><circle cx="9.1" cy="7.6" r="1"/><circle cx="13" cy="6.6" r="1"/><circle cx="16.4" cy="8.7" r="1"/></svg>',
    "eraser": '<svg viewBox="0 0 24 24" fill="{{c}}"><path d="M4 14l6-6 8 8-4 4H8z" opacity="0.92"/><path d="M13 5l6 6-2 2-6-6z"/></svg>',
    "highlighter": '<svg viewBox="0 0 24 24" fill="{{c}}"><path d="M15.5 2.6 21.4 8.5 11 18.9 5.1 13z" opacity="0.38"/><path d="M16.9 1.2 22.8 7.1 20.5 9.4 14.6 3.5z"/><path d="M3 20.4h8v1.8H3z"/></svg>',
    "read_single": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.7" stroke-linecap="round"><rect x="4.5" y="2.8" width="15" height="18.4" rx="1.6"/><path d="M8 7h8M8 10.6h8M8 14.2h5"/></svg>',
    "read_continuous": '<svg viewBox="0 0 24 24" fill="{{c}}"><rect x="4" y="2.4" width="16" height="6.6" rx="1.2"/><rect x="4" y="10.6" width="16" height="6.6" rx="1.2" opacity="0.5"/><rect x="4" y="18.8" width="16" height="2.8" rx="1.2" opacity="0.32"/></svg>',
    "sun": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4.2" fill="{{c}}"/><line x1="12" y1="3" x2="12" y2="5.5"/><line x1="12" y1="18.5" x2="12" y2="21"/><line x1="3" y1="12" x2="5.5" y2="12"/><line x1="18.5" y1="12" x2="21" y2="12"/><line x1="5.2" y1="5.2" x2="6.9" y2="6.9"/><line x1="17.1" y1="17.1" x2="18.8" y2="18.8"/><line x1="18.8" y1="5.2" x2="17.1" y2="6.9"/><line x1="6.9" y1="17.1" x2="5.2" y2="18.8"/></svg>',
    "moon": '<svg viewBox="0 0 24 24" fill="{{c}}"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
    "menu": '<svg viewBox="0 0 24 24" fill="{{c}}"><path d="M3 6h18v2H3zM3 11h18v2H3zM3 16h18v2H3z"/></svg>',
    "fit": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V5a1 1 0 0 1 1-1h4"/><path d="M20 9V5a1 1 0 0 0-1-1h-4"/><path d="M4 15v4a1 1 0 0 0 1 1h4"/><path d="M20 15v4a1 1 0 0 1-1 1h-4"/></svg>',
    "zoomin": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.4" y1="15.4" x2="21" y2="21"/><line x1="10.5" y1="7.5" x2="10.5" y2="13.5"/><line x1="7.5" y1="10.5" x2="13.5" y2="10.5"/></svg>',
    "zoomout": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.4" y1="15.4" x2="21" y2="21"/><line x1="7.5" y1="10.5" x2="13.5" y2="10.5"/></svg>',
    "search": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.4" y1="15.4" x2="21" y2="21"/></svg>',
    "rotleft": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5A9 9 0 1 1 3.6 15"/><path d="M3 4v5h5"/></svg>',
    "rotright": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 8.5A9 9 0 1 0 20.4 15"/><path d="M21 4v5h-5"/></svg>',
    "fitwidth": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5v14"/><path d="M20 5v14"/><line x1="8" y1="12" x2="16" y2="12"/><path d="M10.5 9.5 8 12l2.5 2.5"/><path d="M13.5 9.5 16 12l-2.5 2.5"/></svg>',
    "info": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16.5"/><line x1="12" y1="7.6" x2="12" y2="7.6"/></svg>',
    "toc": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round"><line x1="4" y1="6.5" x2="20" y2="6.5"/><line x1="8" y1="12" x2="20" y2="12"/><line x1="8" y1="17.5" x2="20" y2="17.5"/></svg>',
    "copy": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 5.5A1.5 1.5 0 0 0 13.5 4H5.5A1.5 1.5 0 0 0 4 5.5v8A1.5 1.5 0 0 0 5.5 15"/></svg>',
    # 标签关闭按钮（×）：QSS 的 QTabBar::close-button 只能设 image: url(磁盘文件)，
    # 而本项目坚持零外部资源，所以 × 由 QIcon 贴到关闭按钮上（见 main_window._style_tab_close_buttons）。
    "close": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="2.4" stroke-linecap="round"><line x1="6.5" y1="6.5" x2="17.5" y2="17.5"/><line x1="17.5" y1="6.5" x2="6.5" y2="17.5"/></svg>',
    # 标签页图标：一眼区分「笔记」与「PDF」
    "tab_note": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4.5h9.5L19 9v10.5H5z"/><path d="M14 4.5V9h5"/><path d="M8 13h8"/><path d="M8 16.5h5"/></svg>',
    "tab_pdf": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4.5h9.5L19 9v10.5H5z"/><path d="M14 4.5V9h5"/><path d="M8.5 17v-4.2h1.6a1.4 1.4 0 0 1 0 2.8H8.5"/><path d="M14.2 17v-4.2h1.5a2.1 2.1 0 0 1 0 4.2z"/></svg>',
    # Markdown：文档 + 井号，和笔记/PDF 一眼区分
    "tab_md": '<svg viewBox="0 0 24 24" fill="none" stroke="{{c}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4.5h9.5L19 9v10.5H5z"/><path d="M14 4.5V9h5"/><path d="M9.5 12.2l-.7 5.3"/><path d="M13.2 12.2l-.7 5.3"/><path d="M8.1 14.1h5.6"/><path d="M7.8 16.1h5.6"/></svg>',
}


class ThemeManager:
    """管理当前主题并提供配色、QSS 与图标。"""

    def __init__(self, theme: str = "light"):
        self.theme = theme if theme in THEMES else "light"
        self._qss_cache: Dict[str, str] = {}
        self._icon_cache: Dict[tuple, QIcon] = {}

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in THEMES else "light"

    def colors(self) -> Dict[str, str]:
        return _palette(self.theme)

    def qss(self) -> str:
        qss = self._qss_cache.get(self.theme)
        if qss is None:
            qss = build_qss(self.theme)
            self._qss_cache[self.theme] = qss
        return qss

    def canvas_bg(self) -> str:
        return self.colors()["canvas_bg"]

    # ----- 图标 -----
    def svg_icon(self, name: str, size: int = 20) -> QIcon:
        return self.svg_icon_colored(name, self.colors()["icon"], size)

    def svg_icon_colored(self, name: str, color: str, size: int = 20) -> QIcon:
        """按指定颜色渲染 SVG（色块按钮用对比色画图标）。"""
        key = (name, color, int(size))
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        svg = _SVGS.get(name)
        if not svg:
            return QIcon()
        svg = svg.replace("{{c}}", color)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            return QIcon()
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        icon = QIcon(pm)
        self._icon_cache[key] = icon
        return icon

    @staticmethod
    def std_icon(sp: QStyle.StandardPixmap) -> QIcon:
        return QApplication.style().standardIcon(sp)

    def icon(self, kind: str, size: int = 20) -> QIcon:
        """按动作类型返回图标。kind 见 main_window 中的使用。"""
        std_map = {
            "new": QStyle.StandardPixmap.SP_FileIcon,
            "open": QStyle.StandardPixmap.SP_DirOpenIcon,
            "save": QStyle.StandardPixmap.SP_DialogSaveButton,
            "export": QStyle.StandardPixmap.SP_DialogSaveButton,
            "undo": QStyle.StandardPixmap.SP_ArrowBack,
            "redo": QStyle.StandardPixmap.SP_ArrowForward,
            "prev": QStyle.StandardPixmap.SP_ArrowUp,
            "next": QStyle.StandardPixmap.SP_ArrowDown,
        }
        # 内嵌 SVG 图标（不依赖外部资源，颜色跟随主题）
        if kind in _SVGS:
            return self.svg_icon(kind, size)
        if kind in std_map:
            return self.std_icon(std_map[kind])
        return QIcon()

    def toggle(self) -> str:
        self.set_theme("dark" if self.theme == "light" else "light")
        return self.theme


#: 应用图标（打包 exe 的图标、任务栏/Alt-Tab、`make_icon.py` 生成 .ico 都用这一份）
APP_ICON_SVG = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="3" y="3" width="58" height="58" rx="14" fill="#c96442"/>'
    '<path d="M14 20h22M14 28h14" stroke="#ffffff" stroke-width="4.2" '
    'stroke-linecap="round" opacity="0.9"/>'
    '<path d="M18 46c7-1 8-13 14-19 3-3 7-3 8 0 1 4-3 7-9 8-7 1-13 4-13 4" '
    'fill="none" stroke="#ffffff" stroke-width="4.6" stroke-linecap="round" '
    'stroke-linejoin="round"/>'
    '</svg>'
)


def app_icon(size: int = 256) -> QIcon:
    """应用图标（内嵌 SVG 渲染，不依赖外部资源，任何主题下都是同一枚）。"""
    renderer = QSvgRenderer(QByteArray(APP_ICON_SVG.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)
