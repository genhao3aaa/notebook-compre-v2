<#
.SYNOPSIS
    手写笔记本与PDF批注（Episode2）—— 发布构建脚本（本地 / CI 共用）。

.DESCRIPTION
    一条命令完成「可复现的正式发布」：

      1. 版本一致性检查：assets/version_info.txt ↔ installer/HandwritingNotebook.iss ↔ 参数
      2. PyInstaller 打包（build.spec，onedir + 白名单裁剪 + hn_core Rust 核心）
      3. 成品 --selftest（默认后端 + 强制 HN_RENDER_BACKEND=rust 两轮）
      4. Inno Setup 编译安装包（installer/HandwritingNotebook.iss）
      5. 校验 exe / Setup.exe 的版本资源，打印全部产物路径 + SHA256

    退出码：0 = 全部通过；非 0 = 任一步失败（CI 直接据此判断）。

.PARAMETER Python
    Python 解释器路径。默认依次尝试：$env:HN_PYTHON → Episode2 根目录的
    .venv → PATH 里的 python。

.PARAMETER Iscc
    Inno Setup 的 ISCC.exe 路径。默认依次尝试：$env:HN_ISCC → PATH →
    Inno Setup 6 常见安装位置。

.PARAMETER Version
    覆盖版本号（形如 5.3.0）。默认从 assets/version_info.txt 读取，
    仅用于「验证脚本对得上」或发布演练；正常发布不要传。

.PARAMETER SkipBuild
    跳过 PyInstaller（复用已有 dist\ 产物），仍会做成品自检 / 安装包 / 版本校验。

.PARAMETER SkipInstaller
    跳过 Inno Setup（只出 dist\ 下的 exe）。

.PARAMETER SkipSelftest
    跳过两轮成品自检（不推荐；CI 与正式发布都应跑）。

.EXAMPLE
    pwsh -File build_release.ps1

.EXAMPLE
    pwsh -File build_release.ps1 -Python "D:\venvs\hn\Scripts\python.exe" -Iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

.NOTES
    产物：
      dist\手写笔记本与PDF批注\手写笔记本与PDF批注.exe
      dist_release\HandwritingNotebook-5.3.0-Setup.exe
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$Iscc = "",
    [string]$Version = "",
    [switch]$SkipBuild,
    [switch]$SkipInstaller,
    [switch]$SkipSelftest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot     = $PSScriptRoot
