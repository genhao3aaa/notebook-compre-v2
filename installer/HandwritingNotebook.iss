; -*- coding: utf-8 -*-
; ============================================================================
; 手写笔记本与PDF批注（Episode2）—— Inno Setup 6 安装包脚本
; ----------------------------------------------------------------------------
; 产物：..\dist_release\HandwritingNotebook-5.3.0-Setup.exe
; 版本：AppVersion=5.3.0（单一变量 MyAppVersion；build_release.ps1 会与
;       assets/version_info.txt 做一致性检查，并用 /DMyAppVersion=<版本> 传入）
;
; 安装位置：优先 D:\Apps\HandwritingNotebook（用户要求尽量不占 C 盘）；
;           没有 D 盘 / D 盘不可写时回退 %LOCALAPPDATA%\Programs\HandwritingNotebook
;           （按用户安装，无需管理员；快捷方式/卸载信息仍在用户配置目录，这是 Windows 规范）
; 快捷方式：桌面「手写笔记本与PDF批注.lnk」+ 开始菜单「手写笔记本与PDF批注」文件夹
; 卸载：     %LOCALAPPDATA%\Programs\HandwritingNotebook\unins000.exe
;           静默：unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
; 静默安装： HandwritingNotebook-5.3.0-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;
; 中文向导：installer/ChineseSimplified.isl（Inno Setup 6.1.0+ 简体中文，
;           取自 jrsoftware/issrc 的 is-6_2_2 标签，与 6.2.2 编译器配套）。
;           同时保留英文，供非中文系统 / 英文 CI runner 回退。
; ============================================================================

#define MyAppName "手写笔记本与PDF批注"
#ifndef MyAppVersion
  #define MyAppVersion "5.3.0"
#endif
#define MyAppVersion4 MyAppVersion + ".0"
#define MyAppPublisher "Handwriting Notebook Project"
#define MyAppExeName "手写笔记本与PDF批注.exe"
#define MyAppDirName "HandwritingNotebook"
#define SourceRoot ".."

[Setup]
; AppId 固定：升级时能识别同一产品（卸载信息 / 安装目录复用都靠它）。
; 注意 "{{" 是 Inno 的转义写法，最终值为 {7C1E5A42-...}。
AppId={{7C1E5A42-9D3B-4F62-8A1E-5B2C7D9E4F13}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/genhao3aaa/notebook-compre-v2
AppSupportURL=https://github.com/genhao3aaa/notebook-compre-v2
VersionInfoVersion={#MyAppVersion4}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion4}

; 按用户安装（PrivilegesRequired=lowest，无 UAC 提权）
; 安装位置：优先 D:\Apps\{#MyAppDirName}（用户要求程序本体不要占 C 盘），
; D 盘不存在/不可写时回退 %LOCALAPPDATA%\Programs\{#MyAppDirName}，见文件末尾 [Code]。
DefaultDirName={code:GetDefaultInstallDir}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0

; 向导与交互
WizardStyle=modern
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
AllowUNCPath=no
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes
SetupLogging=yes

; 卸载信息（Inno 默认写 HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall）
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

; 安装包自身
OutputDir=..\dist_release
OutputBaseFilename=HandwritingNotebook-{#MyAppVersion}-Setup
SetupIconFile=..\assets\app.ico
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=2

[Languages]
; 中文优先：LanguageID=$0804 与中文系统 UI 语言匹配；英文作为回退。
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 可选：注册 .note 打开方式（只写 HKCU 的 Classes\OpenWithProgids，不改系统默认）
Name: "associate"; Description: "注册 .note 笔记文件的打开方式（不会抢占默认程序）"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
; PyInstaller onedir 产物整目录搬到安装目录（_internal 子目录必须保留相对结构）
Source: "{#SourceRoot}\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 桌面快捷方式：同名覆盖旧「源码版」快捷方式（目标改为安装目录里的 exe）。
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppName}"
; 开始菜单：文件夹「手写笔记本与PDF批注」+ 程序/卸载两个快捷方式。
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Comment: "卸载 {#MyAppName}"

[Registry]
; ---- 可选：.note 打开方式（任务 associate；卸载时删干净；不动 .note 默认值）----
Root: HKCU; Subkey: "Software\Classes\HandwritingNotebook.note"; ValueType: string; ValueName: ""; ValueData: "手写笔记本与PDF批注笔记"; Flags: uninsdeletekey; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\HandwritingNotebook.note\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\HandwritingNotebook.note\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate
; 只登记到「打开方式」列表（OpenWithProgids），不写 .note 的默认 ProgID。
; 注意：Inno 的 ValueType: none **不会创建值**（只建 key）——实测装完 OpenWithProgids 是空的，
; 「打开方式」列表里看不到本程序。这里用空字符串值（REG_SZ），资源管理器同样识别；
; 真实机器上的 5.3.0 安装包已按此修正（2026-11-08 安装验证发现）。
Root: HKCU; Subkey: "Software\Classes\.note\OpenWithProgids"; ValueType: string; ValueName: "HandwritingNotebook.note"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate

[Run]
; 安装完成后可选运行（静默安装时跳过，CI 不会被 GUI 卡住）
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 用户数据（%LOCALAPPDATA%\HandwritingNotebook\ 的 logs/设置/批注兜底）**不**删：
; 卸载程序只清安装目录与它自己创建的快捷方式/注册表项。

[Code]
// ---------------------------------------------------------------------------
// 安装位置策略（2026-11 用户硬性要求：程序本体尽量不占 C 盘）
// ---------------------------------------------------------------------------
// 1. D:\Apps\HandwritingNotebook —— D 盘存在且能创建/写入时优先（减少 C 盘占用）；
// 2. %LOCALAPPDATA%\Programs\HandwritingNotebook —— 没有 D 盘或 D 盘不可写时回退，
//    保证普通公共用户机器也能安装。
// 说明：桌面/开始菜单快捷方式与卸载信息按 Windows 规范仍写入用户配置目录（C:），
//       这不属于「程序安装物」；真正占空间的 exe/_internal 全在 D 盘安装目录。
// ---------------------------------------------------------------------------
function GetDefaultInstallDir(Param: String): String;
var
  BaseDir: String;
begin
  if DirExists('D:\') then
  begin
    BaseDir := 'D:\Apps';
    if ForceDirectories(BaseDir) then
    begin
      Result := BaseDir + '\HandwritingNotebook';
      Exit;
    end;
  end;
  Result := ExpandConstant('{localappdata}\Programs\HandwritingNotebook');
end;
