"""程序入口。

支持 Windows 10/11 高 DPI 缩放（150% / 200% 等），界面与笔迹保持清晰。

命令行参数（2026-10-01 新增）
---------------------------
- `python main.py` / 双击 exe：正常启动；
- `python main.py <文件.pdf|文件.note|文件.md> [...]`：启动后直接把这些文件开成标签
  （与「把文件拖到 exe 上」/ 资源管理器右键打开一致），PDF 仍然会恢复到上次读到的那一页；
- `--selftest [工作目录]`：打包后的自检（见 src/ui/selftest.py）。

进程身份与崩溃兜底（2026-11，5.3.0 发布）
------------------------------------------
- **AppUserModelID** 固定为 `HandwritingNotebook.Episode2`：任务栏 / 开始菜单 / Alt-Tab
  按它归组，不再显示成「Python」；安装版与源码版用同一个 ID，快捷方式与任务栏图标一致。
- **顶层异常兜底**（只有正常启动路径有，`--selftest` 不装）：未捕获异常写
  `%LOCALAPPDATA%\\HandwritingNotebook\\logs\\crash-<时间戳>.log` 并弹中文对话框。
  GUI 程序没有控制台，否则用户只看到「闪退」；自检路径只看退出码与 selftest.log，
  不弹模态框（无人点击会挂住 CI）。

打包注意：`from src.ui.main_window import MainWindow` 等重依赖刻意放在 `main()` 内部，
这样导入失败也能被下面的顶层兜底记日志，而不是进程无声退出。
"""

from __future__ import annotations

import os
import sys

#: 进程 AppUserModelID（任务栏 / 开始菜单归组用；安装版与源码版保持一致）
APP_USER_MODEL_ID = "HandwritingNotebook.Episode2"

#: 用户数据目录名（崩溃日志等放在 %LOCALAPPDATA%/<这个名字>/ 下）
_APP_DATA_DIR_NAME = "HandwritingNotebook"


def _open_paths(window, paths) -> None:
    """把命令行里给的文件路径开成标签（不是本程序格式就忽略）。"""
    from src.core.markdown_document import is_markdown

    for raw in paths:
        path = os.path.abspath(raw)
        if not os.path.isfile(path):
            continue
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".pdf", ".note") or is_markdown(path):
                window.open_path(path)
        except Exception:                    # 单个文件打不开不该拦住启动
            continue


