# Episode2 v1：Python/Qt 外壳 + Rust 核心（ROADMAP 路线 B）

> 本文件说明 **Episode2** 的 Rust 加速核心：后端契约、对拍口径与实测数据。
>
> Episode1 已冻结，只保留在旧仓库 [genhao3aaa/notebook-compre](https://github.com/genhao3aaa/notebook-compre)
> 作为历史版本。当前版本 **v5.3.1** 以独立仓库
> [genhao3aaa/notebook-compre-v2](https://github.com/genhao3aaa/notebook-compre-v2) 发布，首次提供独立安装包：
> 安装版是真正的 Windows 应用（内置 Python 运行时与 Rust 核心），桌面 / 开始菜单快捷方式指向
> 安装目录下的 `手写笔记本与PDF批注.exe`；源码启动脚本 `run_episode2.cmd` 只用于开发调试。
> 详见文末「与 Episode1 的关系」。

## 1. 这一版做了什么（对照 ROADMAP §3）

| ROADMAP | 内容 | 本版状态 |
|---|---|---|
| **B1** 核心边界 | `src/render/backend.py`：`RenderBackend` 契约（`rasterize` / `simplify` / `hit_test`），Python 参考实现与 Rust 实现二选一 | ✅ 完成 |
| **B3.1** 对拍框架 | `tests/benchmarks/bench_backend.py`（对拍 + 计时 + `--json`）、`tests/test_backend_parity.py`（CI 闸门） | ✅ 完成 |
| **B3.2** Rust `rasterize` | `rust/hn_core`：tiny-skia 变宽轮廓一次填充（含单点/圆头/压感过渡） | ✅ 完成（QPainter 主路径接入留到下一版，见 §6） |
| **B3.3** Rust `simplify` + `hit_test` | RDP（显式栈，无递归深度限制）+ `rstar` 包围盒 R 树 | ✅ 完成 |
| **B3.4** 打包 | `build_rust.py` 一键出 abi3 轮子；PyInstaller 收集 `.pyd` 并打进安装包 | ✅ 完成（v5.3.0） |
| **B3.5** A/B 基准 | 见 §4（1k/5k 笔画实测） | ✅ 完成 |

关键取舍（与 ROADMAP 一致）：

* **纯函数边界**：Rust 只做几何与光栅化，不碰 Qt 对象、不碰 PDF、不碰文件系统——
  这样才可能与参考实现逐点/逐像素对拍，也才能一键回退；
* **零拷贝**：所有数据走 numpy 缓冲（`PyReadonlyArray1<f32>` / `into_pyarray`），
  不做逐点跨语言调用；
* **一定有参考实现**：`HN_RENDER_BACKEND=python` 强制走 Python；扩展缺失/ABI 不匹配时
  **自动降级**并在日志里说明（`backend_rust_unavailable`），程序不会因为「性能优化」不可用。

## 2. 目录与文件

```
episode2/
├── rust/hn_core/
│   ├── Cargo.toml            # pyo3 0.23 / numpy 0.23 / tiny-skia 0.11 / rstar 0.12
│   ├── pyproject.toml        # maturin 配置（module-name = hn_core，abi3-py310）
│   └── src/lib.rs            # simplify / hit_test / rasterize + 几何口径注释
├── src/render/backend.py     # ★ 契约 + Python 参考实现 + Rust 实现 + 选择/降级 + 应用适配器
├── src/tools/{pen,highlighter,eraser}.py   # 抬笔简化 / 橡皮命中改走后端
├── tests/benchmarks/bench_backend.py       # 对拍 + 基准（支持 --json）
├── tests/test_backend_parity.py            # 对拍回归（CI 闸门）
├── bench_backend_result.json               # 本次实测的机器可读结果
└── build_rust.py             # 一键编译 + 安装扩展
```

## 3. 怎么用

```bash
# 1) 工具链（没有 MSVC 时可用 GNU 目标）
winget install Rustlang.Rustup
rustup default stable-x86_64-pc-windows-gnu      # 有 VS Build Tools 时可用默认的 msvc
uv pip install maturin numpy

# 2) 编译并安装扩展（产出 dist_rust/hn_core-*-cp310-abi3-win_amd64.whl）
python build_rust.py
python build_rust.py --check                     # 只检查是否可导入

# 3) 跑程序 / 测试
python main.py
pytest -q
python tests/benchmarks/bench_backend.py --json   # 对拍 + 基准

# 4) 切换后端（出问题立即回退）
set HN_RENDER_BACKEND=python     # 强制参考实现
set HN_RENDER_BACKEND=rust       # 强制 Rust（不可用时自动降级并记日志）
```

## 4. 实测（Windows / CPython 3.12 / rustc stable（GNU 目标）/ tiny-skia 0.11.4）

对拍结论：**全部达标**（`bench_backend_result.json`）

| 规模 | `simplify` | `hit_test` | `rasterize`（420×420） |
|---|---:|---:|---:|
| 300 笔画 | 37.8 ms → **0.64 ms（59x）** | 0.144 → **0.019 ms（7.6x）** | 27.0 → **3.1 ms（8.6x）** |
| 1000 笔画 | 152 ms → **2.5 ms（60x）** | 0.504 → **0.076 ms（6.6x）** | 86.4 → **7.8 ms（11.1x）** |
| 5000 笔画 | 940 ms → **16.7 ms（56x）** | 2.53 → **0.41 ms（6.1x）** | 413 → **36.1 ms（11.5x）** |

正确性口径：

* `simplify`：Rust 保留点数与 Python 参考实现**逐条一致**（300/300、1000/1000、5000/5000）；
* `hit_test`：40 次随机查询，参考命中 1416 个 → **漏 0、多给候选 0**；
* `rasterize`：覆盖率差 0.20% / 0.54% / 0.47%（容差 0.8%），alpha 通道平均绝对差 ≤ 2.8，
  墨迹像素 RGB 平均绝对差 ≤ 2.2（容差 20）。

> 为什么不能要求逐像素相同：Qt 与 tiny-skia 的抗锯齿算法不同，每条笔画边缘都有
> 1px 左右的半透明带；笔画越密、重叠越多，累计差越大。这里的口径是
> 「墨迹覆盖率 + 墨迹像素的颜色」——即用户真正看得见的部分。

## 5. 回退与观测

* `HN_RENDER_BACKEND=python` → 立刻回到 Episode1 的几何实现（零风险）；
* `HN_LOG=info` → 启动时打印 `backend_selected backend=rust version=0.1.0`；
  扩展装不上时打印 `backend_rust_unavailable error=...`；
* 对拍不达标 → `tests/test_backend_parity.py` 直接失败，CI 拦在合并前。

## 6. 下一版（拟）

1. **`rasterize` 接入 QPainter 主路径**：`canvas_render.py` 的整页重建改为
   「Rust 出 RGBA → `QImage` 直接贴」，替换掉现在的逐笔 `drawPath`；
   需要先解决「实时墨迹（`_draw_live_ink`）与重建结果一致」的口径问题（Episode1 A1 踩过）；
2. ~~**PyInstaller 收 `.pyd`**~~：**已在 v5.3.0 完成**——`build.spec` 收集 `hn_core` abi3 轮子，
   安装包内置 Rust 核心，成品 `--selftest` 验证扩展在位；
3. **大页面基准**：在真实 A4 / dpr 1.5 页面上再跑一轮，确认 5k 笔画的整页重建进入 50 ms 级；
4. `hit_test` 的精确判定也搬进 Rust（现在 R 树只做粗筛，精确几何仍在 Python）。

## 7. 保存位置与阅读位置（v1.1）

* **保存位置**：批注默认写在 PDF 旁边（`<pdf>.annot`）；那里写不了就退到**候选链里第一个用真探针验证能写的目录**：
  `HN_ANNOT_DIR` → `%LOCALAPPDATA%\手写笔记本与PDF批注\annotations\`（历史位置，
  文件名 `<12 位路径哈希>-<原 PDF 文件名>.annot`）→ `%APPDATA%` → `文档` → 系统临时目录；
  打开时按**同一顺序**找回批注，位置定下来后沿用、不在「旁边 / 兜底」之间来回跳。
  为什么需要候选链：在受限文件权限 / 安全策略（企业管控、AppContainer 等）下，PDF 旁边与 `%LOCALAPPDATA%` 兜底目录可能**同时**不可写
  （实测 `os.open(..., O_CREAT|O_EXCL)` 返回 `PermissionError [Errno 13] winerror=None`，而目录 ACL 看上去仍是全权限），
  此时保存只会弹出 `WriteError: 创建临时文件失败：保存位置（文件夹）不允许写入`。
  自查：`python diagnose_save_permission.py "<目录>"`（`--fix` 顺手修只读与残骸，`--json` 机器可读，退出码 0 / 1 / 2）；
  候选链名单与判定以 `src/core/annot_store.py` 为准，回归测试 `tests/test_annot_store.py`。
* **阅读位置**：再次打开同一份 PDF 会回到上次读到的那一页（连续模式连滚动位置一起恢复）。
  离线实测：656 页英文书真实 PDF，走「打开 → 跳页 → 连续模式滚动 → 关闭 → 重开」，
  状态栏页码与页码框都恢复到正确页；回归测试 `tests/test_page_state.py`。
  命令行 / 拖放打开走同一条恢复逻辑：`python main.py <文件.pdf|文件.note> …` 会开成多个标签
  （坏路径与未知类型忽略，不弹错），PDF 仍回到上次那一页 —— 回归 `tests/test_startup.py::test_cli_file_arguments_open_tabs`。
* 这两项与 Episode1 的行为**一致**：Episode1 再次打开同一份 PDF 也是回到上次阅读位置，**不是打开成空文件**。
* **设置存哪儿（v1.1）**：偏好（阅读位置 / 会话标签 / 主题 / 笔色）默认写注册表
  `HKCU\Software\WorkBuddy\HandwritingNotebook`；写不进去时 `QSettings` **不抛异常**，只把 `status()` 置成
  `AccessError`，表现就是「记不住阅读位置」。现在启动时真探一次注册表，写不进就自动改用 INI 文件：
  `HN_SETTINGS_FILE` → `%APPDATA%\WorkBuddy\HandwritingNotebook.ini` →
  `%LOCALAPPDATA%\手写笔记本与PDF批注\settings.ini` → `%TEMP%\手写笔记本与PDF批注\settings.ini`
  （已经存在的 INI 优先复用，`HN_SETTINGS_INI=1` 可强制 INI；注册表不可用会在
  `%LOCALAPPDATA%\手写笔记本与PDF批注\registry-unavailable.flag` 留标记）；当前后端用 `AppSettings.storage()` 查看。
  回归测试 `tests/test_page_state.py`（注册表被禁 → INI、INI 跨实例往返、INI 后端下重开回到上次那一页）。
* **冻结版验收（2026-10-01）**：episode2 全量 **283 passed / 1 skipped**（含 `test_startup` / `test_selftest`）；
  保存兜底链 **9/9**（PDF 旁边与 `%LOCALAPPDATA%` 都不可写 → 批注落到 `%TEMP%` 候选并**能读回**）；全目录不可写 **12/12**
  （不崩、错误文本含「所有备用位置都写不进去」+ 候选位置清单、旧 `.annot` 字节不变、无 `.tmp-` 残骸）；
  真实 656 页书 **14/14**（注册表不可写 → 自动 INI，关闭前 `page=222/656`、状态栏「页: 223 / 656」，重开后一致）；
  `HN_ANNOT_DIR` **9/9**（显式目录优先作兜底，PDF 旁边可写时仍优先 PDF 旁边）。
* **无头自动化的坑**：offscreen / 无头跑回归时，`_load_pdf_into_tab` 里的「批注不匹配」提示（`QMessageBox.warning`，MD5 不一致）是**模态框**，
  会永久挂住脚本（产品行为合理）—— 做无头回归要给这个提示加钩子，或每轮都用全新目录。

## 8. 与 Episode1 的关系

* **Episode1**：v5.2.2 及更早的历史版本，**已冻结**，代码保留在旧仓库
  [genhao3aaa/notebook-compre](https://github.com/genhao3aaa/notebook-compre)，不再更新；
  旧仓库的 clone 地址与安装说明均已过时，日常使用请用新仓库。
* **Episode2（当前版本）**：自 **v5.3.0** 起以独立仓库
  [genhao3aaa/notebook-compre-v2](https://github.com/genhao3aaa/notebook-compre-v2) 发布，
  并首次提供**独立安装包**（`HandwritingNotebook-5.3.1-Setup.exe`）：
  * 安装版按用户安装：默认优先 `D:\Apps\HandwritingNotebook`（不占系统盘），
    没有 D 盘（或 D 盘不可写）时回退到 `%LOCALAPPDATA%\Programs\HandwritingNotebook`；
    无需管理员权限，也**无需安装 Python**；
  * 桌面 / 开始菜单快捷方式指向安装目录下的 `手写笔记本与PDF批注.exe`（不再是源码启动脚本），
    exe 内置 Python 运行时与 Rust 核心 `hn_core`；
  * 卸载走「设置 → 应用 → 手写笔记本与PDF批注」，或开始菜单里的卸载快捷方式。
* **源码运行仍保留**：开发调试可 `python main.py`，或用 `run_episode2.cmd`
  （双击无控制台启动 / `console` 看 traceback / `shortcut` 建源码快捷方式）。
  普通用户不需要这些步骤，直接下载安装包即可。
* **版本号口径**：exe / 安装包版本以 `assets/version_info.txt` 为准（v5.3.1 → `5.3.1.0`）；
  CHANGELOG 历史章节里的 `v5.x` 是开发期界面迭代里程碑标签，两者不是同一套编号。
* **文件格式**：`.note` / `.annot` 使用 v2 二进制容器（magic 不匹配会明确报错）；
  更旧的程序读不了 v2 文件，需要交换时用 `save(path, version=1)` 写回 JSON。
