# 设计文档：本地运行时平台 — 内置 llama-server（Iteration 1.5 / v0.4.3）

Status: Proposed（待评审）

日期：2026-09-19

所属层：Planner（模型运行时基础设施）

对应 ADR：[016-local-model-runtime-llama-server](../adr/016-local-model-runtime-llama-server.md)

对应路线图：[iteration-roadmap-v0.4.1-to-v1.0](../iteration-roadmap-v0.4.1-to-v1.0.md) §3 Iteration 1.5

## 1. 背景与目标

本地推理当前依赖外部安装的 Ollama。本迭代引入**内置 llama-server sidecar
作为默认本地运行时**：应用内一键启停、首次拉取模型后按需加载，Ollama 与
OpenAI-compatible 保留为兼容后端。

**唯一要解的问题**：本地推理从“外部依赖 Ollama”变为“应用内一键启停、
首次拉取后按需加载”。

## 2. 现状接入面（已核实）

| 组件 | 现状 | 迁移影响 |
|---|---|---|
| `MiniCPMModel`（core/model.py） | 用 `config.active_base_url` 构造 AsyncOpenAI，只说 OpenAI-compatible `/v1` | **零改动**——运行时无关，这是迁移成本低的关键 |
| `BackendManager`（core/backend.py） | Ollama 专用：探测 `/v1/models`、`ollama serve` 子进程自启 | 新增并列实现 `LlamaServerManager`，同接口 |
| `TeXadaConfig` | `backend: Literal["ollama", "openai_compatible"]`，`ollama_host`，`model_name`，`vision_model_name` | 扩展为三值，新增 llama-server 专属字段 |
| Tauri 打包 | `externalBin: binaries/texada-backend`（Python sidecar） | 增加 `binaries/llama-server`，随平台三构建 |
| 前端 | `settings.backend` 选择器 + 状态栏（ready/partialReady/missingModel…） | 增加第三选项 + 启停按钮 + 首拉入口 |
| FastAPI | `/api/runtime` 运行时配置、`/api/settings` 设置更新 | 新增启停/下载进度端点 |

## 3. 架构

```text
Settings ──► backend = llama_server（默认） | ollama | openai_compatible
                │
                ▼
        LlamaServerManager（新，core/llama_server.py）
        接口与 BackendManager 对齐：
        ensure_ready / ensure_vision_ready / get_status /
        start / stop / pull_model（下载进度）
                │
                ▼
        llama-server 进程（router 模式，单进程双模型）
        --models-dir ~/.texada/models --port 8080
        按需加载 / 空闲卸载；OpenAI-compatible /v1
                │
                ▼
        MiniCPMModel（零改动） ──► 同一 Planner/Tools/Formula Runtime
```

三个设计决定：

1. **router 模式单进程托管双模型**。llama-server router 按请求的 `model`
   字段路由，未加载模型自动加载（`--no-models-autoload` 可关），支持
   空闲卸载。模型文件命名与 `config.model_name` /
   `vision_model_name` 对齐（文件名即模型名），`/v1/models` 自动转发
   状态。
2. **模型获取是显式用户动作**。安装包只含 `llama-server` 二进制
   （macOS aarch64/x64、Windows x64），权重首次由应用内下载到
   `~/.texada/models/`（文本 GGUF ~1.2GB + 视觉 GGUF ~0.5GB +
   mmproj ~1.1GB），带进度、取消、HF 镜像选项。
3. **启停是应用内能力**。`LlamaServerManager.start()` 拉起进程并等待
   `/v1/models` 就绪；`stop()` 优雅终止；状态机扩展为
   Ready / Loading / Model missing / Stopped / Disconnected，暴露给
   FastAPI 端点与前端按钮。

## 4. 关键接口

