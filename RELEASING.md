# 发布流程（RELEASING）

本文件是维护者的**发布检查清单**：从版本号到 GitHub Release 的完整步骤。
普通用户的安装说明见 [README](README.md#下载安装普通用户)；
安装包定义在 `installer/HandwritingNotebook.iss`，一键构建脚本是 `build_release.ps1`。

> 产品只支持 **Windows 10 / 11 x64**，发布物是 Windows 安装包
> `HandwritingNotebook-<版本>-Setup.exe`。

## 0. 一次性准备

| 工具 | 用途 | 获取方式 |
|---|---|---|
| Python 3.12 + `requirements.txt` | 运行 / 打包 | <https://www.python.org/> 或 uv |
| PyInstaller | 打源码版 exe | `pip install pyinstaller` |
| Inno Setup 6 | 编译安装包 | `winget install JRSoftware.InnoSetup`，或 <https://jrsoftware.org/isdl.php> |
| Rust 工具链 + maturin | 编译 `hn_core` 加速核心 | `winget install Rustlang.Rustup` + `pip install maturin` |
| 代码签名证书（可选） | 对 exe / 安装包签名（详见 §0.1） | 商业 OV/EV 证书、Azure Trusted Signing、SignPath（开源免费）或自签名（仅本机信任） |

Inno Setup 默认装在 `C:\Program Files (x86)\Inno Setup 6`；装在别处时用
`build_release.ps1 -Iscc <ISCC.exe 路径>` 指定（或设环境变量 `HN_ISCC`），脚本也会搜索
PATH / Program Files / `%LOCALAPPDATA%\Programs\Inno Setup 6` 等常见位置。

GitHub 侧不需要额外 secret：Release 由 `.github/workflows/release.yml` 用仓库自带的
`GITHUB_TOKEN` 创建，因此 workflow 里必须有 `permissions: contents: write`。

### 0.1 可选：代码签名（对外分发强烈建议）

`build_release.ps1` 支持在构建时签名（先签 dist 里的 exe，再让 ISCC 打进安装包，最后签 Setup）：

```powershell
# 证书已在 CurrentUser\My（含私钥）
powershell -ExecutionPolicy Bypass -File build_release.ps1 -CertThumbprint <指纹>

# 用 PFX 文件（CI / 另一台机器）
powershell -ExecutionPolicy Bypass -File build_release.ps1 -Pfx my.pfx -PfxPassword <口令>
```

**CI 自动签名**：在仓库 Settings → Secrets and variables → Actions 添加：

| Secret | 内容 |
|---|---|
| `SIGNING_PFX_BASE64` | PFX 文件的单行 Base64（`[Convert]::ToBase64String([IO.File]::ReadAllBytes('my.pfx'))`） |
| `SIGNING_PFX_PASSWORD` | PFX 密码 |

配置后 `release.yml` 会在 `build_release.ps1` 里自动加 `-Pfx/-PfxPassword` 并签名；未配置则跳过
签名（产物仍可发布，只是会有 SmartScreen「未知发布者」提示）。

**证书选择**：

- **自签名**：一条命令生成、只对本机/内部有效，适合公司内分发（证书私钥不要入库）；
- **Azure Trusted Signing**：微软托管，按需付费，需完成组织身份验证；
- **Certum Open Source Code Signing**：开源项目可申请，价格低；
- **SignPath.io**：面向开源项目的免费/赞助签名服务，可与 GitHub Actions 集成。

> 自签名证书不能消除**别人机器**上的 SmartScreen 提示；要实现「无提示」必须使用受信任的
> OV/EV 证书，并让新发布物逐步积累 SmartScreen 信誉（新证书初期仍可能提示）。

## 1. 确定版本号

版本号形如 `5.3.1`（语义化版本），发布物命名 `HandwritingNotebook-5.3.1-Setup.exe`。

以下**三处必须一致**，否则构建 / CI 会失败：

| 位置 | 应写的内容 |
|---|---|
| `assets/version_info.txt` | `filevers=(5, 3, 0, 0)`、`FileVersion` 与 `ProductVersion` = `5.3.1.0` |
| `installer/HandwritingNotebook.iss` | 安装包版本（`AppVersion` / `AppVerName`）= `5.3.1` |
| git tag 与 GitHub Release | `v5.3.1` |

> `build_release.ps1` 会先做版本一致性检查；`release.yml` 会用 tag（去掉 `v`）校验
> `assets/version_info.txt` 中的版本，不一致时直接失败。

## 2. 源码预检（必须在干净的工作区）

```bash
ruff check
pyright
pytest -q
python main.py --selftest %TEMP%\hn-check
```

- `ruff check` 0 问题；`pyright` 无 error（warning 允许）；
- `pytest -q` 全量通过（含性能预算，**不要**用 `HN_SKIP_PERF` 跳过）；
- 源码 `--selftest` 打印 `SELFTEST OK`。

## 3. 构建安装包

```powershell
# 安装包必须内置 Rust 核心（build_release.ps1 会检查 dist 里的 hn_core，缺了直接失败）
python build_rust.py

# 一键发布构建（可加 -Iscc / -Python / -Version，见下表）
powershell -ExecutionPolicy Bypass -File build_release.ps1
```

`build_release.ps1` 依次执行：

1. **版本一致性检查**：`assets/version_info.txt` ↔ `installer/HandwritingNotebook.iss` ↔ 目标版本；
2. `pyinstaller build.spec --clean --noconfirm` 打包（onedir 白名单裁剪 + 收集 `hn_core`）；
3. **两轮成品自检**：默认后端 + 强制 `HN_RENDER_BACKEND=rust`，都要求 `SELFTEST OK`，
   Rust 轮次还要求自检输出「渲染后端：rust」；同时校验 exe 的 `FileVersion=5.3.1.0`；
4. `ISCC.exe /DMyAppVersion=<版本>` 编译安装包，并校验 Setup 的版本资源；
5. 打印产物路径、字节数与 SHA256（以及 `dist` 总大小 / 文件数），并生成
   `dist_release\SHA256SUMS`（安装包的 SHA256；未编译安装包时跳过）。

常用参数：

| 参数 | 作用 |
|---|---|
| `-Python <exe>` | 指定 Python 解释器（默认自动找已装 PyInstaller 的 python） |
| `-Iscc <exe>` | 指定 Inno Setup 的 `ISCC.exe`（也可用 `HN_ISCC`） |
| `-Version <x.y.z>` | 覆盖版本号（仅发布演练 / 校验用，正式发布不要传） |
| `-SkipBuild` | 复用已有 `dist\` 产物，跳过 PyInstaller |
| `-SkipInstaller` | 只出源码版 exe，不编译安装包 |
| `-SkipSelftest` | 跳过两轮成品自检（不推荐，正式发布禁用） |

产物：

```
dist_release\HandwritingNotebook-5.3.1-Setup.exe
dist_release\SHA256SUMS
```

`SHA256SUMS` 由 `build_release.ps1` 自动生成；CI 的 `.github/workflows/release.yml` 也会
重新生成一次并随 Release 上传。本机校验：

```powershell
Get-FileHash .\dist_release\HandwritingNotebook-5.3.1-Setup.exe -Algorithm SHA256
```

## 4. 安装验收（发布前必须真装一次）

在干净的 Windows 10 / 11 机器（或卸载后重装）上：

```powershell
# 静默安装（Inno Setup 参数）
.\dist_release\HandwritingNotebook-5.3.1-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

安装位置约定：**D 盘存在且可写时默认装到 `D:\Apps\HandwritingNotebook`**（不占系统盘）；
**没有 D 盘或 D 盘不可写的机器回退到 `%LOCALAPPDATA%\Programs\HandwritingNotebook`**。
快捷方式 / 卸载信息按 Windows 规范仍在用户配置目录（C 盘），程序本体（exe / `_internal`）在安装目录。
安装目录可以在向导里改；升级时沿用上次目录。下面统一用 `<安装目录>` 指代实际位置。

逐项确认：

- [ ] 安装后**实际位置优先在 D 盘**：`D:\Apps\HandwritingNotebook\` 有 `手写笔记本与PDF批注.exe`
      （以及 `_internal\` 与 `_internal\hn_core\hn_core.pyd`）；
- [ ] 无 D 盘回退路径也验证一次（可在虚拟机 / 无 D 盘机器上装，或临时用
      `/DIR="%LOCALAPPDATA%\Programs\HandwritingNotebook"` 指定安装目录验证回退形态）；
- [ ] `<安装目录>` 里的 exe 跑 `--selftest %TEMP%\hn-check` 输出 `SELFTEST OK`；
- [ ] 强制 Rust 后端再自检一次：`set HN_RENDER_BACKEND=rust` 后同样 `SELFTEST OK`；
- [ ] 桌面快捷方式「手写笔记本与PDF批注」的 TargetPath / WorkingDirectory 指向 `<安装目录>` 的 exe；
- [ ] 开始菜单文件夹「手写笔记本与PDF批注」+ 程序 / 卸载快捷方式存在；
- [ ] 「设置 → 应用」里有卸载项，显示名含 `5.3.1`；exe / Setup 的「属性 → 详细信息」版本为 `5.3.1.0`；
- [ ] 双击启动不弹控制台，任务栏显示应用名与图标（不是 python）；
- [ ] 打开 PDF / 新建笔记 / 保存批注 / 导出 PDF 正常；
- [ ] 安装时勾选的可选任务「注册 `.note` 打开方式」只在右键「打开方式」里出现，不抢占默认程序；
- [ ] 卸载：`<安装目录>\unins000.exe`（默认如 `D:\Apps\HandwritingNotebook\unins000.exe`，
      静默参数 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`）后快捷方式、安装目录、卸载项清理干净，
      然后按本节重新安装，保持机器处于「已安装」状态；
- [ ] （建议）截屏留证：窗口界面 + 桌面快捷方式 + 任务栏图标。

## 5. 更新文档

- `CHANGELOG.md`：顶部新增对应版本段落（日期、功能、修复、升级注意）；
- `README.md`：版本号、下载链接、功能清单、已知限制是否还准确；
- `THIRD_PARTY_NOTICES.md`：依赖或构建工具变化时同步；
- `EPISODE2.md`：Rust 核心 / 打包方式变化时同步。

## 6. 提交、打 tag、推送

```bash
git add -A
git commit -m "chore(release): v5.3.1"
git tag -a v5.3.1 -m "v5.3.1"
git push origin main
git push origin v5.3.1
```

推送 `v*` tag 会触发 `.github/workflows/release.yml` 自动构建并创建 Release。
如果只想先验证流水线，可用 GitHub Actions 页面的 **Run workflow**（`workflow_dispatch`）
手动触发，不会创建 Release。

> **别重复创建 Release**：推 tag 后由 CI 创建（含 Setup exe + `SHA256SUMS`），
> 手动只补正文 / 额外资产（如便携 zip）即可；如果打算完全手动发布，就别推 tag 触发
> 自动流程，改用 `workflow_dispatch` 只跑构建。

## 7. GitHub Release 资产

Release 标题 `v5.3.1`。如果 Release 由 CI 自动创建，正文是 `release.yml` 里的简短模板
（安装 / 校验 / 卸载说明）；手动创建时可用 `CHANGELOG.md` 对应段落。需要上传：

| 资产 | 必需 | 说明 |
|---|---|---|
| `HandwritingNotebook-5.3.1-Setup.exe` | ✅ | Windows 安装包（按用户安装） |
| `SHA256SUMS` | ✅ | 所有资产的 SHA256，供用户校验 |
| `HandwritingNotebook-5.3.1-portable.zip` | 可选 | 源码版 `dist\手写笔记本与PDF批注\` 打包，免安装 |

发布后检查：

- [ ] Release 页面可下载安装包，SHA256 与本地一致；
- [ ] 从 Release 下载一次并安装（或至少校验哈希）；
- [ ] README 的 Releases 链接可打开，Markdown 渲染正常；
- [ ] 仓库 About / Topics 指向 `notebook-compre-v2`（旧仓库不再更新）。

## 8. CI 发布流水线（`.github/workflows/release.yml`）

| 项 | 值 |
|---|---|
| 触发 | push tag `v*`；另有 `workflow_dispatch` 手动触发 |
| Runner | `windows-latest` |
| 权限 | `permissions: contents: write`（创建 Release 需要） |
| 版本号 | 从 tag 取并去掉 `v` 前缀（`v5.3.1` → `5.3.1`），校验与 `assets/version_info.txt` 一致 |
| 工具链 | `actions/checkout@v4`、`actions/setup-python@v5`（3.12）、`dtolnay/rust-toolchain@stable`、maturin |
| Inno Setup | 直接用 runner 预装的 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` |
| 步骤 | 装依赖 → 编译 `hn_core` → 校验版本 → `build_release.ps1`（内含 PyInstaller、两轮自检、ISCC）→ 生成 `SHA256SUMS` → 上传 artifact |
| Release | `softprops/action-gh-release` 创建，资产为 Setup exe + SHA256SUMS（仅 tag 触发时创建） |

## 9. 常见问题

**构建报「版本号不一致」**
：检查 §1 的三处版本号；CI 里以 tag 为准，本地以 `assets/version_info.txt` 为准。

**`ISCC.exe` 找不到**
：确认安装了 Inno Setup 6；装在别处时用 `-Iscc <路径>` 或环境变量 `HN_ISCC` 指定。
CI 上 Inno Setup 位于 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`。

**成品自检失败**
：先看 `--selftest` 输出与 `selftest.log`；常见原因是 PyInstaller 把平台插件 / PyMuPDF / PIL
裁掉了。用 `build.spec` 打包（不要用 `-F` 临时命令）并检查裁剪白名单。

**SmartScreen 提示「未知发布者」**
：安装包未签名。用 `build_release.ps1 -CertThumbprint <指纹>` 或 `-Pfx <pfx> -PfxPassword <口令>`
在构建时签名（先签 exe 再打安装包，安装后的程序也是签名版本）；CI 侧配置
`SIGNING_PFX_BASE64` / `SIGNING_PFX_PASSWORD` 两个 Secrets 后自动签名。自签名证书只能让
本机信任，**消除别人机器上的提示需要受信任的 OV/EV 证书**（或 SignPath 等开源签名服务）。

**tag 推错了**
：先删 GitHub Release，再删远端 tag（`git push origin :refs/tags/v5.3.1`）与本地 tag
（`git tag -d v5.3.1`），修正后重新打 tag 推送。

**发布物能否只发源码**
：可以，但 AGPL-3.0 要求分发二进制时同时提供对应完整源码；发布安装包请与同版本的源码 tag 一起发布。