$AppName      = '手写笔记本与PDF批注'
$ExeName      = '手写笔记本与PDF批注.exe'
$DistDir      = Join-Path $RepoRoot ('dist\' + $AppName)
$DistExe      = Join-Path $DistDir $ExeName
$SpecPath     = Join-Path $RepoRoot 'build.spec'
$VersionTxt   = Join-Path $RepoRoot 'assets\version_info.txt'
$IssPath      = Join-Path $RepoRoot 'installer\HandwritingNotebook.iss'
$ReleaseDir   = Join-Path $RepoRoot 'dist_release'
$BuildLogDir  = Join-Path $RepoRoot 'build'
$SelftestRoot = Join-Path $BuildLogDir 'selftest'
$Stopwatch    = [System.Diagnostics.Stopwatch]::StartNew()
$NL           = [Environment]::NewLine

# ---------------------------------------------------------------------- #
# 构建中间物一律放 D 盘（用户要求：各项操作尽量不在 C 盘进行）
# ---------------------------------------------------------------------- #
# PyInstaller 的构建缓存、ISCC 的临时文件、成品 selftest 的临时目录默认都落在
# %TEMP%（通常是 C:）。这里统一改到仓库下的 build\tmp（本项目在 D 盘 → 不往 C 盘写东西），
# 也可用环境变量 HN_BUILD_TMP 覆盖。
# 注意：只在**本脚本进程**里改环境变量，不影响系统设置；子进程会继承。
$WorkTmpRoot  = if ($env:HN_BUILD_TMP) { $env:HN_BUILD_TMP } else { Join-Path $RepoRoot 'build\tmp' }
$BuildTmpDir  = Join-Path $WorkTmpRoot 'build'
$PyiConfigDir = Join-Path $WorkTmpRoot 'pyinstaller'
New-Item -ItemType Directory -Force -Path $BuildTmpDir, $PyiConfigDir | Out-Null
$env:TEMP = $BuildTmpDir
$env:TMP = $BuildTmpDir
$env:PYINSTALLER_CONFIG_DIR = $PyiConfigDir
$env:TMPDIR = $BuildTmpDir

# 清掉 DSH 工具环境注入的 AppCompat 兼容层（__COMPAT_LAYER=DetectorsAppHealth）。
# 实测它会让本机启动的 Setup / GUI 进程被 Windows 降到 Low integrity level，
# 写 %LOCALAPPDATA% / 安装目录时可能误报「拒绝访问（错误 5）」；用户从资源管理器
# 双击（Explorer 环境没有这个变量）不受影响。自动化构建与验收必须清掉才代表真实环境。
if (Test-Path Env:__COMPAT_LAYER) {
    Remove-Item Env:__COMPAT_LAYER -ErrorAction SilentlyContinue
    Write-Host '已从本进程环境移除 __COMPAT_LAYER（DSH 兼容层副作用）'
}

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host ('=== ' + $Text + ' ===') -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host ''
    Write-Host ('[FAIL] ' + $Message) -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------- #
# 版本号：唯一来源 assets/version_info.txt
# ---------------------------------------------------------------------- #
function Read-ProductVersion([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "找不到版本文件：$Path" }
    $text = Get-Content -LiteralPath $Path -Raw
    $m = [regex]::Match($text, 'filevers\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
    if (-not $m.Success) { throw "version_info.txt 里没有可解析的 filevers=(a,b,c,d)：$Path" }
    $tuple = @([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value, [int]$m.Groups[4].Value)
    $fileVersion = [regex]::Match($text, "StringStruct\('FileVersion',\s*'([^']+)'\)")
    $prodVersion = [regex]::Match($text, "StringStruct\('ProductVersion',\s*'([^']+)'\)")
    if (-not $fileVersion.Success -or -not $prodVersion.Success) {
        throw "version_info.txt 缺少 FileVersion/ProductVersion 字符串"
    }
    return [pscustomobject]@{
        Path           = $Path
        Tuple          = $tuple
        FileVersion    = $fileVersion.Groups[1].Value
        ProductVersion = $prodVersion.Groups[1].Value
        Version        = ('{0}.{1}.{2}' -f $tuple[0], $tuple[1], $tuple[2])
    }
}

function Read-IssDefaultVersion([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "找不到安装包脚本：$Path" }
    $text = Get-Content -LiteralPath $Path -Raw
    $m = [regex]::Match($text, '#define\s+MyAppVersion\s+"([^"]+)"')
    if (-not $m.Success) { throw ".iss 里找不到 #define MyAppVersion：$Path" }
    return $m.Groups[1].Value
}

Write-Step '0/5 版本一致性检查'
$info = Read-ProductVersion $VersionTxt
if ($Version) {
    $Version = $Version.Trim()
} else {
    $Version = $info.Version
}
$expected4 = $Version + '.0'
if ($info.Version -ne $Version) {
    Fail ("assets/version_info.txt 的 filevers 是 {0}，与目标版本 {1} 不一致（先升版本号再发布）" -f $info.Version, $Version)
}
if ($info.FileVersion -ne $expected4 -or $info.ProductVersion -ne $expected4) {
    Fail ("version_info.txt 的 FileVersion/ProductVersion 应为 {0}，实际 FileVersion={1} ProductVersion={2}" -f $expected4, $info.FileVersion, $info.ProductVersion)
}
$issVersion = Read-IssDefaultVersion $IssPath
if ($issVersion -ne $Version) {
    Fail ("installer/HandwritingNotebook.iss 的 MyAppVersion={0}，与 version_info.txt 的 {1} 不一致" -f $issVersion, $Version)
}
Write-Host ("版本号 OK：{0}（filevers={1} / FileVersion={2} / AppVersion={3}）" -f $Version, ($info.Tuple -join ','), $info.FileVersion, $issVersion)

# ---------------------------------------------------------------------- #
# 工具定位：python / ISCC
# ---------------------------------------------------------------------- #
function Resolve-Python([string]$Explicit) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Explicit) { $candidates.Add($Explicit) }
    if ($env:HN_PYTHON) { $candidates.Add($env:HN_PYTHON) }
    $candidates.Add((Join-Path $RepoRoot '.venv\Scripts\python.exe'))
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $candidates.Add($cmd.Source) }
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        if (Test-Path -LiteralPath $c) {
            & $c -c "import PyInstaller" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $c).Path }
        }
    }
    throw '找不到可用的 Python（需要已安装 PyInstaller）。请用 -Python 指定解释器。'
}