```python
# config.py 新增字段
backend: Literal["llama_server", "ollama", "openai_compatible"] = "llama_server"
llama_server_host: str = "http://127.0.0.1:8080"
llama_server_binary: str = ""          # 空 = 打包路径或 PATH 查找
llama_models_dir: str = ""             # 空 = ~/.texada/models
llama_context_size: int = 4096
llama_gpu_layers: int = 99             # Metal：全量 offload（默认 auto 亦可）
llama_models_max: int = 2              # router 同时驻留模型数（8GB 内存控制）
llama_idle_sleep_seconds: int = 300    # 空闲休眠秒数（-1 禁用；=ADR-016 的“空闲卸载”）

# core/llama_server.py
class LlamaServerManager:
    async def ensure_ready(self) -> bool            # 未运行则拉起，等待就绪
    async def ensure_vision_ready(self) -> bool     # 视觉模型（GGUF+mmproj）就绪
    async def start(self) -> bool
    async def stop(self) -> bool
    async def pull_model(self, role: str) -> AsyncIterator[dict]  # 下载进度流
    def get_status(self) -> dict                    # 同步，供 UI
```

模型文件约定（`~/.texada/models/`）：

- 文本：`MiniCPM5-2B-Q4_K_M.gguf`（router 中模型名 `text`）
- 视觉：`MiniCPM-V-4.6-Q4_K_M.gguf` + `mmproj-MiniCPM-V-4.6-F16.gguf`
  （模型名 `vision`，`--mmproj` 随模型声明）

调用侧（`config.active_model_name`）在 llama_server 后端返回
`"text"` / `"vision"` 路由名，其余后端保持原值——`MiniCPMModel`
与 `/api/agent` 无需任何改动。

## 5. 验收门槛（路线图 §3 Iteration 1.5）

1. **行为中性**：`eval/run_real_baseline.py --mode live` 在 llama-server
   后端上的结构通过率不低于 Ollama 基线 28/95（29.5%）——允许波动，
   不允许系统性退化；`reasoning_effort: none` 行为一致（v0.4.1 特性）。
2. **按需加载实测**：8GB 机器双模型加载内存、冷启动延迟、空闲卸载
   回收三项数据记录到报告（沿用 A18 Pro 实测先例）。
3. **打包**：macOS 公证与 Windows NSIS 流水线纳入 llama-server 二进制；
   `cargo check` 通过。

## 5.5 实测验证记录（2026-09-19，llama.cpp b11046 macOS arm64）

已用真实预编译二进制核实（消除设计猜测）：

| 事实 | 验证结果 |
|---|---|
| 版本输出 | `version: 0.4.1-dev (build 11046, commit ...)`；解析 `build N`，钉死 ≥ b9049 |
| router 目录模式 | `--models-dir PATH` 存在 |
| mmproj 声明 | **必须** `--models-preset` INI（`[vision] model=... mmproj=...`），models-dir 无法携带投影器 → 启动时动态生成 preset |
| 按需加载 | `--models-autoload`（默认开，`--no-models-autoload` 可关） |
| 空闲卸载 | `--sleep-idle-seconds N`：空闲 N 秒后 server 休眠释放显存（-1 禁用）→ 配置字段 `llama_idle_sleep_seconds` |
| 内存控制 | `--models-max N`：同时驻留模型数上限 |
| GPU 卸载 | `-ngl/--n-gpu-layers` 默认 auto（Metal 自动）；显式 99 亦可 |
| 上下文 | `-c/--ctx-size N`（0=读模型默认） |

## 6. 风险与验证项（ADR-016 清单）

| 风险 | 验证方式 |
|---|---|
| `reasoning_effort: none` 的 `extra_body` 在 llama-server 兼容性 | live 基线实测 + 单点探测脚本 |
| llama.cpp 版本（MiniCPM-V 4.6 需 b9049+） | 构建配置钉死版本号，启动时校验 |
| Metal 默认 `-ngl`、上下文 4096 与 90s 推理超时 | 实测 p50/p95 延迟对比 |
| 首次下载失败模式（网络中断、镜像不可达） | 进度端点返回错误态，不产生半截文件（`.part` 临时名） |
| 双运行时状态/probe 代码路径同步 | 两个 Manager 共用就绪探测逻辑（同一函数） |

## 7. 不做

- 不移除 Ollama 兼容分支（保留为回退通道）
- 不做模型目录/量化自选 UI（单模型每角色稳定后再议）
- 不做 Linux 打包（当前 release matrix 无 Linux）
