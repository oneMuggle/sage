# MinerU 内网独立部署方案

> 文档编号：157
> 状态：已实施（2026-11-23 按 4.1.7 实包校正；离线包工具位于 `scripts/mineru-offline-bundle/`）
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
┌─────────────────────────┐          HTTP :8000（Bearer 或内网匿名）
│ A6000 GPU 服务器         │◄─────────────────────────┐
│                         │                          │
│ systemd: mineru.service │         ┌────────────────┴────────────────┐
│  ExecStart=/etc/mineru/ │         │ Sage 后端（Python 3.10 / 3.8）    │
│    mineru-start.sh      │         │  parse_document 工具             │
│  → mineru-kit api-server│         │  配置: baseUrl + apiKey + tier  │
│    --tier standard      │         │  轮询 /v1/tasks                  │
│                         │         └─────────────────────────────────┘
│ 模型: $HOME/.mineru/models │
└─────────────────────────┘
                 ▲                    (可接入多台 Sage 客户端)
                 │
     [离线部署包 mineru-offline-bundle-*.tar
      （便携 Python + wheels + models + install.sh）]
                 │
        [联网构建机 build-bundle.sh]
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
| 驱动 | driver ≥ 535（torch 2.10 / CUDA 12.8；vllm 0.19.1） | 550+ |
| 磁盘 | 10 GB（模型 ~2 GB + 运行缓存） | 50 GB（含文档缓存与结果留存） |

A6000（Ampere, compute 8.6）完整支持 vLLM；`--tier standard` 单卡可跑，如需更高吞吐可用 `mineru-router` 起 2–3 个 worker。

## 3. 服务器侧部署

### 3.1 Python 环境

离线包自带便携 CPython（python-build-standalone `3.12.16`）与全部 wheel，目标机无需系统 Python，也不联网：

```bash
# 便携 Python 解包到 /opt/mineru/python（由构建机 build-bundle.sh 生成）
/opt/mineru/python/bin/python3.12 -m venv --copies /opt/mineru/.venv
/opt/mineru/.venv/bin/pip install --no-index \
  --find-links /path/to/bundle/wheels "mineru[full]>=4.1,<4.2"
```

> 版本锁定在 `>=4.1,<4.2`：4.1 是破坏性协议更新，与 4.0 客户端/服务端不可混用；4.2 起 API 形状可能再变，客户端与服务端必须同锁。
>
> 上述步骤由离线包的 `sudo ./install.sh` 自动完成（含 `mineru` 系统用户、`/etc/mineru/mineru.env` 0600、systemd unit、300 s 健康轮询）。

### 3.2 模型离线搬运（内网核心步骤）

MinerU 运行期需要两类模型：

| 模型包 | 大小 | 用途 |
|---|---|---|
| `MinerU-4_models_torch` | ~0.8 GB | 小模型：OCR 检测 / 公式识别 / UNet 版面分析 |
| VLM（`MinerU2.5-Pro-2605-1.2B`） | ~1.2 GB | 复杂版式、跨页表格、标题层级 |
| 合计运行时 | ~2 GB | 加载后显存占用约 4–8 GB |

> 以上搬运已由 `scripts/mineru-offline-bundle/build-bundle.sh` 全自动完成（便携 Python + wheel + 模型 + 部署脚本打包为单一 tar）。以下手工步骤仅用于排障或定制。

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

> 模型目录归属按启动用户计算。systemd 托管时需显式设置 `HOME`（unit 模板已设 `Environment=HOME=/var/lib/mineru`），否则会找不到 `~/.mineru/models`。完成后用 `mineru-kit models verify`（同 `--tier/--small-backend/--vlm-engine` 参数）判定模型就绪，退出码 0 即通过。

### 3.3 配置文件

默认读取 `$MINERU_HOME/config.yaml`（`MINERU_HOME` 默认 `~/.mineru`），可用 `MINERU_CONFIG` 指向其他文件。

```yaml
# ~/.mineru/config.yaml
model:
  source: local                  # 关键：禁止一切网络探测/下载
  base_dir: /var/lib/mineru/.mineru/models   # install.sh 生成的实际路径；缺省为服务用户 ~/.mineru/models
  small_backend: torch           # A6000 走 CUDA，快于 ONNX
  vlm:
    engine: vllm                 # 48GB 显存跑 1.2B VLM 吞吐最高
```

