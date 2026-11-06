# TeXada v0.4.4

发布日期 / Release date 2026-11-06（Asia/Shanghai）。

v0.4.4 提供七种参数化矩阵预设、修订绑定结构检查、有限求和与区域积分保真，
以及 macOS 插入前的应用级焦点交接和阶段诊断。发布源码包含本批矩阵、求和
和桌面修复，最终安装产物及检查结果由本次 Release 附件记录。

[下载 Release](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/tag/v0.4.4) · [完整 diff](https://github.com/CacinieP/TeXada-the-Math-Agent/compare/v0.4.3...v0.4.4) · [CHANGELOG](../CHANGELOG.md#044---2026-11-06) · [使用指南](../README.md)

## 本版变化

- 预设页提供通用、三对角、单位、零、对角、上三角和下三角七种矩阵，支持
  类型搜索、具体或符号尺寸、括号、索引起点和展开方式。通用与零矩阵支持
  矩形尺寸，其他类型使用方阵。通用和三对角的有限自然语言句式共用生成器。
- `POST /api/matrix` 复用 Agent 结果、历史、日志及备份。实际候选经过编译、
  渲染和当前 revision 的结构检查。已验证的矩阵预设使用 32768 字符预算，
  大公式可通过历史、日志与备份往返。参数编辑会使旧结果失效。
- 有限求和描述保留唯一求和项、整数或集合索引域、函数下标及积分区域。
  缺省范围和积分测度使用一般记号，缺失或冲突索引显示补充提示。带上下文
  的请求进入规划，并记录有限约束的实际检查范围。
- macOS 插入依次隐藏窗口和应用，隐藏错误返回调用方。显示命令、托盘与
  快捷键共用应用恢复、窗口显示和聚焦路径。诊断日志只记录阶段和布尔值。
- 正式 v0.4.3 的原始矩阵、求和及区域积分失败输出成为固定回归，检查语法、
  需求结构与提交状态。旧预设、历史参数恢复和备份兼容性同时覆盖。

## 安装包与升级

| 平台 | v0.4.4 安装包 |
| --- | --- |
| macOS Apple Silicon | `TeXada_0.4.4_aarch64.dmg` |
| macOS Intel | `TeXada_0.4.4_x64.dmg` |
| Windows x64 | `TeXada_0.4.4_x64-setup.exe` |
| Linux x64，Debian/Ubuntu | `TeXada_0.4.4_amd64.deb` |
| Linux x64，AppImage | `TeXada_0.4.4_amd64.AppImage` |

安装包包含桌面程序、Python 后端、离线 KaTeX 和 llama-server build11669。
模型权重与视觉投影文件在设置中单独下载。升级前可从设置导出备份，结束
旧版本任务并选择 Quit / 退出，再安装对应平台的新包。打开后核对关于页
的 `v0.4.4`，已有摘要正确的模型可直接复用。

macOS 要求 13.3+，发布门槛包括 Developer ID 签名、公证、贴票和 Gatekeeper
检查。Windows 安装包采用 unsigned NSIS。Linux 安装启动检查覆盖原生
Ubuntu 24.04 x64 的 deb 和 AppImage。

<a id="linux-installation"></a>

### Linux 安装

Debian/Ubuntu 使用包管理器安装。

```bash
sudo apt install ./TeXada_0.4.4_amd64.deb
```

AppImage 添加执行权限后运行。

```bash
chmod +x TeXada_0.4.4_amd64.AppImage
./TeXada_0.4.4_amd64.AppImage
```

需要图形桌面和兼容系统库。需要独立解包运行时，在新的空目录执行。

```bash
./TeXada_0.4.4_amd64.AppImage --appimage-extract
./squashfs-root/AppRun
```

Linux 的公式点击流程使用复制和手动粘贴。Wayland、快捷键及目标平台模型
质量的独立验收继续由 #46 跟踪。

## 发布产物与证据范围

GitHub Actions 将统一版本及来源提交绑定到五个安装包，分别执行安装副本
启动、包内后端启动、确定性编译渲染和提交检查。macOS 同时记录签名、
公证、贴票及 Gatekeeper 结果。发布附件中的 `release-manifest.json`、
`SHA256SUMS`、逐包 `native-smoke-*.json` 和两份公证记录共同标识实际产物。
[Desktop Release 工作流](https://github.com/CacinieP/TeXada-the-Math-Agent/actions/workflows/release-desktop.yml)

问题基线来自 2026-11-06 对官方 v0.4.3 macOS arm64 包的 14 条原始请求回放，
使用包内运行时和真实本地 Q4 模型。原始 run ID、输入、输出、配置及摘要
保留在 ADR-018 和固定公式样例中。v0.4.4 的源码回归针对这些失败建立结构
和提交断言。[正式基线证据](adr/018-parameterized-matrix-candidates.md#problem-and-current-release-evidence)

后续 main `7567ebaf3c17404049441cbcb6846d8cd777030a` 的本地 ad-hoc 候选完成
14 条复放，其中 13 条提交，C08 缺失区域下标时返回补充提示。该候选覆盖
PR #62/#63，额外矩阵类型与焦点交接分别来自后续 PR #66/#65。各批记录保留
自己的源码与产物身份，最终 v0.4.4 安装结果以本次 Actions 附件为准。

<a id="known-limits"></a>

## 待复验范围

- macOS 焦点交接修复后的目标文稿实际收到完整公式、托盘或快捷键恢复及
  显式 Quit，继续由 #64 跟踪。已有受控前台采样记录的是早期候选状态，
  点击与粘贴阶段由新增诊断补充。[#64](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/64)
- 连续 GUI 冷下载、下载中关闭与恢复及历史会话退出原因继续由 #50 跟踪。
  [#50](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/50)
- 独立公式转写复核、真实扫描或手写、跨平台模型质量继续由 #46 跟踪。
  Linux MiniRacer 初始化退出的复现与根因调查归 #54。
  [#46](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/46) · [#54](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/54)

编译与渲染记录语法和呈现结果，严格 MATCH 记录声明范围内的结构约束。
使用公式前请逐项对照原文。产品支持公式识别、转写、编辑和排版。

## English

v0.4.4 adds seven parameterized matrix presets with type search, concrete or
symbolic dimensions, brackets, index origin and display controls. General and
zero matrices support rectangular shapes. Finite general/tridiagonal
descriptions share the generator. The matrix Agent API records compilation,
rendering and actual-candidate structure evidence for the current revision,
with history, backup and stale-result handling.

Finite sum descriptions preserve terms, integer/set domains and indexed
functions and integration regions. Unspecified bounds and measures use general
notation. Missing or conflicting indices produce a clarification request.
Contextual requests enter planning with declared checking coverage.

macOS insertion hides the window and application before requesting a paste,
propagates hide errors and records content-free stage diagnostics. Commands,
tray and shortcut restoration share the application/window focus path. Native
target-text receipt, restoration and explicit Quit acceptance continue under
#64. Continuous GUI download/session checks belong to #50, and independent
formula/OCR and target-machine model-quality work belongs to #46.

The official v0.4.3 replay supplies the recorded failure baseline. The later
ad-hoc candidate from main 7567eba covers PR #62/#63. Final v0.4.4 package
identity and installed results belong to this release's Actions artifacts,
manifest, checksums, per-package native reports and macOS notarization records.
Publication requires all five package gates and both macOS notarization gates.

Packages include Apple Silicon/Intel macOS DMGs, Windows x64 NSIS and Linux
x64 deb/AppImage. Models download separately. macOS requires 13.3+ with
Developer ID signing, notarization, stapling and Gatekeeper checks. Windows
uses unsigned NSIS. Linux package checks cover Ubuntu 24.04 x64, with formula
copying and manual paste as its desktop insertion path.
