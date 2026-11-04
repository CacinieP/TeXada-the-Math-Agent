# TeXada v0.4.2

Release date / 发布日期：2026-11-04（Asia/Shanghai）。

v0.4.2 整合 v0.4.1 以来已合并的 Beta/RC 产品修复与 [PR #45 依赖安全修复](https://github.com/CacinieP/TeXada-the-Math-Agent/pull/45)。这是公式识别、转写、编辑和排版工具的正式发布；工程验收不等于模型准确率或数学证明。

[下载 Release](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/tag/v0.4.2) · [中英文使用指南](../README.md) · [完整 CHANGELOG](../CHANGELOG.md#042---2026-11-04)

## 安装包与升级

| 平台 | v0.4.2 安装包 |
| --- | --- |
| macOS Apple Silicon | `TeXada_0.4.2_aarch64.dmg` |
| macOS Intel | `TeXada_0.4.2_x64.dmg` |
| Windows x64 | `TeXada_0.4.2_x64-setup.exe` |
| Linux x64，Debian/Ubuntu | `TeXada_0.4.2_amd64.deb` |
| Linux x64，AppImage | `TeXada_0.4.2_amd64.AppImage` |

安装包包含桌面程序、Python 后端、离线 KaTeX 和内置 llama-server；不包含模型权重或视觉投影文件。首次使用可在设置中选择内置后端、下载模型，然后启动服务。已有 Ollama 和 OpenAI-compatible 配置继续保留，不因升级强制迁移。

升级前建议从设置页导出自己的数据备份。停止旧版本的生成和下载任务后再退出应用，安装对应平台的新包；打开后核对关于页的 `v0.4.2` 和设置中的后端、模型名称。旧 Beta/RC 安装包保留原样，合并源码不会更新已经安装的程序。

macOS 需要 13.3 或更新版本；签名、公证与实际安装启动检查以最终产物记录为准。Windows NSIS 未做代码签名。Linux 兼容范围以最终 Ubuntu 原生构建、deb 安装与 AppImage 启动记录为准，不推广为任意发行版或所有桌面环境已验收。

<a id="linux-installation"></a>

## Linux 安装

Debian/Ubuntu 使用包管理器安装下载的 deb，并按提示补齐系统依赖：

```bash
sudo apt install ./TeXada_0.4.2_amd64.deb
```

也可选择 AppImage：

```bash
chmod +x TeXada_0.4.2_amd64.AppImage
./TeXada_0.4.2_amd64.AppImage
```

需要图形桌面及兼容的系统库。AppImage 仍有系统运行要求，不代表完全静态；若系统未提供所需 FUSE 支持，可按 AppImage 的提取运行方式使用：

```bash
./TeXada_0.4.2_amd64.AppImage --appimage-extract
./squashfs-root/AppRun
```

在自己的独立下载目录提取，避免覆盖已有 `squashfs-root`。原生 CI 中的虚拟显示启动用于检查包的可执行性、打包后端和确定性渲染，不代替真实桌面人工交互或 Linux 模型性能评测。

## 本版保留的操作行为

- 自然语言、OCR、补全候选通过共享工具检查后**直接提交**，进入历史并可复制；macOS/Windows 支持系统光标键入，Linux 点击公式后需手动粘贴。不恢复早期 RC 的逐条采用门禁。请仍对照原文核对结果。
- `MutationScopeGuard` 继续限制越界修改；越界时保留失败状态。`/api/convert` 仍是只预览的兼容入口；Studio 单公式移交仍使用来源/版本绑定与待审阅决定。
- 补全页的实验性 Ghost Text 只在光标处插入建议；Tab 接受、Esc 只清除建议，下一次 Esc 才隐藏窗口。编辑、移动光标、失焦或切换页签会使旧建议及等待中的响应失效。
- 内置模型与 projector 在启动前校验固定 SHA256。下载支持进度、速度、剩余时间与续传；仅清理本应用启动的运行时。
- 设置中内置、Ollama、OpenAI-compatible 三条路径分别保留配置；文本与 OCR 的远程连接和密钥分离。模型列表可见与推理已验证是不同状态。
- 合并作用域与算符保护、过期来源拒绝、一次有界导出格式恢复、设置布局和运行日志修复，完整历史见 CHANGELOG。

## 安全更新

同步锁定 Pillow 13.0.0、certifi 2026.10.23、setuptools 84.2.1、rustls 0.23.46 / rustls-webpki 0.103.16 和 KaTeX 0.18.2。离线前端、Python wheel 与桌面后端使用同一 KaTeX JavaScript，字体与许可随包提供。

GTK3 依赖要求 glib 0.18，不能直接换成不兼容的 0.20。此版本保留完整官方 glib 0.18.5 crate 和许可，仅回移上游 `VariantStrIter` 的两行修复，由 Cargo path patch 选择，并增加优化构建的迭代器回归。它不是官方发布的 0.18 修复版；版本扫描可能仍显示相关告警，不能据此伪造版本或忽略结果。来源、原始摘要和验证方法见[依赖维护记录](dependency-security-2026-11-04.md)与[回移说明](../tauri-shell/src-tauri/vendor/README.md)。

## 工程验证与产物记录

发布流程先构建草稿资产，再核对最终安装包和报告后发布正式版。对应标签的 [Desktop Release 工作流](https://github.com/CacinieP/TeXada-the-Math-Agent/actions/workflows/release-desktop.yml) 和附带验证文件记录各平台的实际结果；本说明不预先把正在构建或尚未安装的包记作通过。

检查范围包括锁定依赖审计、Python/客户端回归、Rust 检查、glib 优化迭代器回归，以及从实际安装包启动桌面、打包后端与内置运行时，执行确定性公式编译/渲染并核对版本。Linux 增加原生 Ubuntu 下的 deb 和 AppImage 检查。确定性零模型检查不记作模型推理或 OCR 验收。

已合并的安全修复以 `dd7b55a` 为基线，其 [PR CI 记录](https://github.com/CacinieP/TeXada-the-Math-Agent/actions/runs/41774406990) 包括 Python 1206 通过/13 跳过、客户端 41 项、macOS/Windows Rust、Windows 进程管理与 Linux glib 11 项优化迭代器测试。该基线不是 v0.4.2 最终安装包的替代证明；旧 [RC.2 装机记录](rc2-validation.md) 同样只描述当时的包和人工采用策略。

<a id="known-limits"></a>

## 已知限制与后续质量工作

支持范围是公式识别、转写、编辑与排版。导数、积分、等号和原图已有答案可忠实保留，但不提供求值、化简、因式分解、解方程、求导、积分计算或证明。

例如“x 下标 k 加一”仍可能生成漏项候选，范围守卫会拒绝该结果；失败记录保留，不承诺每条输入都能自动完成。

Linux 尚未实现系统光标自动键入，点击公式回退为复制内容，需手动粘贴。Wayland 集成与 Linux 快捷键尚未经过独立人工验收；原生 CI 的 Xvfb 安装启动检查不覆盖这些桌面交互。

本次新增正式发布不宣称已完成独立人工转写复核、任意扫描页或手写验收、Windows/Intel 实机模型质量评测。适合先从清晰的排版公式截图和可对照的文本输入开始；复杂图片与记号应逐项核对。历史 Beta 中存在数学错误公式成功提交，Codex 判定也不是独立人工准确率；HTTP 成功、语法有效、严格结构 MATCH、渲染、提交和安装启动均应分别理解。

历史失败、完整参考、配置与差异保留在原报告中，不重新标为成功。真实授权图片、扫描/手写、独立人工复核及各平台实际模型表现继续作为质量工作跟踪；正式发布决定不将这些工作伪称完成。当前直接提交行为也不意味着结果已被人确认。

## English release summary

v0.4.2 consolidates the merged beta/RC work since v0.4.1 and the dependency security update. Packages cover Apple Silicon and Intel macOS, Windows x64, and Linux x64 deb/AppImage. Model weights download separately; saved provider choices remain.

NL, OCR and completion retain direct commit. Mutation-scope checks remain; Studio formula handoffs still require bound review. The release includes the built-in b11669 runtime, model/projector hash checks, resumable download progress, isolated provider settings, bounded export recovery and cursor-bound insert-only ghost text.

Security updates synchronize Python/Rust locks and offline KaTeX 0.18.2. GTK3's glib 0.18.5 uses the documented upstream source backport, not a fabricated fixed version. Final signed/notarized macOS, Windows installation and native Ubuntu deb/AppImage results belong to the tagged artifacts and their reports. Windows installers are unsigned; Linux coverage does not imply every distribution is tested.

System-cursor insertion is implemented on macOS/Windows. Linux formula clicks copy for manual paste; Wayland integration and Linux shortcuts have not received independent manual acceptance testing. Xvfb package checks do not cover those desktop interactions.

Engineering acceptance is separate from mathematical accuracy. No new independent human transcription adjudication, handwriting/real-scan acceptance or Windows/Intel model-quality result is claimed. Historical failures remain visible. Use the tool to recognize, transcribe and typeset formulas, and compare generated output with its source.