**注意点**：

| 点 | 说明 |
|---|---|
| `source: local` | 不设则启动时尝试联网探测 HuggingFace/ModelScope，内网会卡超时后才回退 |
| 离线环境 | 同时固定 `MINERU_MODEL_SOURCE=local`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，配合 `MINERU_TELEMETRY_DISABLED=1` 彻底断网 |
| 遥测 | MinerU 4.x 默认开启 usage telemetry，必须设置 `MINERU_TELEMETRY_DISABLED=1` |
| 完成标记 | 重复下载会复用 provider 缓存；不要手工创建 completion marker，用 `mineru-kit models verify` 判定就绪 |

### 3.4 启动 API 服务

**关键坑：`--api-key` 没有环境变量回退。** 只有命令行显式传参才会开启鉴权；仅在 systemd unit 里写 `Environment=MINERU_API_KEY=...` 不会生效，服务端会**静默保持匿名**。这正是旧版离线包「配了 key 却没鉴权」的根因，修法见 §3.5 与 `scripts/mineru-offline-bundle/README.md` §3.1。

```bash
export MINERU_MODEL_SOURCE=local
export MINERU_TELEMETRY_DISABLED=1
export MINERU_API_KEY="<强随机串>"

# --api-key 必须出现在命令行上，环境变量本身不起作用
mineru-kit api-server --host 0.0.0.0 --port 8000 --tier standard \
  --api-key "$MINERU_API_KEY"
```

验证：

```bash
curl -s http://127.0.0.1:8000/v1/health
curl -s http://127.0.0.1:8000/v1/tiers      # 应报告 standard 可用

# 鉴权探针：/v1/usage 不是公开端点 —— 200 即匿名；401/403 即鉴权生效
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/v1/usage
```

公开端点只有 `/v1/health`、`/v1/models`、`/v1/tiers`，**它们无法证明鉴权生效**；`/v1/usage` 才是判据。这就是 `verify.sh` 与 Sage `GET /api/v1/mineru/status` 判定 `serverAuthMode` 的依据。

**`--tier` 语义**：它是上限（含自身及更低档位）。`--tier standard` 不会启用 `advanced`。请求不带 tier 时服务端按 Standard → Basic → Flash → Advanced 选择；`--tier` 只影响 PDF/图片，Office 文档固定走 flash 快速路径。

### 3.5 systemd 托管

直接 `ExecStart=...mineru-kit api-server` 的单元会漏掉 `--api-key`（见 §3.4）。正确形态是**环境文件 + 无密钥包装脚本**：

```ini
# /etc/mineru/mineru.env（0600 root；由 install.sh 生成）
MINERU_MODEL_SOURCE=local
MINERU_TELEMETRY_DISABLED=1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
MINERU_API_KEY=<强随机串>
```

```bash
# /etc/mineru/mineru-start.sh（0755 root；不含密钥）
#!/usr/bin/env bash
set -euo pipefail
: "${MINERU_API_KEY:?MINERU_API_KEY 未注入（检查 EnvironmentFile）}"
exec /opt/mineru/.venv/bin/mineru-kit api-server \
  --host 0.0.0.0 --port 8000 --tier standard \
  --api-key "$MINERU_API_KEY"
```

```ini
# /etc/systemd/system/mineru.service
[Unit]
Description=MinerU Document Parsing API
After=network.target

[Service]
Type=simple
User=mineru
Group=mineru
Environment=HOME=/var/lib/mineru
EnvironmentFile=/etc/mineru/mineru.env
ExecStart=/etc/mineru/mineru-start.sh
Restart=always
RestartSec=10
# vLLM 冷启动较慢，给足启动容忍
TimeoutStartSec=300
TimeoutStopSec=60
LimitNOFILE=65535
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now mineru
systemctl status mineru
```

