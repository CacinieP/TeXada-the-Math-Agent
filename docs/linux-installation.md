# Linux installation / Linux 安装

## 中文

从 [GitHub 最新正式发布](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/latest) 下载 Linux x86_64 资产。Debian 或 Ubuntu 可使用 `.deb`，由 APT 处理声明的依赖。也可以直接运行 AppImage。将下面的 `<version>` 替换为下载的文件版本。

```bash
sudo apt install ./TeXada_<version>_amd64.deb
```

```bash
chmod +x ./TeXada_<version>_amd64.AppImage
./TeXada_<version>_amd64.AppImage
```

如果 AppImage 明确报 FUSE 不可用，可用 `APPIMAGE_EXTRACT_AND_RUN=1 ./TeXada_<version>_amd64.AppImage` 尝试解包运行。可用发布附件中的 `SHA256SUMS` 校验下载的文件。

从 v0.4.10 起，全新配置会根据系统 locale 选择界面语言。中文 locale 默认中文，其他 locale（包括 `C.UTF-8`）默认英文。设置里保存过的语言优先。

安装包内含 `llama-server`。使用内置后端时，可在设置里下载 MiniCPM-V 4.7 1B Q4_K_M 权重和 F16 视觉投影，下载后可在本地执行公式转写与图片 OCR。预留约 2 GiB 磁盘空间存放模型文件。

v0.4.10 的 Ubuntu 22.04 发布 CI 在 glibc 2.35 基线上构建两个 Linux 安装包，并使用 Xvfb 在关闭外网、保留本机回环时验证启动、英文首屏和确定性公式渲染。正式发布的 x64 AppImage 随后通过 AppImageHub 测试。 [发布工作流](https://github.com/CacinieP/TeXada-the-Math-Agent/actions/runs/43581742151) · [AppImageHub 复测](https://github.com/AppImage/appimage.github.io/pull/11396#issuecomment-6875598626)

独立 Ubuntu 24.04.5 x86_64 实测使用语言修复分支的 v0.4.9 CI 候选 AppImage，硬件为 Intel Core i5-7200U（2 核 4 线程），系统识别内存约 11 GiB。该机通过 Xvfb 验证英文首屏，通过打包后的本地 API 验证 CPU 文本转写和图片 OCR。 [Ubuntu 24.04 实测与截图](validation/2026-11-14-ubuntu24-appimage/README.md)

Linux 点击公式后可手动粘贴。图形桌面的双击启动、Wayland 全局快捷键、托盘和手动粘贴属于独立验收项。

## English

Download the Linux x86_64 asset from the [latest public GitHub release](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/latest). On Debian or Ubuntu, install the `.deb` with `sudo apt install ./TeXada_<version>_amd64.deb` so APT can resolve its declared dependencies. For the AppImage, make it executable and run it as shown above. If it reports that FUSE is unavailable, try prefixing the command with `APPIMAGE_EXTRACT_AND_RUN=1`. Verify the downloaded file against the release's `SHA256SUMS`.

Starting with v0.4.10, a fresh profile follows the system locale. Chinese locales start in Chinese and other locales, including `C.UTF-8`, start in English. A saved language choice takes precedence.

The installer includes `llama-server`. In Settings, download the MiniCPM-V 4.7 1B Q4_K_M weights and F16 visual projector for local formula transcription and image OCR. Allow about 2 GiB of disk space for the model files.

The v0.4.10 release workflow built both Linux installers on Ubuntu 22.04 with a glibc 2.35 baseline. Under Xvfb, it checked startup, the English first window and deterministic rendering with external networking disabled and loopback available. AppImageHub passed the public x64 AppImage. [Release workflow](https://github.com/CacinieP/TeXada-the-Math-Agent/actions/runs/43581742151) · [AppImageHub test](https://github.com/AppImage/appimage.github.io/pull/11396#issuecomment-6875598626)

A separate Ubuntu 24.04.5 x86_64 machine ran the v0.4.9 CI candidate from the locale-fix branch. The tester used a 2-core, 4-thread Intel Core i5-7200U and about 11 GiB of visible RAM to verify the English window under Xvfb and CPU text and image inference through the packaged local API. [Hardware test and screenshot](validation/2026-11-14-ubuntu24-appimage/README.md)

Clicking a formula copies it for manual paste on Linux. Interactive desktop launch, Wayland shortcuts, tray integration and manual clipboard use have separate acceptance requirements.
