# 第三方组件许可声明

本项目以 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布，
第三方组件的版权归各自作者所有。下表分三类：**随程序分发的运行时依赖**、
**可选编译的 Rust 扩展**、**仅在构建 / 打包阶段使用的工具**（不随产品分发）。

## 1. 运行时依赖（随安装包分发）

| 组件 | 许可证 | 用途 |
|---|---|---|
| PyMuPDF | AGPL-3.0 | PDF 解析 / 渲染 / 批注导出 |
| PySide6 (Qt for Python) | LGPL-3.0 | 桌面 UI 框架 |
| Pillow | MIT-CMU (HPND) | 图像处理 |
| numpy | BSD-3-Clause | 数值数组（Rust 零拷贝契约） |
| Python 标准库 / CPython | PSF License | 解释器与标准库（PyInstaller 打包时一并收集） |

## 2. Rust 加速核心（可选，安装包中已内置）

| 组件 | 许可证 | 用途 |
|---|---|---|
| tiny-skia | BSD-3-Clause | Rust 光栅化 |
| rstar | MIT / Apache-2.0 | Rust R 树命中测试 |
| pyo3 | MIT / Apache-2.0 | Rust <-> CPython 扩展 |
| numpy (Rust crate) | MIT / Apache-2.0 | pyo3 的 numpy 绑定 |

> Rust 核心缺失或不兼容时会自动降级到纯 Python 实现，程序功能不受影响；
> 安装包已经内置编译好的 `hn_core`，普通用户无需安装 Rust。

## 3. 构建 / 打包工具（不随产品分发）

| 工具 | 许可证 | 用途 |
|---|---|---|
| PyInstaller | GPL-2.0-or-later + bootloader exception | 把 Python 程序打包为 Windows 可执行文件 |
| Inno Setup | Inno Setup License（免费，允许商用分发） | 生成 Windows 安装包 `HandwritingNotebook-*-Setup.exe` |
| maturin | MIT / Apache-2.0 | 构建 `hn_core` 的 abi3 轮子 |
| Rust 工具链（rustc / cargo） | MIT / Apache-2.0 | 编译 Rust 核心 |
| pytest / ruff / pyright | MIT / MIT / MIT | 测试与静态检查 |

PyInstaller 的 **bootloader exception** 明确允许把用 PyInstaller 打包的程序
以任意许可证分发，因此本项目的安装包不因打包工具而改变许可证。
上述工具仅出现在源码构建流程与 CI 中，**不是**安装包运行时的组成部分。

## 4. AGPL-3.0 义务说明

- 本项目依赖 **PyMuPDF（AGPL-3.0）**，因此本项目整体按 AGPL-3.0 发布。
- 分发本项目的可执行文件 / 安装包时，必须同时向接收者提供**对应的完整源代码**
  （本仓库即源码；`dist_release/` 的安装包应与同一版本的源码 tag 一起发布）。
- 若把本项目（或其修改版）作为**网络服务**对外提供，也必须向使用者开放完整源码。
- 安装包生成时使用的构建脚本（`build_release.ps1`、`build.spec`、`installer/HandwritingNotebook.iss`）
  已在仓库中公开，满足「可用于重建二进制」的相应源码要求。

## 5. 完整许可文本

各组件完整许可文本见其官方仓库或发行包：

- PyMuPDF: <https://github.com/pymupdf/PyMuPDF>
- PySide6 / Qt: <https://www.qt.io/licensing/>
- Pillow: <https://python-pillow.org/>
- numpy: <https://numpy.org/>
- tiny-skia: <https://github.com/RazrFalcon/tiny-skia>
- rstar: <https://github.com/georust/rstar>
- pyo3: <https://github.com/PyO3/pyo3>
- PyInstaller: <https://pyinstaller.org/en/stable/license.html>
- Inno Setup: <https://jrsoftware.org/isinfo.php>