> 环境文件保持 `0600 root`，systemd 以特权身份读取它再注入服务环境；包装脚本本身不含密钥，可安全保留 `0755`。匿名模式由 `install.sh --auth-mode anonymous` 换成 `mineru-start-anonymous.sh` 模板（不传 `--api-key`），并在 `/etc/mineru/auth-mode` 记录期望模式（`0644`）供 `verify.sh` 比对实测结果。

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
| 2 | `bash scripts/mineru-offline-bundle/build-bundle.sh` | 联网构建机 | 产出 tar + `.sha256`；`models verify` 退出码 0 |
| 3 | 校验后 `sudo ./install.sh`（默认 bearer） | 内网 A6000 | 便携 Python / venv / wheel / 模型 / systemd 全部落地 |
| 4 | `sudo ./verify.sh` | 内网 A6000 | 8 项全 PASS；`serverAuthMode` 与期望一致 |
| 5 | 断开外网后重启服务仍可解析 | 内网 A6000 | 验证零外网依赖 |
| 6 | 配 Sage 客户端并跑通工具 | Sage 客户端机 | `parse_document` 返回 Markdown 含公式/表格 |

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

**契约细节（4.1.7 实测）**：

- 响应经 `model_dump(exclude_none=True)` 序列化：可选字段**缺失**而非 `null`，客户端不得假设键一定存在。
- `files[].file_name` 会做校验：不允许路径分隔符或 `..`，只传文件名。
- `POST /v1/tasks` 的 query 参数会被拒绝，清单必须放在 JSON body。
- `output_formats` 仅 `{docx}` 或仅 `{html}` 时直接返回原始文件；含 `default` 的组合返回扁平 ZIP。
- 不带 `--api-key` 启动时服务端完全匿名（所有路径放行）；带 key 后仅 `/v1/health`、`/v1/models`、`/v1/tiers` 公开。
- `/v1/usage` 返回 `access_level ∈ {registered, anonymous}`，可作鉴权探针。

**客户端实现要点**：

- 保留 API base 的路径前缀（反代场景），task_id 需 URL 编码。
- 上传与查询要分别对待：存在 `files[].upload` 才需要 PUT 字节。
- 轮询要有预算（最大轮数 × 间隔），超时不应重试创建任务。
- 完成文件的 `result_url` 可直接下载；签名过期则重新查询任务。

### 5.2 代码落点（已实现）

| 层 | 文件 | 说明 |
|---|---|---|
| 领域模型 | `backend/domain/document_parse.py` | 枚举、常量与默认值（超时 300 s / 质量阈值 0.85 / 上传上限 25 MB） |
| HTTP 客户端 | `backend/adapters/out/document_parse/mineru_client.py`（新建） | 多步异步流程 + `probe()`；**不**套 `AICapability` 模板方法（它只支持单请求） |
| 本地引擎 | `backend/adapters/out/document_parse/local_engine.py` | PDF/DOCX 本地抽取，作为 MinerU 不可用时的降级路径 |
| 质量评估 | `backend/adapters/out/document_parse/quality.py` | 本地抽取质量打分，决定是否升级到 MinerU |
| 引擎编排 | `backend/adapters/out/document_parse/mineru_engine.py` | `auto` 引擎选择与回退 |
| 配置读取 | `backend/services/document_parse/config.py` | 环境变量 > preferences `mineru_service` > 默认值 |
| 缓存/队列/工厂 | `backend/services/document_parse/{cache,queue,factory}.py` | 内容哈希缓存、并发闸门、依赖装配 |
| 应用服务 | `backend/application/document_parse.py` | 用例编排（解析 → 质量 → 降级 → 缓存） |
| 工具 | `backend/tools/parse_document_tool.py`（新建） | `ParseDocumentTool`，`risk=EXTERNAL`，`is_blocking=True` |
| 工具注册 | `backend/tools/__init__.py`（`_LAZY_TOOL_EXPORTS`）+ `backend/tools/tool_bundles.py` + `backend/tools/permissions.py` | 与现有工具一致 |
| 状态 API | `backend/api/mineru_routes.py` | `GET /api/v1/mineru/status`（`backend/main.py:1469` 挂载） |
| 设置 UI | `src/pages/settings/MineruServiceCard.tsx` | 仿 `LocalOcrCard.tsx` |

**能力位降级**：与 `OcrEngine.available()` 哲学一致——`baseUrl` 未配置时工具不可用（schema 层不出现或直接返回说明），不影响其他功能。

### 5.3 配置项

preferences 独立 KV `mineru_service`：

```json
{
  "mineru_service": {
    "baseUrl": "http://10.x.x.x:8000",
    "apiKey": "<与服务器 MINERU_API_KEY 一致；匿名部署留空>",
    "defaultTier": "standard",
    "timeoutSeconds": 300
  }
}
```