function Resolve-Iscc([string]$Explicit) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Explicit) { $candidates.Add($Explicit) }
    if ($env:HN_ISCC) { $candidates.Add($env:HN_ISCC) }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { $candidates.Add($cmd.Source) }
    $programFilesX86 = [Environment]::GetFolderPath('ProgramFilesX86')
    $programFiles = [Environment]::GetFolderPath('ProgramFiles')
    if ($programFilesX86) { $candidates.Add((Join-Path $programFilesX86 'Inno Setup 6\ISCC.exe')) }
    if ($programFiles) { $candidates.Add((Join-Path $programFiles 'Inno Setup 6\ISCC.exe')) }
    if ($env:LOCALAPPDATA) { $candidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')) }
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        if (Test-Path -LiteralPath $c) { return (Resolve-Path -LiteralPath $c).Path }
    }
    throw '找不到 Inno Setup 的 ISCC.exe。请用 -Iscc 指定，或安装 Inno Setup 6 并加入 PATH。'
}

Write-Step '1/5 准备构建工具'
$PythonExe = Resolve-Python $Python
Write-Host ("Python : {0}" -f $PythonExe)
& $PythonExe -c "import PyInstaller, PySide6, pymupdf, numpy, PIL; print('PyInstaller', PyInstaller.__version__, '| PySide6', PySide6.__version__, '| pymupdf', pymupdf.__version__)"
if ($LASTEXITCODE -ne 0) { Fail 'Python 依赖不完整（PyInstaller / PySide6 / PyMuPDF / numpy / Pillow）' }
$IsccExe = $null
if (-not $SkipInstaller) {
    $IsccExe = Resolve-Iscc $Iscc
    Write-Host ("ISCC   : {0}" -f $IsccExe)
}

New-Item -ItemType Directory -Force -Path $BuildLogDir | Out-Null
New-Item -ItemType Directory -Force -Path $SelftestRoot | Out-Null

