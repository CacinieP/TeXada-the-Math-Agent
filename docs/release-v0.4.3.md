# TeXada v0.4.3

Release date / 发布日期：2026-11-04（Asia/Shanghai）。

v0.4.3 是窗口生命周期和模型下载恢复的修复版，包含 [PR #51](https://github.com/CacinieP/TeXada-the-Math-Agent/pull/51)。保留 v0.4.2 的公式识别、转写、编辑与排版范围、直接提交策略、模型及安全依赖。

[下载 Release](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/tag/v0.4.3) · [完整 diff：v0.4.2…v0.4.3](https://github.com/CacinieP/TeXada-the-Math-Agent/compare/v0.4.2...v0.4.3) · [CHANGELOG](../CHANGELOG.md#043---2026-11-04) · [使用指南](../README.md)

## 相比 v0.4.2 的变化

| 场景 | v0.4.2 | v0.4.3 |
| --- | --- | --- |
| 关闭主窗口 | 最后窗口关闭可能正常退出应用，并终止本应用持有的后端 | 阻止主窗口销毁并改为隐藏，可从托盘或现有快捷键恢复；显式 Quit 仍退出 |
| 下载传输中断或短响应 | 某些错误会丢失可续传的片段 | 保留已接收前缀，重试使用 Range；最终文件仍按固定 SHA256 验证 |
| 下载流结束 | EOF 或单文件完成可能误报整批成功 | 仅收到明确的整批成功结束事件才显示完成；中断、坏流和失败允许重试 |
| 进度与重试 | 全缓存完成、重复点击、按钮恢复、跨文件速度及翻译参数存在缺陷 | 修复这些状态，并在各文件开始时重置速度和剩余时间基线 |

增加关闭、退出码和本应用持有后端的生命周期日志；日志不记录公式输入或凭据。非法范围、超长下载和最终摘要不符仍会拒绝，取消不会制造成功状态。

这些修复覆盖已确认的代码行为；它们不证明 #50 中两次历史正常退出的具体触发原因。该原因仍未知。

## 安装包与升级

| 平台 | v0.4.3 安装包 |
| --- | --- |
| macOS Apple Silicon | `TeXada_0.4.3_aarch64.dmg` |
| macOS Intel | `TeXada_0.4.3_x64.dmg` |
| Windows x64 | `TeXada_0.4.3_x64-setup.exe` |
| Linux x64，Debian/Ubuntu | `TeXada_0.4.3_amd64.deb` |
| Linux x64，AppImage | `TeXada_0.4.3_amd64.AppImage` |

安装包包含桌面程序、Python 后端、离线 KaTeX 与内置 llama-server；模型权重和视觉投影文件仍在设置中单独下载。已有内置、Ollama 和 OpenAI-compatible 设置继续保留。

升级前从设置导出数据备份，结束旧版本的任务并选择 **Quit / 退出**，再安装对应平台的新包。打开后核对关于页的 `v0.4.3`。已下载且摘要正确的模型可复用，无需为升级重新下载。旧 v0.4.2 标签和安装包保留原样。

macOS 需要 13.3+；最终两包必须通过 Developer ID 签名、公证、贴票和 Gatekeeper 检查。Windows 安装包未做代码签名。Linux 验证范围为原生 Ubuntu 24.04 x64 的 deb 和 AppImage，不代表任意发行版与桌面环境均已验证。

<a id="linux-installation"></a>

### Linux 安装

Debian/Ubuntu：

```bash
sudo apt install ./TeXada_0.4.3_amd64.deb
```

AppImage：

```bash
chmod +x TeXada_0.4.3_amd64.AppImage
./TeXada_0.4.3_amd64.AppImage
```

需要图形桌面和兼容系统库。若系统缺少所需 FUSE 支持，可在独立目录提取运行，避免覆盖已有 `squashfs-root`：

```bash
./TeXada_0.4.3_amd64.AppImage --appimage-extract
./squashfs-root/AppRun
```

Linux 点击公式会复制，需手动粘贴；系统光标自动键入尚未实现。Wayland 集成与 Linux 快捷键尚无独立人工验收，Xvfb 安装启动检查不覆盖这些交互。

## 验证范围与发布门槛

修复合并提交 `39f2c56e26bda894dd9435e31a65b3a892357200` 的 [五组主线 CI 全部通过](https://github.com/CacinieP/TeXada-the-Math-Agent/actions/runs/41796890563)：1304 项 Python 通过、14 跳过，90 项前端通过，macOS/Windows 各 3 项关闭策略回归，以及 Windows 进程生命周期、Linux glib 优化迭代器回归和依赖审计。测试覆盖真实 HTTPX 中断与 Range 恢复、完整性拒绝、取消和整批结束事件，以及真实 WHATWG ReadableStream 和中英文进度显示。

修复源码的本地 adhoc debug 候选已完成包内后端启动、真实 KaTeX 和确定性零模型检查；缓存模型的 3 条 done/skipped 事件之后恰有 1 条成功结束事件。模型文件未变，未启动额外模型进程。这个检查不是已公证发行包的安装验收。

正式发布流程先构建草稿资产，再核对同一来源的五个安装包、逐包 `native-smoke-*.json`、两份 macOS 公证记录、`release-manifest.json` 与 `SHA256SUMS`。全部门槛通过后才发布为稳定版本。v0.4.3 最终产物的实际结果以其 [Desktop Release 工作流](https://github.com/CacinieP/TeXada-the-Math-Agent/actions/workflows/release-desktop.yml) 和 Release 附件为准；上述源码 CI、本地候选与 v0.4.2 记录不替代该结果。

**仍待原生复验：**用户正在使用测试窗口，尚未对本修版重跑正常启动、下载中关闭主窗口后持续传输、托盘恢复、托盘 Quit 和 Cmd+Q，也未完成连续 GUI 冷下载到推理的整条验收。[#50](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/50) 保持打开；[验证步骤](issue50-download-lifecycle.md) 和历史退出观察保留。默认 Cmd+Q 可能不产生 ExitRequested 日志，需核对真实进程和 API 状态。

<a id="known-limits"></a>

## 质量范围与已知限制

本版没有改变模型、转写提示或公式提交策略。自然语言、OCR 与补全候选经工具检查后直接提交；修改范围守卫继续拒绝越界结果，Studio 移交仍要求来源与版本绑定的审阅。请将输出与原文对照。

v0.4.2 的固定 48 例、冷下载和新权重推理记录仍属于 [v0.4.2](release-v0.4.2.md) 及其 [验收包](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/download/v0.4.2/TeXada-0.4.2-validation.zip)。其六项冻结门槛为 **4 true / 2 false**，不因本次发布改写为成功；不将本版的零模型检查计为新模型/OCR 实测。

编译、渲染、提交、HTTP 成功或结构 MATCH 均不证明数学准确。独立人工转写复核、真实扫描/手写及 Windows/Intel/Linux 实机模型质量仍在 [#46](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/46) 跟踪。产品不提供求值、化简、解题或证明；积分和导数记号仍可转写。

## English

v0.4.3 fixes main-window lifecycle and model-download recovery in [PR #51](https://github.com/CacinieP/TeXada-the-Math-Agent/pull/51). Closing the main window now hides it instead of destroying it; restore it through the tray or existing shortcut. Explicit Quit remains available. Window, exit-code and owned-backend logs exclude formula input and credentials.

Interrupted transfers and short responses retain their received prefix for Range retry. Final files still require the pinned SHA256. Batch completion requires an explicit successful terminal rather than EOF or one finished file. Cached completion, duplicate clicks, reader/button cleanup, per-file rate/ETA and translated progress are fixed. Invalid ranges, overlong bodies, hash failures and cancellation cannot become successful completion.

Packages cover Apple Silicon/Intel macOS DMGs, Windows x64 NSIS and Linux x64 deb/AppImage. Models download separately and existing settings remain. macOS requires 13.3+; Developer ID signing, notarization, stapling, Gatekeeper and all five native package checks gate publication. Windows is unsigned. Linux coverage is Ubuntu 24.04 x64; formula clicks copy for manual paste.

The merged fix passed all five source CI jobs (1304 Python passed / 14 skipped, 90 frontend tests, macOS/Windows close-policy regressions, process lifecycle, glib and audits). Its local adhoc debug backend passed deterministic rendering and cached-download terminal checks. Final v0.4.3 installer acceptance belongs to the tagged workflow and attached manifest, checksums, native reports and notarization records.

Native close/restore/Quit and continuous GUI cold-download acceptance remain pending in [#50](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/50); the user requested that the active test window remain untouched. The historical normal-exit trigger is unknown. Source tests do not replace native interaction or prove that trigger.

Models and formula policy are unchanged. The v0.4.2 fixed evaluation remains historical with four true and two false frozen gates; no new model-quality result is claimed. Compilation, rendering, commits and strict MATCH do not establish mathematical accuracy. Independent human review, real scans/handwriting and target-machine model quality remain tracked in [#46](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/46).
