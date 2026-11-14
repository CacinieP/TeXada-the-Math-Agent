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

Ubuntu 22.04 CI 在 glibc 2.35 基线上构建并检查两个包，用 Xvfb 在关闭外部网络但保留本机回环的环境中验证启动、英文窗口和确定性公式渲染。独立 Ubuntu 24.04.5 x86_64 机器实测使用 Intel Core i5-7200U（2 核 4 线程），系统识别内存约 11 GiB。该机在 Xvfb 验证了英文首屏，并通过打包后的本地 API 验证了 CPU 文本转写和图片 OCR。[Ubuntu 24.04 实测与截图](validation/2026-11-14-ubuntu24-appimage/README.md)

Linux 点击公式后可手动粘贴。图形桌面的双击启动、Wayland 全局快捷键、托盘和手动粘贴属于独立验收项。

## English

Download the Linux x86_64 asset from the [latest public GitHub release](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/latest). On Debian or Ubuntu, install the `.deb` with `sudo apt install ./TeXada_<version>_amd64.deb` so APT can resolve its declared dependencies. For the AppImage, make it executable and run it as shown above. If it reports that FUSE is unavailable, try prefixing the command with `APPIMAGE_EXTRACT_AND_RUN=1`. Verify the downloaded file against the release's `SHA256SUMS`.

Starting with v0.4.10, a fresh profile follows the system locale. Chinese locales start in Chinese and other locales, including `C.UTF-8`, start in English. A saved language choice takes precedence.

The installer includes `llama-server`. In Settings, download the MiniCPM-V 4.7 1B Q4_K_M weights and F16 visual projector for local formula transcription and image OCR. Allow about 2 GiB of disk space for the model files.

CI builds on Ubuntu 22.04 with a glibc 2.35 baseline and checks both packages under Xvfb with external networking disabled and loopback available. A separate Ubuntu 24.04.5 x86_64 machine with a 2-core, 4-thread Intel Core i5-7200U and about 11 GiB of visible RAM verified the English window under Xvfb and CPU text and image inference through the packaged local API. [Hardware test and screenshot](validation/2026-11-14-ubuntu24-appimage/README.md)

Clicking a formula copies it for manual paste on Linux. Interactive desktop launch, Wayland shortcuts, tray integration and manual clipboard use have separate acceptance requirements.