# ---------------------------------------------------------------------- #
# PyInstaller
# ---------------------------------------------------------------------- #
Write-Step '2/5 PyInstaller 打包（build.spec，onedir）'
if ($SkipBuild) {
    Write-Host '跳过构建（-SkipBuild），复用已有 dist 产物'
} else {
    if (-not (Test-Path -LiteralPath $SpecPath)) { Fail "找不到 $SpecPath" }
    $pyiLog = Join-Path $BuildLogDir 'release_build.log'
    Push-Location $RepoRoot
    try {
        & $PythonExe -m PyInstaller $SpecPath --clean --noconfirm 2>&1 | Tee-Object -FilePath $pyiLog
        $pyiExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($pyiExit -ne 0) { Fail ("PyInstaller 失败（退出码 {0}），日志：{1}" -f $pyiExit, $pyiLog) }
    Write-Host ("PyInstaller 日志：{0}" -f $pyiLog)
}
if (-not (Test-Path -LiteralPath $DistExe)) { Fail "打包产物不存在：$DistExe（先不要 -SkipBuild）" }

$HnCorePyd = Join-Path $DistDir '_internal\hn_core\hn_core.pyd'
if (-not (Test-Path -LiteralPath $HnCorePyd)) {
    Fail ("打包产物缺少 Rust 核心：{0}（build.spec 的 hn_core 收集没生效？）" -f $HnCorePyd)
}
Write-Host ("Rust 核心：{0}（{1:N0} 字节）" -f $HnCorePyd, (Get-Item -LiteralPath $HnCorePyd).Length)

$exeInfo = (Get-Item -LiteralPath $DistExe).VersionInfo
# 注意 .Trim()：资源里的版本字符串可能被补空格（Inno 写的 Setup.exe 实测会补）
if ($exeInfo.FileVersion.Trim() -ne $expected4) {
    Fail ("PyInstaller 成品 FileVersion={0}，与 version_info.txt 的 {1} 不一致" -f $exeInfo.FileVersion, $expected4)
}
Write-Host ("成品版本资源 OK：FileVersion={0} ProductVersion={1}" -f $exeInfo.FileVersion, $exeInfo.ProductVersion)

# ---------------------------------------------------------------------- #
# 成品自检
# ---------------------------------------------------------------------- #
function Invoke-AppSelftest {
    param(
        [string]$ExePath,
        [string]$WorkDir,
        [hashtable]$ExtraEnv = @{},
        [int]$TimeoutMs = 300000
    )
    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
    $saved = @{}
    foreach ($k in $ExtraEnv.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process')
        [Environment]::SetEnvironmentVariable($k, [string]$ExtraEnv[$k], 'Process')
    }
    try {
        # 用 .NET Process API 而不是 Start-Process：后者默认走 ShellExecute，
        # 在某些非交互宿主（CI 服务账号 / 受限桌面 / 沙箱）里会等待 shell 通知而卡住；
        # UseShellExecute=false 走纯 CreateProcess，行为确定、退出码可靠。
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = (Resolve-Path -LiteralPath $ExePath).Path
        $psi.Arguments = '--selftest "' + $WorkDir + '"'
        $psi.UseShellExecute = $false
        $psi.WorkingDirectory = [System.IO.Path]::GetDirectoryName($ExePath)
        # 成品自检的临时目录也放 D 盘（子进程继承本脚本已改过的 TEMP/TMP，这里显式再兜一层）
        $psi.EnvironmentVariables['TEMP'] = $BuildTmpDir
        $psi.EnvironmentVariables['TMP'] = $BuildTmpDir
        # 再显式清一次 AppCompat 兼容层，避免宿主环境重新注入
        if ($psi.EnvironmentVariables.ContainsKey('__COMPAT_LAYER')) { $psi.EnvironmentVariables.Remove('__COMPAT_LAYER') }
        $proc = [System.Diagnostics.Process]::Start($psi)
        if (-not $proc.WaitForExit($TimeoutMs)) {
            try { $proc.Kill() } catch { }
            throw ("成品自检超时（>{0} ms）：{1}" -f $TimeoutMs, $ExePath)
        }
        $exitCode = $proc.ExitCode
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
    }
    $logs = @(Get-ChildItem -Path $WorkDir -Recurse -Filter 'selftest.log' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime)
    $logPath = ''
    $logText = ''
    if ($logs.Count -gt 0) {
        $logPath = $logs[-1].FullName
        $logText = Get-Content -LiteralPath $logPath -Raw -Encoding UTF8
    }
    return [pscustomobject]@{ ExitCode = $exitCode; LogPath = $logPath; Text = $logText }
}

if ($SkipSelftest) {
    Write-Step '3/5 跳过成品自检（-SkipSelftest）'
} else {
    Write-Step '3/5 成品自检（默认后端）'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $workDefault = Join-Path $SelftestRoot ('default-' + $stamp)
    $hnLog = Join-Path $workDefault 'hn-backend.log'
    $r1 = Invoke-AppSelftest -ExePath $DistExe -WorkDir $workDefault -ExtraEnv @{ HN_LOG = 'info'; HN_LOG_FILE = $hnLog }
    if ($r1.ExitCode -ne 0) { Fail ("成品自检失败（退出码 {0}），日志：{1}" + $NL + "{2}" -f $r1.ExitCode, $r1.LogPath, $r1.Text) }
    if ($r1.Text -notmatch 'SELFTEST OK') { Fail ("成品自检没有打印 SELFTEST OK，日志：{0}" + $NL + "{1}" -f $r1.LogPath, $r1.Text) }
    if (Test-Path -LiteralPath $hnLog) {
        Get-Content -LiteralPath $hnLog -Encoding UTF8 | Where-Object { $_ -match 'backend_' } | ForEach-Object { Write-Host ('  ' + $_) }
    }
    Write-Host ("自检 OK：{0}" -f $r1.LogPath)

    Write-Step '3.5/5 成品自检（强制 HN_RENDER_BACKEND=rust）'
    $workRust = Join-Path $SelftestRoot ('rust-' + $stamp)
    $hnLogRust = Join-Path $workRust 'hn-backend.log'
    $r2 = Invoke-AppSelftest -ExePath $DistExe -WorkDir $workRust -ExtraEnv @{
        HN_RENDER_BACKEND = 'rust'; HN_LOG = 'info'; HN_LOG_FILE = $hnLogRust
    }
    if ($r2.ExitCode -ne 0) { Fail ("Rust 后端自检失败（退出码 {0}），日志：{1}" + $NL + "{2}" -f $r2.ExitCode, $r2.LogPath, $r2.Text) }
    if ($r2.Text -notmatch 'SELFTEST OK') { Fail ("Rust 后端自检没有 SELFTEST OK，日志：{0}" + $NL + "{1}" -f $r2.LogPath, $r2.Text) }
    if ($r2.Text -notmatch '渲染后端：rust') {
        Fail ("强制 HN_RENDER_BACKEND=rust 但自检显示的后端不是 rust，日志：{0}" + $NL + "{1}" -f $r2.LogPath, $r2.Text)
    }
    if (Test-Path -LiteralPath $hnLogRust) {
        Get-Content -LiteralPath $hnLogRust -Encoding UTF8 | Where-Object { $_ -match 'backend_' } | ForEach-Object { Write-Host ('  ' + $_) }
    }
    Write-Host ("Rust 后端自检 OK：{0}" -f $r2.LogPath)
}

# ---------------------------------------------------------------------- #
# Inno Setup 安装包
# ---------------------------------------------------------------------- #
$SetupExe = Join-Path $ReleaseDir ('HandwritingNotebook-' + $Version + '-Setup.exe')
Write-Step '4/5 Inno Setup 编译安装包'
if ($SkipInstaller) {
    Write-Host '跳过安装包（-SkipInstaller）'
} else {
    if (-not (Test-Path -LiteralPath $IssPath)) { Fail "找不到 $IssPath" }
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    $issLog = Join-Path $BuildLogDir 'release_issc.log'
    Push-Location (Split-Path $IssPath -Parent)
    try {
        & $IsccExe ('/DMyAppVersion=' + $Version) $IssPath 2>&1 | Tee-Object -FilePath $issLog
        $isccExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($isccExit -ne 0) { Fail ("ISCC 编译失败（退出码 {0}），日志：{1}" -f $isccExit, $issLog) }
    if (-not (Test-Path -LiteralPath $SetupExe)) { Fail "ISCC 成功但找不到安装包：$SetupExe" }
    $setupInfo = (Get-Item -LiteralPath $SetupExe).VersionInfo
    # Inno 写进 Setup.exe 的 FileVersion 会补空格（"5.3.0.0             "），这里先 Trim
    if ($setupInfo.FileVersion.Trim() -ne $expected4) {
        Fail ("安装包 FileVersion={0}，与目标 {1} 不一致" -f $setupInfo.FileVersion, $expected4)
    }
    Write-Host ("安装包版本资源 OK：FileVersion={0}" -f $setupInfo.FileVersion)
    Write-Host ("ISCC 日志：{0}" -f $issLog)
}

# ---------------------------------------------------------------------- #
# 产物清单 + SHA256
# ---------------------------------------------------------------------- #
Write-Step '5/5 产物清单'
$Stopwatch.Stop()
$artifacts = New-Object System.Collections.Generic.List[object]
$artifacts.Add([pscustomobject]@{ Kind = 'PyInstaller 成品'; Path = $DistExe })
$artifacts.Add([pscustomobject]@{ Kind = 'Rust 核心'; Path = $HnCorePyd })
if (-not $SkipInstaller -and (Test-Path -LiteralPath $SetupExe)) {
    $artifacts.Add([pscustomobject]@{ Kind = '安装包'; Path = $SetupExe })
}
$distFiles = @(Get-ChildItem -LiteralPath $DistDir -Recurse -File)
$distBytes = ($distFiles | Measure-Object -Property Length -Sum).Sum
Write-Host ("dist 总大小：{0:N1} MB / {1} 个文件（CI 体积预算 < 150 MB）" -f ($distBytes / 1MB), $distFiles.Count)
foreach ($a in $artifacts) {
    $item = Get-Item -LiteralPath $a.Path
    $hash = (Get-FileHash -LiteralPath $a.Path -Algorithm SHA256).Hash
    Write-Host ''
    Write-Host ("{0}" -f $a.Kind) -ForegroundColor Yellow
    Write-Host ("  路径   : {0}" -f $item.FullName)
    Write-Host ("  字节数 : {0:N0}" -f $item.Length)
    Write-Host ("  SHA256 : {0}" -f $hash)
}
# 落盘校验和文件（发布用；CI/人工都能直接核对）
$sumsPath = Join-Path $ReleaseDir 'SHA256SUMS'
if (-not $SkipInstaller -and (Test-Path -LiteralPath $SetupExe)) {
    $setupHash = (Get-FileHash -LiteralPath $SetupExe -Algorithm SHA256).Hash.ToLower()
    $setupName = Split-Path $SetupExe -Leaf
    Set-Content -LiteralPath $sumsPath -Value ($setupHash + '  ' + $setupName) -Encoding Ascii
    Write-Host ''
    Write-Host ("SHA256SUMS：{0}" -f $sumsPath) -ForegroundColor Yellow
} else {
    Write-Host ''
    Write-Host '（未编译安装包，跳过 SHA256SUMS 生成）'
}

Write-Host ''
Write-Host ("完成，总耗时 {0:N1} 秒" -f $Stopwatch.Elapsed.TotalSeconds) -ForegroundColor Green
exit 0