# ---------------------------------------------------------------------- #
# 应用身份：AppUserModelID
# ---------------------------------------------------------------------- #
def _set_app_user_model_id() -> None:
    """设置进程 AppUserModelID（必须在创建 QApplication **之前**调用）。

    不设的话 Windows 会把进程归到「Python」下：任务栏图标/分组不对，固定到任务栏
    或开始菜单后显示的是 python 而不是本程序，安装版也拿不到自己的身份。
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        # 显式 AppUserModelID（字符串），进程生命周期内有效。
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:                        # 旧系统 / 受限环境：只影响任务栏分组，不该拦住启动
        pass


# ---------------------------------------------------------------------- #
# 顶层崩溃兜底：写日志 + （正常启动时）弹中文对话框
# ---------------------------------------------------------------------- #
def _crash_log_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, _APP_DATA_DIR_NAME, "logs")


def _write_crash_log(exc: BaseException) -> str | None:
    """把未捕获异常与运行环境写进 `crash-<时间戳>.log`，返回日志路径（失败返回 None）。"""
    import datetime
    import platform
    import traceback

    try:
        directory = _crash_log_dir()
        os.makedirs(directory, exist_ok=True)
        now = datetime.datetime.now()
        path = os.path.join(directory, "crash-%s.log" % now.strftime("%Y%m%d-%H%M%S"))
        with open(path, "w", encoding="utf-8") as f:
            f.write("手写笔记本与 PDF 批注 - 未处理异常\n")
            f.write("时间: %s\n" % now.isoformat(timespec="seconds"))
            f.write("程序: %s\n" % sys.executable)
            f.write("frozen: %s\n" % getattr(sys, "frozen", False))
            f.write("Python: %s\n" % sys.version.replace("\n", " "))
            f.write("平台: %s\n" % platform.platform())
            f.write("参数: %r\n" % (sys.argv,))
            f.write("\n")
            f.write("".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__)))
        return path
    except Exception:                        # 写日志本身失败也不能再抛
        return None


def _show_crash_dialog(detail: str) -> None:
    """崩溃时弹中文对话框（GUI 程序没有控制台；失败就静默）。"""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(
            None,
            "手写笔记本与 PDF 批注 - 启动失败",
            "程序遇到未处理的错误，已写入日志：\n\n%s\n\n"
            "请把该日志反馈给开发者。" % detail)
        del app
    except Exception:
        pass


def _install_crash_hook() -> None:
    """安装 sys.excepthook：未捕获异常（含 Qt 槽函数里的）写日志 + 弹框。

    `--selftest` 路径**不**装这个钩子：自检靠退出码与 selftest.log 判定，
    弹模态框无人点击会让 CI 永久挂住。
    """
    import traceback

    def _hook(exc_type, exc, tb) -> None:      # pragma: no cover - 只在真崩溃时走
        try:
            traceback.print_exception(exc_type, exc, tb)
        except Exception:
            pass
        log_path = _write_crash_log(exc)
        _show_crash_dialog(log_path or "%s: %s" % (exc_type.__name__, exc))

    sys.excepthook = _hook


def main() -> int:
    # A5：打包后自检入口（`<exe> --selftest [工作目录]`）：
    # 启动 → 打开 PDF → 手写 → 保存批注 → 导出 → 保存笔记，全程离屏运行。
    # 打包裁剪最容易伤到运行时才加载的东西（平台插件 / PyMuPDF / PIL），
    # 所以发布前必须能在成品里跑这串检查。
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        from src.ui.selftest import run_selftest

        return run_selftest(sys.argv[2] if len(sys.argv) > 2 else None)

    # 应用身份：必须在 QApplication 创建之前；崩溃兜底紧跟其后（导入失败也能记日志）。
    _set_app_user_model_id()
    _install_crash_hook()

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    # 高 DPI：Qt 6 默认已开启高分屏缩放，这里仅设置缩放取整策略，
    # 让 150% / 200% 等非整数比例下界面与笔迹保持清晰。
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 先把命令行里的文件路径摘出来：Qt 会把 `sys.argv` 里它自己的参数吃掉并改写
    # 这个列表，之后再读就拿不到文件路径了（实测：打包版「拖文件到 exe 上」打不开）。
    requested = [a for a in sys.argv[1:] if not a.startswith("-")]

    app = QApplication(sys.argv)
    app.setApplicationName("手写笔记本与 PDF 批注")
    # 应用图标内嵌在 theme.py 里（与打包 exe 的 .ico 同一份来源）：
    # 任务栏 / Alt-Tab / 任务管理器都会显示它，而不是 Qt/Python 的默认图标。
    from src.ui.theme import app_icon

    app.setWindowIcon(app_icon())

    from src.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    # 命令行里给的文件：等窗口显示后再开，界面才有正确的尺寸与状态栏。
    if requested:
        QTimer.singleShot(0, lambda: _open_paths(window, requested))

    return app.exec()


if __name__ == "__main__":
    # 自检路径的异常由 run_selftest 自己吞掉并返回非 0；这里只兜「进程级」异常。
    _is_selftest = len(sys.argv) > 1 and sys.argv[1] == "--selftest"
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:             # noqa: BLE001 - 顶层兜底就是要抓全部
        try:
            import traceback

            traceback.print_exc()
        except Exception:
            pass
        _log_path = _write_crash_log(exc)
        if not _is_selftest:
            _show_crash_dialog(_log_path or "%s: %s" % (type(exc).__name__, exc))
        sys.exit(1)