可选字段（有默认值，一般不用改）：`enabled`（工具是否启用）、`maxUploadMb`（默认 25，范围 1–200）、`useInChatAttachment`（默认 `true`，聊天附件是否走 MinerU）、`minQualityThreshold`（默认 0.85，`auto` 引擎的升级阈值）。

**优先级**：环境变量 > preferences `mineru_service` > 默认值。

| 环境变量 | 覆盖字段 |
|---|---|
| `SAGE_MINERU_BASE_URL` | `baseUrl` |
| `SAGE_MINERU_API_KEY` | `apiKey` |
| `SAGE_MINERU_TIER` | `defaultTier` |
| `SAGE_MINERU_TIMEOUT_SECONDS` | `timeoutSeconds` |

密钥只走 gitignored 的 `.env.local`、环境变量或设置页输入框，**不要**写进 `README`、工单或聊天记录。`GET /api/v1/mineru/status` 只回 `hasApiKey`（布尔）与 `serverAuthMode`（`anonymous|bearer|required|unknown`），永不回显 key 或 `baseUrl`。

不塞进 `endpoints` / `modelSelections`：MinerU 不是 OpenAI 兼容模型端点，复用 `AICapability.load_config()` 的形状会造成语义混淆。

### 5.4 工具语义

```
parse_document(
    path: str | None = None,          # 与 media_id 二选一
    media_id: str | None = None,
    engine: "auto" | "local" | "mineru" = "auto",
    output_format: "markdown" | "structured" | "docx" | "html" = "markdown",
    pages: str | None = None,         # 如 "1-5,8"
    tier: "flash" | "basic" | "standard" | "advanced" | None = None
) -> ToolResult(output={engine_used, tier_used, quality_score, cached, duration_ms, warnings, media_url, assets})
```

`engine` 语义：

| 取值 | 行为 |
|---|---|
| `auto`（默认） | 先本地抽取并打分；质量低于阈值（0.85）或遇复杂版式时升级 MinerU；MinerU 不可达则保留本地结果 |
| `local` | 只走本地 PDF/DOCX 抽取，不访问网络 |
| `mineru` | 直接调用 MinerU；服务不可达时返回明确错误，由上层决定是否降级 |

`output_format` 映射到 MinerU 的 `output_formats`：`markdown` / `structured` → `default`（ZIP 内取 md / middle JSON），`docx` / `html` → 对应单一格式。注意 MinerU 对仅 `{docx}`、仅 `{html}` 返回原始文件而非 ZIP。

与 `ocr_image` 的分工：

| 工具 | 输入 | 输出 | 延迟 | 部署 |
|---|---|---|---|---|
| `ocr_image` | 单张图片 | 纯文本 + 行级置信度 | 秒级 | 本地 |
| `parse_document` | 整份 PDF / Office 文档 | Markdown / 结构化（公式/表格/版式） | 本地秒级、MinerU 分钟级 | 本地 + 远程服务 |

结果为阻塞式（`is_blocking = True`，后端超时 300 s）；相同内容哈希命中缓存时秒回。

## 6. 网络与安全

| 项 | 建议 |
|---|---|
| 传输 | 同网段 HTTP 可接受；跨网段用 HTTPS 反代（nginx + 内网 CA） |
| 鉴权 | 在**命令行**传 `--api-key` 才会生效（无环境变量回退）；systemd 场景用 §3.5 的环境文件 + 包装脚本；Sage 侧按 `serverAuthMode` 决定是否带 `Authorization: Bearer` |
| 匿名模式 | 若 `--auth-mode anonymous`，任何可达 8000 端口的主机都能调用解析服务，**必须**用内网防火墙限制来源 |
| 状态接口 | `GET /api/v1/mineru/status` 只回 `hasApiKey` 与 `serverAuthMode`，不回 key、不回 `baseUrl`；排障时也不要贴 raw key |
| 防火墙 | 仅对 Sage 后端机器放行 8000 端口 |
| 体积 | Sage 侧上传上限 25 MB（可在设置页或 `SAGE_MINERU_*` 调整）；MinerU 单任务支持最多 100 个文件 |
| 遥测 | `MINERU_TELEMETRY_DISABLED=1`，文件内容/名称/路径默认不上传，但内网应彻底关闭 |
| 日志 | MinerU 日志不含文档内容时可保留；含路径的日志按敏感信息管理 |

