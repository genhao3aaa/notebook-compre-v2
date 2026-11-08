"""启动性能与交互回归（2026-11）：会话恢复不再阻塞启动。

覆盖三件事：
1. defer_session_restore：窗口 show() 之前不恢复会话；
2. 恢复阶段的「批注 MD5 不匹配」不弹模态框（会挡住启动），改为状态栏汇总；
3. 非当前标签的 Markdown 懒排版，切过去时才渲染。
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _make_pdf(path):
    import pymupdf as fitz

    doc = fitz.open()
    for _ in range(2):
        doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()
    return path


def _window(tmp_path, **kwargs):
    from src.core.settings import AppSettings
    from src.ui.main_window import MainWindow

    return MainWindow(settings=AppSettings(path=str(tmp_path / "s.ini")),
                      restore_geometry=False, **kwargs)


def _close(win):
    win._confirm_save = lambda *a, **k: True
    for t in list(win._tabs):
        t.dirty = False
    win.close()


def test_deferred_session_restore_waits_for_window(qapp, tmp_path):
    """defer_session_restore=True：构造阶段不恢复，显式调用后才恢复。"""
    from src.core.settings import AppSettings

    pdf = _make_pdf(str(tmp_path / "deferred.pdf"))
    s = AppSettings(path=str(tmp_path / "deferred.ini"))
    s.set_open_tabs([{"kind": "pdf", "path": pdf}])
    from src.ui.main_window import MainWindow

    win = MainWindow(settings=s, defer_session_restore=True, restore_geometry=False)
    try:
        assert all(not t.path for t in win._tabs), "延迟恢复：构造时不应打开文件"
        win.start_deferred_session_restore()
        assert any(t.path == pdf for t in win._tabs), "调用后应恢复会话"
    finally:
        _close(win)


def test_restore_quiet_suppresses_annot_mismatch_dialog(qapp, tmp_path, monkeypatch):
    """会话恢复遇到批注 MD5 不匹配：不弹模态框，记录到 _restore_annot_warnings。"""
    from src.core.annot_document import AnnotDocument
    from src.ui.controllers import file_ops as file_ops_mod

    pdf = _make_pdf(str(tmp_path / "mismatch.pdf"))
    annot = AnnotDocument.from_pdf(pdf, "deadbeef" * 4, 1)
    annot.save(str(tmp_path / "mismatch.annot"))

    def _boom(*a, **k):
        raise AssertionError("quiet=True 时不应弹模态框")

    monkeypatch.setattr(file_ops_mod.QMessageBox, "warning", staticmethod(_boom))
    win = _window(tmp_path, restore_session=False)
    try:
        tab = win.open_pdf(pdf, activate=False, quiet=True)
        assert tab is not None
        assert pdf in win._restore_annot_warnings
    finally:
        _close(win)


def test_restore_annotation_warning_summary(qapp, tmp_path, monkeypatch):
    """会话恢复结束后，状态栏汇总「忽略了几份旧批注」，不再要求点弹窗。"""
    from src.core.annot_document import AnnotDocument
    from src.core.settings import AppSettings
    from src.ui.controllers import file_ops as file_ops_mod

    pdf = _make_pdf(str(tmp_path / "resume.pdf"))
    AnnotDocument.from_pdf(pdf, "deadbeef" * 4, 1).save(str(tmp_path / "resume.annot"))
    s = AppSettings(path=str(tmp_path / "resume.ini"))
    s.set_open_tabs([{"kind": "pdf", "path": pdf}])
    monkeypatch.setattr(file_ops_mod.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("恢复阶段不应弹模态框"))))
    from src.ui.main_window import MainWindow

    win = MainWindow(settings=s, defer_session_restore=True, restore_geometry=False)
    try:
        win.start_deferred_session_restore()
        assert any(t.path == pdf for t in win._tabs)
        assert not win._restore_annot_warnings, "汇总后应清空"
        assert "旧批注" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
    finally:
        _close(win)


def test_lazy_markdown_restore_renders_on_switch(qapp, tmp_path):
    """非当前标签的 Markdown 恢复时只读文本不排版，切过去时才解析 + 渲染。"""
    md = tmp_path / "lecture.md"
    md.write_text("# 一级标题\n\n正文 **粗体**\n\n## 二级标题\n", encoding="utf-8")
    win = _window(tmp_path, restore_session=False)
    try:
        tab = win.open_markdown(str(md), activate=False, lazy=True)
        assert tab is not None
        assert tab.md_pending is True, "非当前标签应延迟排版"
        assert tab.md_text, "文本仍应读入（只是不排版）"
        win._switch_to_tab(tab)
        assert tab.md_pending is False, "切换后应完成排版"
        assert tab.md_headings, "切换后应解析出标题大纲"
    finally:
        _close(win)
