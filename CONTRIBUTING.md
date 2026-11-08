# 贡献指南

本项目是 **Windows 10 / 11** 桌面程序（PySide6 + PyMuPDF，可选 Rust 加速核心）。
本文档面向**源码开发**；只想使用的话，直接从
[GitHub Releases](https://github.com/genhao3aaa/notebook-compre-v2/releases) 下载安装包即可。

## 环境要求

- 平台：Windows 10 / 11（依赖 Qt 触控笔事件与 Windows 反馈 API，暂不支持其他平台）
- Python **3.10+**（开发与 CI 使用 3.12）
- Rust（可选）：只有从源码编译 `hn_core` 加速核心时需要；未编译时程序自动回退纯 Python 实现
- Inno Setup 6（可选）：只有制作安装包时需要
- 依赖：`pip install -r requirements.txt pytest ruff pyright`

## 获取源码与安装依赖

```bash
git clone https://github.com/genhao3aaa/notebook-compre-v2.git
cd notebook-compre-v2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pytest ruff pyright
```

用 [uv](https://docs.astral.sh/uv/) 更快：

```bash
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r requirements.txt pytest ruff pyright
```

## 运行

```bash
python main.py
```

无控制台运行 / 建源码快捷方式可用仓库自带的 `run_episode2.cmd`（详见 README「运行」）。

## 构建 Rust 核心（可选）

未编译时程序自动回退到纯 Python 实现，功能可用但性能较低。

```bash
pip install maturin
python build_rust.py            # 产出 dist_rust/hn_core-*-cp310-abi3-win_amd64.whl 并安装
python build_rust.py --check    # 只检查扩展能否导入
```

> 安装包（`HandwritingNotebook-*-Setup.exe`）已经内置 Rust 核心，
> 只有从源码运行且想要加速时才需要自己编译。

## 提交前自检

```bash
ruff check                      # 静态检查（配置在 pyproject.toml）
pyright                         # 类型检查（pyrightconfig.json，验收线「无 error」）
pytest -q                       # 全量回归 + 性能预算
python main.py --selftest %TEMP%\hn-check
```

`--selftest` 会离屏跑完整链路（创建 PDF → 打开 → 渲染 → 批注 → 导出 → 笔记存取），
成功打印 `SELFTEST OK`，失败返回非 0。

CI 配置在 `.github/workflows/ci.yml`（windows-latest）：`ruff` → `pyright` → `pytest` →
基准存档 → 源码自检，第二个 job 负责打包 + 成品自检 + 体积预算。

## 打包与发布构建

只打源码版可执行文件（PyInstaller，onedir + 白名单裁剪）：

```bash
pip install pyinstaller
pyinstaller build.spec
# 产物：dist\手写笔记本与PDF批注\手写笔记本与PDF批注.exe
```

制作完整安装包需要 **Inno Setup 6**（二选一）：

```powershell
winget install JRSoftware.InnoSetup
# 或从 https://jrsoftware.org/isdl.php 下载安装
```

发布构建前先编译 Rust 核心（安装包内置 `hn_core`，缺了构建脚本会直接失败），
然后在仓库根目录执行一键构建：

```powershell
python build_rust.py
powershell -ExecutionPolicy Bypass -File build_release.ps1
```

`build_release.ps1` 依次做：版本一致性检查（`assets/version_info.txt` ↔
`installer/HandwritingNotebook.iss`）→ PyInstaller 打包 → 成品自检两轮（默认 + 强制 Rust）
→ Inno Setup 生成安装包 → 校验版本资源 → 输出哈希。

产物在 `dist_release\`：`HandwritingNotebook-<版本>-Setup.exe` + `SHA256SUMS`。
Inno Setup 默认装在 `C:\Program Files (x86)\Inno Setup 6`；装在别处时用
`-Iscc <ISCC.exe 路径>` 指定（或设 `HN_ISCC`），脚本也会自动搜索常见位置；
需要指定解释器时用 `-Python`。安装包定义见 `installer\HandwritingNotebook.iss`。

完整发布步骤（版本号、tag、GitHub Release 资产）见 [RELEASING.md](RELEASING.md)。

## 提交规范

- 提交信息建议使用 Conventional Commits（`feat:` / `fix:` / `docs:` / `perf:` / `chore:`）。
- 每个改动尽量单一主题、可独立回滚。
- 新行为请附测试；性能改动请附基准数据（`tests/benchmarks/`，支持 `--json`）。
- 不要提交构建产物与缓存（`.gitignore` 已覆盖 `build/`、`dist*/`、`dist_release/`、`rust/target/` 等）。

## 许可

本项目以 **AGPL-3.0** 发布。贡献即视为同意你的贡献以 AGPL-3.0 授权。