## 7. 验证清单

服务器侧：

- [ ] `nvidia-smi` 可见 A6000
- [ ] `mineru-kit --version` 为 4.1.x（锁 `>=4.1,<4.2`）
- [ ] `HOME=/var/lib/mineru mineru-kit models verify --tier standard --small-backend torch --vlm-engine vllm` 退出码 0
- [ ] `sudo ./verify.sh` 八项全 PASS
- [ ] `/v1/health` 返回 200；`/v1/tiers` 含 standard
- [ ] `/v1/usage` 行为与 `--auth-mode` 一致（bearer ⇒ 401/403；anonymous ⇒ 200）
- [ ] 样例 PDF（含公式与跨页表格）解析成功，Markdown 结构正确
- [ ] 断开外网后重启服务仍可正常解析（验证零外网依赖）

Sage 侧：

- [ ] 配置 `baseUrl` 后工具出现在可用工具列表
- [ ] 未配置 `baseUrl` 时工具静默不可用，其它功能正常
- [ ] `GET /api/v1/mineru/status` 的 `serverAuthMode` 与 `verify.sh` 输出一致
- [ ] 解析 10 页以上 PDF 成功，输出长度与质量符合预期
- [ ] 服务器不可达时工具返回友好错误，不阻塞聊天链路

## 8. 运维与故障排查

| 症状 | 排查 |
|---|---|
| 期望 bearer 但 `serverAuthMode=anonymous` | `grep -- --api-key /etc/mineru/mineru-start.sh`；`systemctl cat mineru` 看 `ExecStart` 是否被旧 unit/drop-in 覆盖；改完要 `systemctl daemon-reload` |
| 启动卡住数分钟 | `source: local` 未设，正在联网探测；检查 config.yaml |
| `/v1/health` 200 但解析失败 | `HOME=/var/lib/mineru mineru-kit models verify ...` 是否通过；检查磁盘与显存 |
| vLLM 加载失败 | 检查驱动与 CUDA 版本匹配（torch 2.10 / CUDA 12.8 / 驱动 ≥535）；`mineru-kit hardware info --json` |
| 启动慢/超时 | vLLM 冷启动可超 60 s；`TimeoutStartSec=300`，看 journal 是否在加载模型 |
| 上传 404/过期 | `files[].upload.expires_at` 有期限，超时需重新创建任务 |
| 结果签名过期 | 重新 `GET /v1/tasks/{task_id}` 取新 `result_url` |
| 客户端 401 | `serverAuthMode` 与设置页 `apiKey` 是否匹配（bearer 需填 key，anonymous 需留空） |
| 磁盘增长 | 结果文件有留存策略；`mineru-kit api-server --help` 查 `--retention-seconds` 并按需调小 |

## 9. 风险评估

| 风险 | 等级 | 缓解 |
|---|---|---|
| 4.1 破坏性协议变更 | 中 | 客户端与服务端同锁 `>=4.1,<4.2`；不做跨版本兼容 |
| 旧离线包默认匿名（`--api-key` 未传到 api-server） | 中 | 新版 `install.sh` 用包装脚本展开 `$MINERU_API_KEY`，`verify.sh` 实测 `/v1/usage`；升级步骤见 `scripts/mineru-offline-bundle/README.md` §5 |
| `hf_xet` 内网不可用 | 低 | 只在内网用 `source: local`；下载全部在联网机完成 |
| 模型许可（AGPL-3.0） | 中 | 纯内网自用一般不触发分发条款；对外交付前需法务确认 |
| A6000 型号歧义（Ampere vs Ada） | 低 | 两者均满足；驱动与 vLLM wheel 按实际型号选 |
| vLLM 冷启动慢（10–20s） | 低 | systemd `TimeoutStartSec=300` + 健康检查容忍 |
| 模型版本漂移 | 中 | 固定模型版本（`MinerU2.5-Pro-2605-1.2B`），不用 latest |

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

`output_formats` 可选：`default`（Markdown + Middle JSON + 图片，ZIP）、`docx`、`html`、`latex`。多格式共享一个扁平 ZIP；仅传 `{docx}` 或仅 `{html}` 时直接返回原始文件，不打包。Sage 的 `parse_document` 对外暴露 `markdown | structured | docx | html` 四种（见 §5.4）。
