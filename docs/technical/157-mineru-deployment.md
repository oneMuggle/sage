# MinerU 内网独立部署方案

> 文档编号：157
> 状态：待实施（2026-11-14 调研定稿）
> 适用分支：main / release/win7（服务器侧与分支无关，客户端接入两侧一致）

## 1. 背景与目标

Sage 现有的本地 OCR 子系统（RapidOCR / Tesseract）只覆盖「单张图片 → 纯文本」。对于论文 PDF 中的复杂版式、公式、跨页表格与标题层级，需要更高质量的文档解析能力。

[MinerU](https://github.com/opendatalab/mineru)（OpenDataLab 开源，4.x）提供整份文档 → Markdown 的解析管线，支持公式识别、表格结构还原、版面分析与标题分级。内网环境中部署一台带 GPU 的服务器集中运行 MinerU，Sage 作为 HTTP 客户端接入。

**目标**：

1. 在 A6000（48GB）服务器上离线部署 MinerU 4.1，`--tier standard` 档位。
2. 模型权重通过离线搬运进入内网，运行期零外网依赖。
3. Sage 侧以工具形式接入，支持 PDF/Office 文档解析为 Markdown。
4. 多台 Sage 客户端共享同一 MinerU 服务。

**非目标**：

- 不替换现有 `ocr_image` 工具（两者语义不同，并存）。
- 不在 Sage 后端进程内嵌 MinerU（Python 版本不兼容，见 §2.2）。
- 不做公有云 MinerU SaaS 接入。

## 2. 部署架构

### 2.1 拓扑

```
                内网
┌─────────────────────────┐          HTTP :8000
│ A6000 GPU 服务器         │◄─────────────────────────┐
│                         │                          │
│ systemd: mineru-kit     │         ┌────────────────┴────────────────┐
│   api-server            │         │ Sage 后端（Python 3.10 / 3.8）    │
│   --tier standard       │         │  MineruParseTool                │
│   --host 0.0.0.0        │         │  配置: baseUrl + apiKey + tier  │
│                         │         │  轮询 /v1/tasks                  │
│ 模型: /opt/mineru/models│         └─────────────────────────────────┘
└─────────────────────────┘
                 ▲                    (可接入多台 Sage 客户端)
                 │
        [离线模型包 mineru-models.tar.gz]
                 │
        [联网构建机 ~/.mineru/models]
```

### 2.2 Python 版本约束（关键决策依据）

| 组件 | Python 要求 |
|---|---|
| MinerU 4.x / 4.1 | **≥ 3.11, < 3.15**（官方推荐 3.12） |
| Sage main | 3.10（开发）/ 3.11（Windows 内嵌运行时） |
| Sage release/win7 | 3.8 |

MinerU 无法运行在 Sage 后端进程内，**必须独立进程/服务部署**。这同时带来好处：GPU 资源池化，Sage 端零版本升级成本。

### 2.3 硬件要求

| 项 | 最低 | 推荐（A6000 实际） |
|---|---|---|
| GPU 显存 | 8 GB（规划起点，非保证值） | 48 GB — Standard 档占用约 8 GB，余量留给并发 |
| 系统内存 | 16 GB | 32 GB+ |
| 驱动 | driver ≥ 535（CUDA 12.2） | 550+ |
| 磁盘 | 10 GB（模型 ~2 GB + 运行缓存） | 50 GB（含文档缓存与结果留存） |

A6000（Ampere, compute 8.6）完整支持 vLLM；`--tier standard` 单卡可跑，如需更高吞吐可用 `mineru-router` 起 2–3 个 worker。

## 3. 服务器侧部署

### 3.1 Python 环境

```bash
# 独立 venv，避免污染系统 Python
uv venv --python 3.12 /opt/mineru/.venv
source /opt/mineru/.venv/bin/activate

# full extras: torch（小模型 CUDA 加速）+ vLLM（VLM 高吞吐推理）
uv pip install -U "mineru[full]>=4.1,<5"
```

> 版本锁定在 `>=4.1,<5`：4.1 是破坏性协议更新，与 4.0 客户端/服务端不可混用。

### 3.2 模型离线搬运（内网核心步骤）

MinerU 运行期需要两类模型：

| 模型包 | 大小 | 用途 |
|---|---|---|
| `MinerU-4_models_torch` | ~0.8 GB | 小模型：OCR 检测 / 公式识别 / UNet 版面分析 |
| VLM（如 `MinerU2.5-2509-1.2B`） | ~1.2 GB | 复杂版式、跨页表格、标题层级 |
| 合计运行时 | ~2 GB | 加载后显存占用约 4–8 GB |

**步骤 1 — 联网构建机下载并校验**（`small_backend` / `vlm_engine` 按目标服务器显式指定，不依赖构建机硬件）：

```bash
mineru-kit models download --tier standard \
  --small-backend torch --vlm-engine vllm \
  --source huggingface

mineru-kit models verify --tier standard \
  --small-backend torch --vlm-engine vllm
```

若构建机无法访问 HuggingFace Xet CAS：

```bash
export HF_HUB_DISABLE_XET=1                 # 走普通 HTTP
# 或改用魔搭源：--source modelscope
```

**步骤 2 — 打包**：

```bash
tar -czf mineru-models.tar.gz -C ~/.mineru models
sha256sum mineru-models.tar.gz > mineru-models.tar.gz.sha256
```

**步骤 3 — 内网服务器解压**：

```bash
sha256sum -c mineru-models.tar.gz.sha256
tar -xzf mineru-models.tar.gz -C ~/.mineru/
```

> 模型目录归属按启动用户计算。systemd 托管时需显式设置 `HOME` 或 `MINERU_CONFIG`，否则会找不到 `~/.mineru/models`。完成后用 `mineru-kit models show` 确认 `Effective small backend` / `Effective VLM engine` 与模型就绪状态。

### 3.3 配置文件

默认读取 `$MINERU_HOME/config.yaml`（`MINERU_HOME` 默认 `~/.mineru`），可用 `MINERU_CONFIG` 指向其他文件。

```yaml
# ~/.mineru/config.yaml
model:
  source: local                  # 关键：禁止一切网络探测/下载
  base_dir: /opt/mineru/models   # 若模型统一存放，替换默认 ~/.mineru/models
  small_backend: torch           # A6000 走 CUDA，快于 ONNX
  vlm:
    engine: vllm                 # 48GB 显存跑 1.2B VLM 吞吐最高
```

**三个必须注意的点**：

| 点 | 说明 |
|---|---|
| `source: local` | 不设则启动时尝试联网探测 HuggingFace/ModelScope，内网会卡超时后才回退 |
| 遥测 | MinerU 4.x 默认开启 usage telemetry，必须设置 `MINERU_TELEMETRY_DISABLED=1` |
| 完成标记 | 重复下载会复用 provider 缓存；不要手工创建 completion marker，用 `mineru-kit models verify` 判定就绪 |

### 3.4 启动 API 服务

```bash
export MINERU_MODEL_SOURCE=local
export MINERU_TELEMETRY_DISABLED=1
export MINERU_API_KEY="<强随机串>"

mineru-kit api-server --host 0.0.0.0 --port 8000 --tier standard
```

验证：

```bash
curl -s http://127.0.0.1:8000/v1/health
curl -s http://127.0.0.1:8000/v1/tiers      # 应报告 standard 可用
```

OpenAPI 文档：`http://127.0.0.1:8000/docs`

**`--tier` 语义**：它是上限（含自身及更低档位）。`--tier standard` 不会启用 `advanced`。请求不带 tier 时服务端按 Standard → Basic → Flash → Advanced 选择。

### 3.5 systemd 托管

```ini
# /etc/systemd/system/mineru.service
[Unit]
Description=MinerU Document Parsing API
After=network.target

[Service]
Type=simple
User=mineru
Environment=HOME=/var/lib/mineru
Environment=MINERU_MODEL_SOURCE=local
Environment=MINERU_TELEMETRY_DISABLED=1
Environment=MINERU_API_KEY=<强随机串>
ExecStart=/opt/mineru/.venv/bin/mineru-kit api-server \
    --host 0.0.0.0 --port 8000 --tier standard
Restart=always
RestartSec=10
# vLLM 冷启动较慢，给足启动容忍
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now mineru
systemctl status mineru
```

### 3.6 多 GPU / 高吞吐扩展（可选）

单卡 A6000 已满足 Standard 档需求。当并发解析任务增多时：

```bash
mineru-router --host 0.0.0.0 --port 8002 \
  --local-gpus auto --worker-tier standard --preload-models
```

Router 暴露完整 `/v1/*` 契约，可聚合多个 `api-server` 上游（`--upstream-url` 可重复），Sage 侧只需把 `baseUrl` 指向 Router。

## 4. 内网搬运完整检查清单

| # | 步骤 | 执行位置 | 验证 |
|---|---|---|---|
| 1 | 装驱动 ≥535，`nvidia-smi` 正常 | 内网 A6000 | GPU 可见 |
| 2 | 建 Python 3.12 venv + `mineru[full]` | 内网 A6000 | `mineru-kit --version` 输出 4.1.x |
| 3 | 联网机构建模型包并 `verify` | 联网构建机 | verify 退出码 0 |
| 4 | 打包 + SHA-256 落盘 | 联网构建机 | `sha256sum -c` 通过 |
| 5 | 传输介质搬入内网 | 离线介质 | — |
| 6 | 解压到 `~/.mineru/models` | 内网 A6000 | `mineru-kit models show` 显示就绪 |
| 7 | 写 `config.yaml`（`source: local`） | 内网 A6000 | 启动日志无网络探测报错 |
| 8 | 启动 api-server + 健康检查 | 内网 A6000 | `/v1/health` 200 |
| 9 | 用样例 PDF 端到端解析 | 内网 A6000 或客户端 | 产出 Markdown 含公式/表格 |
| 10 | 配 Sage 客户端并跑通工具 | Sage 客户端机 | 工具返回 Markdown |

## 5. Sage 客户端接入

### 5.1 MinerU V1 API 契约（4.1）

多步异步流程（非单次请求）：

```
POST /v1/tasks
  请求: {"files": [{"file_name": "a.pdf", "bytes": 123456}], "tier": "standard", "output_formats": ["default"]}
  响应: {"task_id": "...", "files": [{"file_id": "...", "upload": {"url": "...", "headers": {...}, "expires_at": "..."}}]}

PUT  <upload.url>                          # 原始字节上传，无需完成回调
     Content-Type 按响应 headers 要求

GET  /v1/tasks/{task_id}                   # 轮询
  响应: files[].status ∈ waiting-file | pending | running | completed | partial | failed | canceled
        成功文件带 files[].result_url

GET  <result_url>                          # 下载 ZIP（md + middle json + images）或 docx/html/latex
POST /v1/tasks/{task_id}/cancel            # 取消未完成文件
```

发现类端点：`GET /v1/health`、`/v1/tiers`、`/v1/models`、`/v1/usage`。

错误结构：必填 `code`、`message`，可选 `param`。Tasks 创建无幂等保证，恢复操作应使用原 `task_id`。

**客户端实现要点**：

- 保留 API base 的路径前缀（反代场景），task_id 需 URL 编码。
- 上传与查询要分别对待：存在 `files[].upload` 才需要 PUT 字节。
- 轮询要有预算（最大轮数 × 间隔），超时不应重试创建任务。
- 完成文件的 `result_url` 可直接下载；签名过期则重新查询任务。

### 5.2 代码落点（基于现有结构）

| 层 | 文件 | 说明 |
|---|---|---|
| HTTP 客户端 | `backend/services/document_parse/mineru_client.py`（新建） | 多步流程；**不**套 `AICapability` 模板方法（它只支持单请求） |
| 配置读取 | 同上 `load_config()` | 读 preferences/settings 中的 `mineru` 块 |
| 工具 | `backend/tools/mineru_parse_tool.py`（新建） | 仿 `ocr_image_tool.py` 的 `BaseTool` 结构 |
| 工具注册 | `backend/tools/__init__.py`（`_LAZY_TOOL_EXPORTS`）+ `backend/tools/tool_bundles.py` | 与现有 104 个工具一致 |
| 设置 UI | `src/pages/settings/` 新增卡片 | 仿 `LocalOcrCard.tsx` |

**能力位降级**：与 `OcrEngine.available()` 哲学一致——`baseUrl` 未配置时工具不可用（schema 层不出现或直接返回说明），不影响其他功能。

### 5.3 配置项

最小配置：

```json
{
  "mineru": {
    "baseUrl": "http://10.x.x.x:8000",
    "apiKey": "<与服务器 MINERU_API_KEY 一致>",
    "defaultTier": "standard",
    "timeoutSeconds": 300
  }
}
```

存放位置二选一：

- `app_settings` 的 `modelSelections` + `endpoints`（复用 `AICapability.load_config()` 形状）
- preferences 独立 KV `mineru_service`（更贴近「外部服务地址」语义，实现更简单）

推荐后者：MinerU 不是 OpenAI 兼容模型端点，塞进 `endpoints` 会造成语义混淆。

### 5.4 工具语义

```
mineru_parse_document(
    file_path: str,
    output_format: "markdown" | "zip" | "docx" | "html" | "latex" = "markdown",
    tier: "flash" | "basic" | "standard" = "standard",
    pages: str | None = None          # 如 "1-5,8"
) -> ToolResult(text=markdown, metadata={pages_parsed, duration_ms, tier})
```

与 `ocr_image` 的分工：

| 工具 | 输入 | 输出 | 延迟 | 部署 |
|---|---|---|---|---|
| `ocr_image` | 单张图片 | 纯文本 + 行级置信度 | 秒级 | 本地 |
| `mineru_parse_document` | 整份 PDF / Office 文档 | Markdown（公式/表格/版式） | 分钟级 | 远程服务 |

**实现建议**：首版可做同步阻塞（`is_blocking = True`，后端超时 300s）；若后续需要并行多文档，再复用 `backend/tools/download_jobs.py` 的异步任务模式。

## 6. 网络与安全

| 项 | 建议 |
|---|---|
| 传输 | 同网段 HTTP 可接受；跨网段用 HTTPS 反代（nginx + 内网 CA） |
| 鉴权 | 服务器设 `MINERU_API_KEY`，Sage 侧带 `Authorization: Bearer`；不要裸奔端口 |
| 防火墙 | 仅对 Sage 后端机器放行 8000 端口 |
| 体积 | 设 Sage 侧上传上限（对齐现有 25–30 MB 习惯）；MinerU 单任务支持最多 100 个文件 |
| 遥测 | `MINERU_TELEMETRY_DISABLED=1`，文件内容/名称/路径默认不上传，但内网应彻底关闭 |
| 日志 | MinerU 日志不含文档内容时可保留；含路径的日志按敏感信息管理 |

## 7. 验证清单

服务器侧：

- [ ] `nvidia-smi` 可见 A6000
- [ ] `mineru-kit --version` 为 4.1.x
- [ ] `mineru-kit models show` 显示 small backend / VLM engine / 模型就绪
- [ ] `/v1/health` 返回 200
- [ ] `/v1/tiers` 含 standard
- [ ] 样例 PDF（含公式与跨页表格）解析成功，Markdown 结构正确
- [ ] 断开外网后重启服务仍可正常解析（验证零外网依赖）

Sage 侧：

- [ ] 配置 `baseUrl` 后工具出现在可用工具列表
- [ ] 未配置 `baseUrl` 时工具静默不可用，其它功能正常
- [ ] 解析 10 页以上 PDF 成功，输出长度与质量符合预期
- [ ] 服务器不可达时工具返回友好错误，不阻塞聊天链路

## 8. 运维与故障排查

| 症状 | 排查 |
|---|---|
| 启动卡住数分钟 | `source: local` 未设，正在联网探测；检查 config.yaml |
| `/v1/health` 200 但解析失败 | 看 `mineru-kit models show` 是否就绪；检查磁盘与显存 |
| vLLM 加载失败 | 检查驱动与 CUDA 版本匹配；`mineru-kit hardware info --json` |
| 上传 404/过期 | `files[].upload.expires_at` 有期限，超时需重新创建任务 |
| 结果签名过期 | 重新 `GET /v1/tasks/{task_id}` 取新 `result_url` |
| 磁盘增长 | 结果文件有留存策略（`MINERU_API_TASK_RETENTION_SECONDS`），按需清理 |

## 9. 风险评估

| 风险 | 等级 | 缓解 |
|---|---|---|
| 4.1 破坏性协议变更 | 中 | 客户端与服务端同锁 `>=4.1,<5`；不做跨版本兼容 |
| `hf_xet` 内网不可用 | 低 | 只在内网用 `source: local`；下载全部在联网机完成 |
| 模型许可（AGPL-3.0） | 中 | 纯内网自用一般不触发分发条款；对外交付前需法务确认 |
| A6000 型号歧义（Ampere vs Ada） | 低 | 两者均满足；驱动与 vLLM wheel 按实际型号选 |
| vLLM 冷启动慢（10–20s） | 低 | systemd `TimeoutStartSec=300` + 健康检查容忍 |
| 模型版本漂移 | 中 | 固定模型版本号（如 `MinerU2.5-2509-1.2B`），不用 latest |

## 10. 附录：V1 API 速查

| Method | Path | 用途 |
|---|---|---|
| GET | `/v1/health` | 健康检查 |
| GET | `/v1/tiers` | 可用解析档位 |
| GET | `/v1/models` | 模型列表（虚拟模型 id） |
| GET | `/v1/usage` | 用量 |
| GET | `/v1/files/{file_id}` | 文件元信息 |
| GET | `/v1/files/{file_id}/content` | 下载解析产物 |
| POST | `/v1/tasks` | JSON 清单创建任务（返回缺失文件上传链接） |
| PUT | 返回的 upload URL | 逐文件上传原始字节 |
| GET | `/v1/tasks/{task_id}` | 任务与逐文件状态 + 结果链接 |
| POST | `/v1/tasks/{task_id}/cancel` | 取消未完成文件 |

`output_formats` 可选：`default`（Markdown + Middle JSON + 图片，ZIP）、`docx`、`html`、`latex`。多格式共享一个扁平 ZIP。
