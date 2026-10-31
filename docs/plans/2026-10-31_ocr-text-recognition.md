# 本地 OCR 文字识别能力方案（无多模态模型时的文本兜底）

> 日期：2026-10-31 · 状态：方案（待评审，未开始实施；调研数据核对于 2026-10-31）
> 范围：聊天图片附件主链路、Agent 图片读取工具、Wiki 图片摄入、Office/PDF 扫描页 OCR 的统一引擎层；
> 不改变「有视觉能力时优先原生视觉」的既有策略
> 分支：`main`（开发环境 Python 3.10；**打包基线 3.11.9**；CI 3.11）+ `release/win7`（Python 3.8.10）；
> 新代码必须 **py38 语法安全 + 3.11 运行**
> 结论先行：**不重写现有 OCR，而是把它从「Office 内部的一个函数」升级为「可插拔的本地 OCR 子系统」**。
> main 默认引擎用 **RapidOCR 3.x（ONNX Runtime + PP-OCRv5 mobile）**，Tesseract 作为已有/兼容后端；
> 聊天链路新增「本地 OCR」降级层；Win7 不承诺 RapidOCR（官方不支持），以 **Tesseract 4.1 兼容构建**兜底，
> RapidOCR + onnxruntime 1.14.1 仅作实验性路径，真机验证前不启用。

---

## 0. TL;DR

### 0.1 现状（代码核实）

- Sage 已有 OCR，但**只服务 Office/PDF**：`backend/office/ocr.py` 用 `pytesseract + tesseract`
  对文本层近乎为空的 PDF 页做整页识别，由 `SAGE_OCR=1` 显式开启，默认关闭；
  消费方只有 `backend/office/pdf.py:230-246` 与 `backend/office/pdf_to_word.py:325-337`。
- 聊天图片现状（`backend/core/legacy/agent.py:801-836`）是三级：
  1. 对话模型支持（或能力未知）vision → `image_url` 原生注入（`_inject_images_as_content`，:838-875）；
  2. 确认不支持 vision 且配置了 `visionModel` → `caption_image` 生成描述并替换为文本
     （`_generate_image_descriptions` :972-1015、`_replace_images_with_descriptions` :1017+）；
  3. 都没有 → 抛 `VisionNotAvailableError`（`backend/core/errors.py:56-73`）。
- 前端 `src/widgets/chat/ChatInput.tsx:121-132` 用
  `!supportsVision && !visionModelConfigured` 决定 `visionUploadDisabled`，并据此禁用
  `onImageSelect`（:758）与拖拽/粘贴（:761-763），显示
  `chat.vision_not_available`（`src/shared/lib/i18n/locales/zh/chatAndSider.ts:199-201`）。
- 聊天图片**不进入 MediaStore**：前端以 base64 data URL 随请求发送（≤4 张、单张解码后 ≤5 MiB，
  `backend/api/chat_stream_support.py:79-110`）；落库的 `client_meta.images` 只保留
  `{name,size,type}`，刷新后无法从服务端取回原图（`src/features/send-message/messageDisplayMeta.ts`）。
- 本地模型管理已有成熟先例：
  - `backend/memory/embedder_factory.py:44-122`：可选依赖 + 模型目录 + 设置偏好 + 优雅降级 + 预热；
  - **模型下载由 Electron 负责**：`electron/modelDownloadIpc.ts:38-52`（清单 + SHA-256）、
    `electron/main.ts:1810-1815`（落到 `SAGE_USER_DATA_DIR/models`）、
    `src/pages/settings/MemoryTab.tsx:140,310-315`（设置页入口）。

### 0.2 关键事实修正（相对初稿）

1. **main 打包 Python 是 3.11.9**（`scripts/bundle-python-main.ps1:86`），CI 也是 3.11；
   `CLAUDE.md` 写的 3.10 是开发环境。新代码按 py38 语法安全 + 3.11 运行。
2. **`Pillow` 的通道差异**：`requirements.txt:92` 有 `Pillow>=10.0`（注释明确「main 通道 only；
   requirements-bundled/py38 不加」），`requirements-bundled.txt` **没有 Pillow**，
   `requirements-py38.txt:87` 有 `Pillow==10.4.0`。而 main 安装包正是用
   `requirements-bundled.txt` 构建（`scripts/bundle-python-main.ps1:102`），
   win7 用 `requirements-py38.txt`（`scripts/bundle-python.ps1:31`）。
   结论：**main 安装版没有 Pillow，现有 OCR 路径在安装包中实际不可用**；
   OCR 核心应**不硬依赖 Pillow**（引擎原生解码 / 临时文件），Pillow 仅作可选预处理。
3. **`tesseract` 是系统二进制**，仓库没有捆绑或定位机制，`shutil.which` 只查 PATH；
   Tesseract 5 官方只支持 Win10/11，Win7 只能用 4.1 旧构建（非官方支持）。
4. **onnxruntime 的 Win7/Py3.8 边界**（PyPI 元数据核实）：
   - Py3.8 最高可用 **1.19.2**（最后一个带 cp38 wheel 的版本）；
   - Win7 社区最后可用 **1.14.1**，1.15 起普遍报告无法加载；官方不承诺 Win7；
   - RapidOCR 官方 FAQ 明确「近版本 ONNX Runtime 不支持 Windows 7」。
5. **RapidOCR 3.x 支持 Py>=3.8**；`rapidocr-onnxruntime==1.4.4` 支持 3.6–3.12（legacy 路线）。
6. **设置落点**：项目有强 `app_settings` 白名单（`settings_canonicalizer.py` 的
   `LEGAL_TOP_KEYS` + `test_settings_schema_parity.py`），新增顶层键要同步 6 处；
   更适合沿用 `embedding_mode` 的 **preference blob** 模式（`settingsRegistry.ts:223-234`、
   `SettingsRepository.KEYS`），新增 `ocr_config`。
7. **`backend/services/multimodal` 是远端 HTTP 抽象**（`AICapability.execute` 固定走
   `httpx.AsyncClient`），本地 OCR 不应强行注册进去；独立 `backend/services/ocr/` 更合适。
8. **聊天图片不落盘**：OCR 只能在请求内处理 data URL，或按 sha256 写文本缓存；
   不要把「原图长期可回看」作为一期承诺。

### 0.3 缺口

| 场景 | 现在会怎样 | 目标 |
|---|---|---|
| 对话模型无 vision、未配 visionModel，用户贴截图 | 上传被禁用或请求报错 | 本地 OCR 提取文字 → 作为文本上下文继续对话 |
| 对话模型无 vision、已配 visionModel，但图片是纯文字截图 | 走视觉模型描述，慢/贵/可能丢细节 | 可配置优先本地 OCR（更快、更省、离线可复现） |
| Agent 需要读工作区里的图片/截图 | 无工具可读 | 新增 `ocr_image` 工具 |
| 扫描 PDF / Office 图片 | 仅 tesseract、默认关闭、安装版缺 Pillow | 统一引擎层，main 默认 RapidOCR |
| Wiki 图片摄入 | 依赖视觉模型 caption | 无视觉模型时用 OCR 文本兜底 |

### 0.4 推荐路线

1. **统一接口**：`backend/services/ocr/`，引擎可插拔（RapidOCR / Tesseract / Null）。
2. **聊天降级链**：`原生视觉 > visionModel > 本地 OCR > 明确报错`，顺序可配置；
   本地 OCR 仅在「确认无 vision 且未配 visionModel」时自动触发。
3. **main 默认 RapidOCR(ONNX)**：PP-OCRv5 mobile（det 4.6MB + rec 16MB + cls ~1–2MB），
   中文印刷体/截图优于 Tesseract；`onnxruntime==1.19.2` 与 Py3.8 对齐。
4. **Win7 保守**：Tesseract 4.1 兼容构建 + fast 语言包；RapidOCR + ORT 1.14.1 仅实验，
   真机验证通过前不启用、不承诺。
5. **模型外置**：不进默认安装包；复用 Electron 的模型下载机制（清单 + SHA-256 + 用户目录）。
6. **UI 诚实**：附件显示路由标签（视觉模型 / 本地 OCR）、识别结果可查看/复制/编辑，
   失败给可操作原因（无文本层 / 质量低 / 语言包缺失 / 引擎不可用 / 超时）。

---

## 1. 背景与目标

### 1.1 用户问题

用户经常直接粘贴截图、拍照或扫描件（报错信息、网页、表格、文档页），希望 Sage 能「看懂」。
但用户可能只配置了纯文本对话模型（本地 Ollama 小模型、DeepSeek、GPT-3.5 类、企业内网模型），
没有多模态能力，也没有单独的视觉理解模型。当前行为是**直接拒绝上传或请求报错**，
与「本地优先、离线可用」的产品定位不符。

### 1.2 目标

1. **无多模态模型也能读图**：至少对「文字为主的图片」提取文本并继续对话。
2. **本地、离线、隐私**：默认不把图片上传到任何外部服务；OCR 在本机 CPU 完成。
3. **快**：单张 1080p 截图目标 < 2s（CPU、模型已加载；低功耗机器 2–5s 可接受）。
4. **可解释**：用户能知道文字来自 OCR、用了什么引擎、质量如何，并能编辑后重发。
5. **可降级**：引擎/模型缺失、Win7、低配机器上不崩溃，给出可操作的提示。
6. **不劣化现状**：有视觉模型时行为不变；Office OCR 的既有语义与开关兼容。

### 1.3 非目标

- 不做通用图片理解（场景、物体、人物描述）——那是视觉模型的职责；OCR 只负责「文字」。
- 不做手写体/复杂公式/乐谱的高保证识别；VLM 方案（PaddleOCR-VL、dots.mocr、DeepSeek-OCR、
  olmOCR 等）不进入桌面默认包。
- 不做云端 OCR 默认接入（未来可作为可选能力）。
- 不做表格结构/阅读顺序/版面还原的一期目标；一期只保序输出文本行。
- 不替代 Word 文档智能（`docs/plans/2026-10-31_word-document-intelligence.md`）的文档解析。
- 不承诺「聊天图片原图长期可回看」——当前链路本就不落盘。

---

## 2. 现状盘点（代码级）

### 2.1 已有 OCR 模块

| 项 | 位置 | 说明 |
|---|---|---|
| OCR 实现 | `backend/office/ocr.py` | `ocr_page_if_needed(page, text)`；文本层 < 32 字符才触发；`SAGE_OCR=1` 才启用 |
| 依赖探测 | `ocr_available()` / `ocr_languages()` | `pytesseract` import + `shutil.which("tesseract")` |
| 语言/置信度 | `SAGE_OCR_LANG`（默认 `eng+chi_sim`）、`SAGE_OCR_MIN_CONFIDENCE`（默认 40） | 逐词置信度过滤 + 语言包回退 |
| 消费方 | `backend/office/pdf.py:230-246`、`backend/office/pdf_to_word.py:325-337` | 仅 PDF 读取 / PDF→Word |
| 能力位 | `backend/office/capabilities.py:53-60,100-122` | 30s 缓存；`GET /office/capabilities`（`office_lifecycle_routes.py:342`） |
| 前端类型/徽章 | `src/shared/api/types/templateAndTaskTypes.ts:147-148`、`src/features/office/OfficeCapabilityBar.tsx:126-129` | 仅 Office 页，未接入聊天门控 |
| 可选依赖 | `backend/requirements-optional.txt:43-51` | 只有注释说明，未真正 pin |
| 测试 | `backend/tests/unit/office/test_ocr.py`（14 项） | fake pytesseract + fake 页对象，语义覆盖完整 |

风险/缺口：

- `ocr_page_if_needed` 对 `pytesseract` 调用**没有超时**；CPU/外部进程可能阻塞请求线程。
- **main 安装包没有 Pillow**（`requirements-bundled.txt` 刻意不含），`backend/office/ocr.py:127`
  的 `from PIL import Image` 在安装版会失败；win7 包含 Pillow 10.4.0，可走 Tesseract 路径。
- `tesseract` 无捆绑/定位机制；仅 PATH 探测。
- 无通用图片字节接口；无引擎抽象；无模型管理。

### 2.2 聊天图片链路

```
前端 useFileUpload（FileReader.readAsDataURL）
  → ChatInput / WelcomeInputCard 收集 data URL（≤4 张；单张解码 ≤5 MiB）
  → chatApi.chatStream({ images: string[] })
  → POST /api/v1/chat/stream（backend/api/chat_stream_support.py:79-110 校验）
  → legacy_routes.py:1866-1869
  → SageAgent._prepare_messages_with_images（backend/core/legacy/agent.py:801-836）
      ├─ vision 支持/未知 → _inject_images_as_content（image_url 块）
      ├─ 不支持且配置 visionModel → caption_image → 替换为文本
      └─ 都不满足 → VisionNotAvailableError
  → LLM
```

关键细节：

- 能力判定 **unknown → 视为支持 vision**（`_get_model_capabilities`，agent.py:781-799）；
  前端同口径（`ChatInput.tsx:121-132`）。因此 OCR 只应在「明确不支持」或用户显式偏好时触发，
  否则会改变「能力未知但实际支持视觉」的用户行为。
- `caption_image` 逐张调用，单张失败填 `[图片识别失败]`，不中断整体（agent.py:972-1015）。
- 替换策略：把描述拼到末条 user 消息文本前（agent.py:1017+）。
- 图片不落盘；`client_meta.images` 只有 `{name,size,type}`。

### 2.3 相关基础设施与可复用先例

| 基础设施 | 位置 | 对 OCR 的复用价值 |
|---|---|---|
| 本地模型目录/降级 | `backend/memory/embedder_factory.py:44-122`、`embedder.py:141-148,222-240` | 可选依赖、`SAGE_USER_DATA_DIR/models/<name>`、设置偏好、预热、失败降级 |
| Electron 模型下载 | `electron/modelDownloadIpc.ts:38-52`、`electron/main.ts:1810-1815`、`src/pages/settings/MemoryTab.tsx:140` | 清单 + SHA-256 + 用户目录；OCR 模型下载直接复用 |
| 设置 preference | `src/entities/setting/settingsRegistry.ts:223-234`（`embedding_mode`）、`backend/data/settings_repo.py` `KEYS` | 新增 `ocr_config`，避开 `app_settings` 顶层白名单 |
| 多模态远端抽象 | `backend/services/multimodal/*` | 仅未来「云端 OCR 兜底」可复用；本地引擎独立 |
| Office 长任务 | `backend/office/worker_process.py:26-27,81`（512MB、单槽、超时/取消） | 批量 OCR 可参考；512MB 对 ONNX 可能偏紧，需单独参数化 |
| 持久化队列 | `backend/skills/review_queue.py:33,210,252`（SQLite + 单 worker） | 批量 OCR 队列的模板 |
| 空闲检测 | `backend/services/idle_detector.py` | 可选「闲时 OCR」 |
| 媒体存储 | `backend/services/multimodal/media_store.py` | 聊天图片不入库；仅附件/音频使用 |
| 工具注册 | `backend/tools/tool_bundles.py:172-209`、`backend/domain/tool_names.py:79`、`backend/agents/profiles.py:406-415,626-631` | 新工具三件套同步 |

### 2.4 约束

1. **双分支**：main 开发 3.10 / 打包 3.11.9；win7 3.8.10。OCR 核心必须 py38 安全；
   ONNX Runtime 在 Win7 上社区上限 1.14.1，官方不支持。
2. **安装包体积敏感**：无后端安装包体积棘轮；前端 `dist/assets` 有 12MB / 单 chunk 1.8MB 门禁。
   OCR 运行时（opencv-headless ~37MB + ORT ~10MB + rapidocr wheel ~26MB）与模型（~22MB）
   不应无脑进默认包。
3. **打包契约**：`backend/tests/contract/test_office_bundled_requirements.py` 要求 office 启动链路的
   发行包出现在 `requirements-bundled.txt`；OCR 若在启动链路顶层 import Pillow/新包，必须同步，
   否则安装版启动 `ModuleNotFoundError`。建议**全部延迟导入 + 能力位降级**。
4. **架构门禁**：新文件 ≤ 800 行（`architecture-baseline.json`；`main.py` 基线 1385 行）；
   `py38_hazard_scan`；后端覆盖率 80%。
5. **端口/启动契约**：OCR 不新增常驻服务、不新增端口。
6. **安全**：图片是不可信输入，解码要有字节/像素上限；OCR 文本注入 LLM 需防提示注入
   （作为「数据」而非指令，并加来源边界）。

---

## 3. 业界参考（2026-10 核实）

### 3.1 开源 OCR 引擎对比（桌面 + CPU + 离线 + 中文）

| 方案 | 形态/依赖 | 体积（核实/估算） | 中文/竖排/手写 | CPU 速度（官方基准） | 许可 | Py3.8 | Win7 | 结论 |
|---|---|---|---|---|---|---|---|---|
| **RapidOCR 3.x**（PP-OCR ONNX） | pip `rapidocr` + `onnxruntime`；无系统二进制 | wheel ~26MB；PP-OCRv5 mobile det 4.6MB + rec 16MB + cls ~1–2MB ≈ 22MB；运行时依赖（opencv-headless ~37MB + ORT ~10.6MB） | v5/v6 支持中英日、竖排、手写（竖排 server 0.931 / mobile 0.809；手写中文 server 0.581 / mobile 0.417） | PP-OCRv5 mobile：Xeon 0.61s/图；M4 1.10s；v6 tiny/small/medium：Xeon 0.22/0.61/3.31s，M4 0.35/1.29/5.55s | Apache-2.0 | 是（>=3.8；ORT 最高 1.19.2） | **官方不支持**；1.14.1 实验 | **main 推荐默认** |
| **PaddleOCR 3.x**（PaddlePaddle） | paddlepaddle wheel ~92MB，安装后更大 | 模型小、运行时大 | 同 PP-OCR | 同模型 | Apache-2.0 | 3.x 无 cp38 wheel；旧版受限 | 需实测 | 不用（体积/兼容） |
| **Tesseract 5 / 4.1** | 系统二进制 + 语言包；pytesseract 纯 Python | 引擎 ~30–50MB（估算）；fast：eng 3.92MB、chi_sim 2.35MB、chi_sim_vert 1.84MB | 印刷体可用；中文一般；竖排有 `chi_sim_vert`；手写弱 | 亚秒–数秒/页，中文明显慢 | Apache-2.0 | 是（pytesseract >=3.8） | Tesseract 5 官方 Win10/11；Win7 仅 4.1 非官方 | **兼容/降级后端；win7 默认** |
| **RapidOCR legacy**（1.4.4 + ORT 1.14.1） | pip；PP-OCRv4 mobile | wheel ~14MB；det 4.5MB + rec 10MB | 中英印刷体好；竖排/手写弱 | 老模型更快 | Apache-2.0 | 是（3.6–3.12） | 社区唯一实验先例，需真机验证 | **win7 实验路径，不承诺** |
| **EasyOCR** | PyTorch | torch wheel ~190MB，安装后 ~2GB | 中英可用 | 整页数秒；峰值 RSS ~1GB | Apache-2.0 | torch 2.4.1 最后 cp38 | 不建议（Win10+） | 不用 |
| **Surya 2.5** | PyTorch/llama.cpp，689M | 权重 1–2GB | 90+ 语言，版面强 | CPU 约 59s/页 | 代码 Apache-2.0；**权重 OpenRAIL-M**（商用受限） | 否（>=3.10） | 不实用 | 不用 |
| **PaddleOCR-VL-1.6**（0.9B） | VLM | BF16 ~1.8GB / GGUF q8 ~1.4GB | 109+ 语言，表格/公式/竖排强 | CPU 15–30s/页（交互不可接受） | Apache-2.0 | 否 | 不实用 | 未来可选/远程 |
| **dots.mocr / DeepSeek-OCR / olmOCR / MinerU** | VLM / 重流水线 | 3B–7B，GB 级 | 版面/表格/公式强 | 需 GPU | 许可证需逐个复核（MinerU AGPL-3.0） | 否 | 不实用 | 不做默认 |
| **Tesseract.js（WASM）** | 前端 JS | wasm + 语言数据 ~10–30MB | 一般 | 慢于原生 | Apache-2.0 | 不受 Python 限制 | Chromium 106 可运行（需验证） | 备选（纯前端降级） |

> PP-OCR CPU 数据来自官方在 Intel Xeon 8350C / Apple M4 的端到端基准；桌面低功耗 CPU 通常更慢，
> 本项目目标机器需实测。模型/运行时体积为包元数据或社区实测，标注「估算」的需复核。
> **关键判断**：同时满足「CPU + 离线 + 中文 + 小体积 + Py3.8」的只有 RapidOCR(ONNX) 与 Tesseract；
> RapidOCR 的 Win7 支持是硬边界，不能作为承诺。

### 3.2 onnxruntime 版本支持矩阵（PyPI 核实）

| ORT 版本 | Requires-Python | cp38 Windows wheel | Win7 |
|---|---:|---|---|
| **1.14.1**（2023-02） | 未声明 | 有 | 社区报告最后可用；需实测 |
| 1.15.1（2023-06） | 未声明 | 有 | 社区报告 1.15.0 起不可用 |
| 1.16.3 / 1.17.3（2023–2024） | 未声明 | 有 | 不支持 |
| **1.19.2**（2024-09） | 未声明 | **有（最后一个）** | 不支持 |
| 1.20.1（2024-11） | 未声明 | 无 | 不支持 |
| 1.21+（2025-04 起） | **>=3.10** | 无 | 仅 Win10/11 |

推荐 pin：

| 场景 | 组合 |
|---|---|
| main（Py3.10/3.11，Win10/11） | `rapidocr>=3.10,<4` + `onnxruntime==1.19.2` + PP-OCRv5 mobile（或 v6 small） |
| Py3.8 + Win10/11（如 win7 分支的非 Win7 用户） | `rapidocr>=3.10,<4` + `onnxruntime==1.19.2`；或 `rapidocr-onnxruntime==1.4.4` |
| Py3.8 + Win7（实验） | `rapidocr-onnxruntime==1.4.4` + `onnxruntime==1.14.1` + `numpy==1.24.4` + `opencv-python-headless==4.10.0.84` + PP-OCRv4 mobile；**真机验证后才启用** |
| 禁止 | Py3.8 上让 pip 自由解析 ORT/numpy；Win7 上使用 ORT >=1.15 |

### 3.3 主流 AI 应用的做法（核实）

**云端产品几乎不在本地先 OCR**：图片直接交给多模态模型；模型不支持图片时做能力门控或报错。

| 产品 | 聊天图片 | 文档/知识库图片 | 无视觉模型时 |
|---|---|---|---|
| ChatGPT / Claude / Gemini / Perplexity | 原生多模态；PDF 抽文本 + 页面图像 | 文档解析 | 换模型/报错；无「文本模型 + OCR」官方降级 |
| Microsoft Copilot | 原生视觉识别图片文字 | 365 文档/搜索索引 | 企业侧「OCR 建索引 + 检索」；Image to Text 为显式动作 |
| **Open WebUI** | 默认给视觉模型 | 支持 Tesseract、Docling、PaddleOCR-VL、MinerU 等抽取引擎 | 无 Vision 能力时隐藏图片入口；可能报「模型不支持图片输入」 |
| **AnythingLLM** | 必须多模态模型（文档明确要求） | 工作区图片走 `tesseract.js` OCRLoader；扫描 PDF 有 `ocrPDF` | 聊天侧无自动 OCR；模型拒绝/后端报错 |
| **LibreChat** | 「Upload to Provider」给视觉模型；「Upload as Text」走文本抽取/OCR | OCR 默认 Mistral OCR，可换本地 parser | 非视觉模型仍可能看到入口，收到 provider 错误 |
| **Jan** | 仅模型具备 `vision` 时显示 Add Images；历史中丢弃 `image/*`，工具图片替换为 “(image omitted: the model has no vision)” | 文档另行索引 | 显式占位，避免整段对话 400 |
| **Ollama** | 仅视觉模型；切换后附件标红「该模型不支持图片」，提交时排除但保留附件 | 无内置 OCR | 换模型即可继续，不丢附件 |
| **LM Studio / Dify** | 按模型能力门控 | Dify 的 Document Extractor/OCR 预处理 | 报「模型不支持图片」或静默丢弃 |

**文档类产品**：

- **Notion OCR Scanner**：识别嵌入图片文字，把文本放在每张图下方 callout，保留换行；
  **显式标记「无可读文字/质量低」的图片**；结果可编辑、原图保留。
- **Obsidian Text Extractor**：Tesseract.js 本地 OCR，按需抽取，结果缓存为本地 JSON；
  README 明确 PDF 只读文本层、手写不可用、语言包需联网下载（识别本地）。
- **Zotero + zotero-ocr**：右键「OCR PDF」生成带文本层的 `.ocr.pdf`，默认 300 DPI，
  外部 Tesseract + `pdftoppm`；原文件保留、结果可检索。
- **Apple Live Text / PowerToys Text Extractor**：系统级 OCR，结果覆盖在原图/剪贴板，可复制校对。

### 3.4 可借鉴的 5 条产品模式

1. **能力门控 + 附件状态机**（Jan/Ollama/Open WebUI）：模型无视觉时隐藏或标红入口；
   模型切换时**保留附件**，提交时按能力重新路由，而不是要求重新上传。
   对 Sage：附件状态 `pending / needs-vision / ocr-ready / sent`，切换模型只改路由。
2. **两条显式路径：原生视觉 vs OCR 文本**（LibreChat「Upload to Provider / Upload as Text」）：
   默认按能力自动选，但附件 chip 上显示路由标签（「视觉模型」「本地 OCR」），发送前可见、可覆盖。
3. **OCR 结果是可编辑的衍生内容，不是不可见前缀**（Notion callout / Zotero 文本层 / Obsidian 缓存）：
   保留原图与文本关联、页码/区域来源；文本可编辑、可复制、可重新识别；
   整体质量提示（低质量/空结果）比逐字置信度更常见，但逐行 bbox/置信度是高价值增强。
4. **聊天附件与文档入库分两条管线**（AnythingLLM/Open WebUI/LibreChat）：
   聊天追求「这一轮回答」，入库追求「可检索、可引用、可长期保存」；
   不要把文档 OCR 的复杂度塞进聊天上传路径。
5. **分级降级 + 可解释失败 + 隐私标签**：
   原生视觉 → 本地 OCR → 文档解析器 → 明确提示（换模型/装语言包/裁剪图片）；
   区分「无文本层 / 质量低 / 语言包缺失 / 模型不支持 / OCR 超时」；
   标明「本地处理」或「发送至第三方」；多页按页返回，允许只重试失败页。

---

## 4. 方案对比

### 方案 A：只把现有 Tesseract 接进聊天链路（最小改动）

- 做法：在 `_prepare_messages_with_images` 的报错分支前调用现有 OCR 的图片识别；
  新增 `ocr_image_data_url()`；前端把 OCR 可用性纳入 `visionUploadDisabled`。
- 优点：不新增 Python 依赖；win7 路径已有基础；工作量最小。
- 缺点：用户仍需自装 tesseract + 中文语言包；中文截图精度一般；Office 与聊天耦合；
  安装版缺 Pillow，仍需修打包；不解决「开箱即用」。

### 方案 B：统一 OCR 子系统 + RapidOCR 默认 + Tesseract 兼容（推荐）

- 做法：新建 `backend/services/ocr/`；main 默认 RapidOCR(ONNX)，Tesseract 兼容/降级；
  聊天、Agent 工具、Wiki、Office 全部走统一接口；设置/能力位/模型下载贯通。
- 优点：开箱可用（可选依赖 + 外置模型）、精度/速度更好、架构干净、可增量落地；
  Office 行为可兼容；模型下载复用 Electron 现有机制。
- 缺点：需处理 onnxruntime/opencv 的打包与版本 pin；Win7 不能使用 RapidOCR（硬边界）；
  需要目标机器性能与体积实测。

### 方案 C：远端视觉/OCR 兜底（补充）

- 做法：允许配置「OCR/视觉端点」，本地引擎不可用时调用；或复用 visionModel。
- 优点：无本地依赖、精度高（VLM）。
- 缺点：违背离线/隐私默认；有成本与延迟；不是「没有多模态模型」的答案。
- 结论：作为方案 B 之后的可选增强（「本地优先，云端可选」），一期不做。

**推荐：方案 B；main 与 win7 采用不同的默认引擎承诺。**

---

## 5. 推荐架构

### 5.1 分层

```
                     ┌──────────────────────────────────────────────┐
  聊天图片 data URL ─▶│ ChatImageRouter（agent 侧路由）               │
  Agent 工具图片路径 ▶│  原生 vision → visionModel → 本地 OCR → 报错  │
  Wiki 图片        ─▶│                                              │
  Office/PDF 页面  ─▶└───────────────┬──────────────────────────────┘
                                     ▼
                    ┌─────────────────────────────────────────────┐
                    │ OCR Service（统一接口 + 缓存 + 限流 + 降级）   │
                    │  recognize(image_bytes|PIL, lang, opts)      │
                    └───────┬───────────────┬─────────────────────┘
                            ▼               ▼
                 ┌──────────────────┐  ┌──────────────────┐
                 │ RapidOCR Engine  │  │ Tesseract Engine │  (Null Engine)
                 │ onnxruntime+模型  │  │ pytesseract+二进制 │
                 └──────────────────┘  └──────────────────┘
                            ▲
                 ┌──────────────────┐
                 │ Model Manager    │  userData/models/rapidocr + SHA-256 + 离线
                 └──────────────────┘
```

### 5.2 核心接口与数据模型

`backend/services/ocr/models.py`（纯 dataclass，py38 安全）：

```python
@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float          # 0-1（各引擎归一化）
    bbox: Optional[Tuple[int, int, int, int]] = None  # x1,y1,x2,y2

@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: Tuple[OcrLine, ...]
    engine: str                # "rapidocr" | "tesseract"
    lang: str
    duration_ms: int
    image_sha256: str
    cached: bool = False
    quality: str = "ok"        # "ok" | "low_confidence" | "empty" | "failed"
    error: Optional[str] = None

@dataclass(frozen=True)
class OcrOptions:
    lang: str = "auto"         # 统一语言标签，引擎内部映射
    min_confidence: float = 0.4
    max_side: int = 2048       # 长边上限，超出先缩放
    timeout_s: float = 30.0
```

`backend/services/ocr/engine.py`：

```python
class OcrEngine(Protocol):
    name: str
    def available(self) -> Tuple[bool, str]: ...
    def recognize(self, image: Any, opts: OcrOptions) -> OcrResult: ...
```

`backend/services/ocr/service.py`：

- `get_ocr_service()` 单例；`init_ocr_service()` 在 lifespan 装配（参考
  `services/scheduler.py:117,642-649` 与 `services/todo_service.py:101,686-694` 的模式）；
- `recognize_bytes(data, *, source)`：校验（字节/像素上限）→ 解码 → 缩放 → 缓存（sha256）
  → 引擎 → 结果；
  - **不硬依赖 Pillow**：RapidOCR 用 OpenCV 原生解码；Tesseract 路径写临时文件后传路径；
    PDF 页面由 PyMuPDF 输出 PNG 字节直接喂引擎；Pillow 仅在可用时做可选预处理；
- `recognize_data_url(url)`、`recognize_path(path)`；
- 任何异常 → 结构化失败结果，**绝不把 OCR 故障升级为聊天失败**；
- 线程池执行（py38 无 `asyncio.to_thread` → `loop.run_in_executor` +
  `contextvars.copy_context()`，与项目既有 py38 async 桥一致）。

### 5.3 路由决策（无视觉模型时的兜底链）

在 `Agent._prepare_messages_with_images`（agent.py:801-836）中把两段式改为可配置链：

```
1. chatModel 明确支持 vision（或能力未知，且未显式 prefer_local）→ 原生注入
2. visionModel 已配置 → caption_image（现状）
3. 本地 OCR 可用 → recognize_bytes，替换为文本
4. 以上都不可用 → VisionNotAvailableError（文案补充「或启用本地 OCR」）
```

- 默认顺序保持现状：`native_vision > vision_model > local_ocr`，OCR 只在「都没有」时兜底；
- 新增 `ocr.prefer_local_for_images`（默认 false）：有视觉模型时也优先 OCR（纯文字截图更快更省）；
- 能力未知仍按「支持 vision」处理，不自动 OCR，避免改变现有用户行为。

注入格式（与现有描述替换同构）：

```
[图 1 文字内容 · 本地 OCR · 引擎 rapidocr]
第一行……
第二行……

[图 2 文字内容 · 本地 OCR · 识别置信度较低，请核对]
……

<用户原始文本>
```

- 明确「这是 OCR 文本，不是图片本身」；低置信度加提示；空结果写
  `[图 1 未识别到文字（可能是图片质量低或无文字）]`，不要静默发送空串；
- 前端消息可保留缩略图（来自当次请求的 data URL / 乐观消息），刷新后原图不保证存在
  （现状如此）。

### 5.4 集成点

| 集成点 | 改动 | 说明 |
|---|---|---|
| 聊天图片 | `agent.py::_prepare_messages_with_images` + `_replace_images_with_text` | 主场景；保持不可变返回 |
| 前端上传门控 | `ChatInput.tsx:129-132,758-763` | `ocrAvailable` 纳入 `visionUploadDisabled`；新增 OCR 路由标签 |
| OCR 能力源 | 新增 `GET /api/v1/ocr/capabilities` | 聊天页当前拿不到 `GET /office/capabilities`，需独立能力端点 |
| Agent 工具 | `backend/tools/ocr_image_tool.py` | 在 `tool_bundles.py:172` 附近注册；同步 `domain/tool_names.py:79`、`agents/profiles.py` 白名单与可见性计数 |
| Wiki 摄入 | `backend/wiki/vision_ingest.py:75-170`、`vision.py` | 无 vision 配置时用 OCR 文本替代 caption（可配置） |
| Office/PDF | `backend/office/ocr.py` 改为薄适配层 | 保留 `SAGE_OCR`/`SAGE_OCR_LANG`/`SAGE_OCR_MIN_CONFIDENCE` 语义；`ocr_available/ocr_languages` 返回不变 |
| REST | 新增 `backend/api/ocr_routes.py` | `POST /api/v1/ocr/image`、`GET /api/v1/ocr/capabilities`；在 `main.py` include（注意 1385 行基线棘轮） |
| 共享类型 | `src/shared/api/types/templateAndTaskTypes.ts` | `OfficeCapabilities` 增加可选 `ocr_engine`/`ocr_model_ready` |

工具定义建议：

```json
{
  "name": "ocr_image",
  "description": "对本地图片/截图做 OCR，提取文字。适用于模型无法直接看图的场景。",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "工作区内图片路径"},
      "media_id": {"type": "string", "description": "聊天媒体 ID（与 path 二选一）"},
      "lang": {"type": "string", "enum": ["auto", "ch", "en"], "default": "auto"}
    },
    "required": []
  }
}
```

工具应为 READ 级、`requires_tool_context = True`（与 `OfficeReadTool`/`OfficeReadPdfTool` 一致），
超时与大小限制由 OCR Service 统一执行。

### 5.5 模型管理与离线

复用 embedder + Electron 模型下载模式：

- 目录优先级：`SAGE_OCR_MODEL_DIR` > `SAGE_USER_DATA_DIR/models/rapidocr/`；
  目录存在时要求 `det.onnx`/`rec.onnx` 齐备，否则回退包内默认模型；
- **RapidOCR 3.x wheel 自带 PP-OCRv6 small 模型**（实测 det/rec/cls 均在
  `site-packages/rapidocr/models/`），因此 pip 安装后即可离线使用；
  外置目录用于指定更大/更小的模型或 PP-OCRv5 等版本；
- 模型选择：main 默认 PP-OCRv5 mobile（≈22MB）；可提供「更高精度」PP-OCRv6 small 可选下载；
- 缓存：`sha256(image) + engine + lang` → 文本/结果，落 `SAGE_USER_DATA_DIR/cache/ocr/`
  （JSON 或 SQLite）；聊天图片本身不落盘，缓存只存文本与元数据；
- Windows 7：不提供 RapidOCR 模型下载入口（或标注实验），默认引导 Tesseract。

### 5.6 设置与 UI

**设置落点**：新增 preference blob `ocr_config`（`SettingsRepository.KEYS` +
`settingsRegistry.ts` `storage: 'preference'`），避免动 `app_settings` 白名单 6 处联动。
同时保留环境变量覆盖（兼容现有 Office 路径）。

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | true（引擎可用时） | 总开关 |
| `engine` | enum | `auto` | `auto/rapidocr/tesseract` |
| `lang` | enum | `auto`（中英） | `auto/ch/en` |
| `prefer_local_for_images` | bool | false | 有视觉模型时也优先本地 OCR |
| `chat_fallback_order` | list | 见 §5.3 | 高级设置，可重排 |
| `max_side` / `timeout_s` | int | 2048 / 30 | 性能保护 |

UI：

1. **设置 → 模型/多模态**：新增「本地 OCR」区块（引擎、状态、模型下载、语言、测试按钮、
   隐私说明「本地处理，不上传」）；
2. **聊天输入区**：OCR 可用时不再禁用图片；提示「图片将通过本地 OCR 识别后转为文本」；
   附件 chip 显示路由标签（视觉模型 / 本地 OCR），发送前可切换；
3. **消息/附件预览**：OCR 结果折叠块（引擎、字符数、质量提示、可复制/编辑/重试）；
   空结果与失败显示原因与下一步动作；
4. **能力徽章**：`OfficeCapabilityBar` 的 OCR 徽章显示实际引擎（rapidocr/tesseract）。

### 5.7 性能、可靠性与安全

- 输入保护：单图解码后 ≤5 MiB（沿用聊天限制）；长边缩放到 `max_side`；像素数上限防解压炸弹；
- 并发：默认 1–2 并发（CPU 推理），超出排队；批量 PDF 页走后台队列；
- 超时：单图默认 30s；超时返回失败占位，不阻塞聊天；**现有 OCR 无超时，需一并补上**；
- 失败语义：单张失败填 `[图片文字识别失败：原因]`，多张互不影响；
- 缓存命中直接返回；引擎初始化预热一次；
- 批量：参考 `ReviewQueue` 的 SQLite 持久化 + 单 worker；或 `SchedulerService.register_system_task`
  周期 drain；CPU 重活可参考 `office/worker_process.run_json_worker`，但需为 OCR 单独设置
  内存/超时（现有 512MB 单槽不一定够）；
- 安全：默认零上传；OCR 文本以明确边界注入（「以下为 OCR 文本，可能含噪声」）；
  不执行图片内嵌指令；模型 SHA-256 校验；日志不输出图片内容与完整识别文本。

---

## 6. 双分支与打包

| 层 | 能力 | main | release/win7 | 依赖/说明 |
|---|---|---|---|---|
| Core | OCR 接口、Tesseract 引擎、聊天兜底、`ocr_image` 工具 | ✅ | ✅ | Pillow（需补 bundled）、pytesseract 可选 |
| Default | RapidOCR 引擎（ONNX） | ✅ 推荐 | ❌ 不承诺（实验路径） | `rapidocr>=3.10,<4` + `onnxruntime==1.19.2` |
| Model | OCR 模型（PP-OCRv5 mobile ≈22MB） | ⚠️ 外置/下载 | ⚠️ 不含 | 复用 Electron 下载器 |
| Win7 实验 | RapidOCR 1.4.4 + ORT 1.14.1 | — | ⚠️ 真机验证后才可选项 | PP-OCRv4 mobile；不默认启用 |
| Enhanced | 云端 OCR/视觉兜底 | ⚠️ 可选 | ⚠️ 可选 | 未来接 multimodal 抽象 |

打包要点：

- **Pillow**：**不建议为此改动 bundled 的既有决策**。OCR 核心不硬依赖 Pillow：
  RapidOCR 用 OpenCV 解码；Tesseract 路径写临时文件；PDF 用 PyMuPDF 输出 PNG 字节。
  若某条预处理确实需要 Pillow，则延迟导入并能力位降级。
- 新增 office 启动链路依赖需同步
  `backend/tests/contract/test_office_bundled_requirements.py`。
- **onnxruntime / rapidocr / opencv**：可选依赖，不进默认 `requirements.txt`；
  若 main 要「开箱可用」，把 `rapidocr` + `onnxruntime==1.19.2` +
  `opencv-python-headless` 加入 bundled 并确认 cp311 win_amd64 wheel、运行期延迟 import；
  否则默认能力为 Tesseract（用户自装）+ 模型/引擎手动启用。
- **Win7**：不要加入 rapidocr/paddlepaddle/torch 到基础依赖；Tesseract 4.1 构建作为可选/引导；
  不捆绑完整 TeX 类大依赖。
- **模型**：不进 `resources/` 默认包；走 `SAGE_USER_DATA_DIR/models/rapidocr`；
  无安装包体积棘轮，但需在 PR 中记录增量。
- **CI**：`py38_hazard_scan`、新文件 ≤800 行、覆盖率 80%；`main.py` 若加路由需处理基线棘轮。

---

## 7. 分阶段实施

### 实施记录（2026-10-31，`feat/local-ocr`）

已完成 M0 + M1 核心 + M2 工具面：

- `backend/services/ocr/`：`models.py` / `config.py` / `engine.py` / `service.py` /
  `engines/tesseract.py` / `engines/rapidocr.py`；进程内 LRU、失败折叠、配置动态读取；
- `backend/office/ocr.py`：改为统一服务适配层，保留 `SAGE_OCR*` 语义；补 Tesseract 超时；
- `backend/office/capabilities.py`：能力位改走统一服务；
- `backend/core/legacy/agent.py`：新增本地 OCR 兜底层（默认 `原生视觉 > visionModel > 本地 OCR > 报错`，
  `prefer_local_for_images` 可改变默认）；
- `backend/api/ocr_routes.py`：`GET /api/v1/ocr/capabilities`、`POST /api/v1/ocr/image`，已挂载；
- `backend/tools/ocr_image_tool.py` + `MULTIMODAL_TOOLS` / `tool_bundles` 注册；
- `backend/data/settings_repo.py`：新增 `ocr_config` preference；前端 `settingsRegistry` 同步元数据；
- 前端 `ChatInput`：OCR 能力探测、上传门控、`chat.ocr_fallback_info` 提示；
- Wiki：`POST /wiki/vision` 视觉失败时回退本地 OCR（响应 `mode=ocr`/`engine`）；
  `VisionIngestConfig.vision_config` 可缺省，caption 缺失/失败时回退 OCR 文本；
- 设置页：新增「本地 OCR」卡片（引擎状态、引擎选择、识别语言、测试识别按钮、
  `prefer_local_for_images`），通过 `ocr_config` preference 持久化；
- 聊天输入区：新增「图片文字（本地 OCR）」预览卡片，支持查看、复制、编辑、重新识别；
  编辑后的文本通过 `image_ocr_texts` 随消息发送，Agent 直接采用、不再重复识别；
- 性能调优：截图默认 `max_side=1280` + 关闭方向分类，Office 扫描页保留 2048 + 分类；
- 文档：`docs/technical/116-local-ocr.md` + `docs/user-manual/29-local-ocr.md`；
- 基准：`scripts/ocr_benchmark.py`（合成图 + CER + 耗时，可 JSON 输出）；
- 打包收口（2026-10-31 P0）：main 安装包捆绑 `rapidocr==3.10.0` +
  `onnxruntime==1.19.2` + `opencv-python-headless==4.11.0.86` + `Pillow`
  （`requirements-bundled.txt`，新增契约测试）；Office 扫描页 OCR 改为
  `ocr_config.office_enabled` 设置（`SAGE_OCR` 兼容覆盖）；
  单图 20k / 总量 60k 文本注入上限；Electron 自动探测
  `resources/tesseract/tesseract[.exe]` 并注入 `SAGE_TESSERACT_PATH`；
- P1 开发（2026-10-31）：发送后消息气泡展示 OCR 文本
  （`client_meta.image_ocr_texts`，每图 4k/总量 8k）；`/ocr/reload` 与设置页
  tiny 模型下载/恢复；`ocr_benchmark.py --manifest` 分类统计；
  `.github/workflows/ocr-smoke.yml` 真实 RapidOCR 冒烟；
- 测试：新增 6 个测试文件（服务/引擎、Agent 兜底、工具、REST、ChatInput、Wiki 回退），
  相关后端 98 项、前端 15 项通过；`ruff`、ESLint、`check_py38_compat`、
  `architecture-check` 通过。
- 真实冒烟（临时 venv：Python 3.10 + `rapidocr>=3.10,<4` + `onnxruntime==1.19.2`）：
  900×240 中英混排图识别正确（`Sage 本地 OCR 测试 2026` / `Invoice No: A-1024 Total: 88.00`），
  首次调用约 2.3s（含模型加载），预热后约 1.8s，缓存命中 0ms；RapidOCR wheel 自带
  PP-OCRv6 small 模型，模型目录为可选覆盖项。
- 1080p 基准（同上环境，PP-OCRv6 small，10 行文本）：默认参数预热后约 **3.0–3.2s**；
  调优为 `max_side=1280` + 关闭方向分类（`use_cls=False`）后，安静机器上约 **1.2–2.0s**
  （多次运行有波动），CPU 争用时可达 2.5–4s。截图场景默认采用该组合；Office 扫描页
  仍使用 `max_side=2048` + `use_cls=True` 保真。识别内容一致，quality=`ok`。
- 可复现基准（`scripts/ocr_benchmark.py`，1600×900 / 10 行合成文本）：中位 **1272ms**，
  CER **1.59%**（3 次，RapidOCR PP-OCRv6 small，1280/关分类）。

待完成：

- main/win7 正式安装包构建与体积实测（OCR 依赖 wheel 合计约 107MB）；
- Win7 安装包是否捆绑 Tesseract 4.1 的最终决策与真机冒烟；
- 设置页模型下载器（Electron 清单/SHA-256/进度；默认 small 模型已随 wheel 提供）；
- 真实业务截图/低配机的 CER 基准（合成基准已完成）；
- 已发送消息中的 OCR 文本展示与 PDF/多图批处理。



### M0：统一 OCR 接口 + Tesseract 迁移 + 聊天兜底（1 周）

- [x] `backend/services/ocr/`：models/engine/service/registry/config；
- [x] `TesseractEngine` 包装现有 `backend/office/ocr.py`（行为不变，补超时）；
- [x] `backend/office/ocr.py` 改为薄适配层；现有 14 项测试全绿；
- [x] `agent.py` 增加本地 OCR 分支（默认顺序不变）；
- [x] 前端 `visionUploadDisabled` 纳入 OCR；提示文案；
- 验收：Office OCR 行为不变；本机有 tesseract 时，无视觉模型聊天可继续；py38 扫描通过。

### M1：RapidOCR 默认引擎 + 模型管理（1–2 周）

- [x] `RapidOcrEngine`（懒加载、超时、置信度归一化、bytes/临时文件兼容）；
- [x] 模型目录/可用性探测；`ocr_config` preference 与能力端点；
- [ ] 模型 SHA-256 校验/预热（待设置页下载器接入）；
- [x] `auto` 选择：RapidOCR > Tesseract；失败自动降级；
- [x] 结果缓存（sha256）；
- [x] 单图性能基准与调优（截图 1280/关分类约 1.2–2.0s；Office 2048/开分类保真；
  `scripts/ocr_benchmark.py` 实测中位 1272ms / CER 1.59%）；
- 验收：目标机器 1080p 截图 P95 < 2s（模型已加载）；中文截图 CER 相对 Tesseract 基线下降 ≥30%；
  引擎缺失无异常、UI 给可操作提示。

### M2：Agent 工具 + Wiki/预览集成（1 周）

- [x] `ocr_image` 工具（工具三件套、profile 白名单、schema 契约测试）；
- [x] Wiki 图片摄入无视觉模型时用 OCR（`/wiki/vision` + `vision_ingest`）；
- [x] 前端 OCR 结果查看/复制/编辑/重新识别（`ImageOcrPreview`）；
- [x] 编辑结果随消息发送（`ChatRequest.image_ocr_texts`，Agent 直接采用）；
- 验收：Agent 能对工作区截图调用 OCR；工具可见性计数与白名单测试通过。

### M3：设置 UI + 模型下载 + 文档（1–2 周）

- [x] 设置页 OCR 区块（引擎状态/引擎选择/语言/测试识别/优先策略/隐私说明）；
- [ ] 复用 Electron 模型下载器（清单/SHA-256/进度/取消）；RapidOCR wheel 已自带 small 模型，
      下载器主要用于 tiny/更大模型的可选升级；
- [x] 技术文档章节 + 用户手册（`116-local-ocr.md` / `29-local-ocr.md`）；
- 验收：新用户无需命令行即可启用；离线环境手动放置模型可工作。

### M4：win7 收口与批量能力（1 周）

- [ ] win7 实测 Tesseract 4.1 路径；RapidOCR 1.4.4 + ORT 1.14.1 实验矩阵；
- [ ] 批量 PDF/多图 OCR 走持久化队列（参考 ReviewQueue）；
- [ ] 体积与性能回归；
- 验收：win7 全量测试绿；核心路径无 ImportError；RapidOCR 在 Win7 未验证前默认关闭；
  安装包体积增量有记录。

---

## 8. 测试与质量门禁

- 单元：引擎选择、语言映射、置信度过滤、缩放、超时、缓存、空结果/失败占位；
- 集成：聊天无视觉模型链路（fake engine）、Office PDF 扫描页、Agent 工具调用、
  `ocr_config` 读取与 env 覆盖；
- 前端：`ChatInput` 门控三态（vision / visionModel / OCR）、路由标签、结果折叠块、设置页；
- 黄金样本：中文截图、英文文档、表格截图、低质量拍照、竖排文字（预期降级）、空图/纯图；
- 性能：单图 P50/P95、内存峰值、首次加载；低配机 2–5s 可接受；
- 打包：main/win7 双分支安装包体积对比；`py38_hazard_scan`；架构基线（≤800 行）；
  bundled requirements 契约；
- 安全：超大图/解压炸弹/损坏图片/提示注入样本文本。

| 指标 | 目标 |
|---|---|
| 中文印刷体截图 CER | 相对 Tesseract 基线下降 ≥30%（RapidOCR，黄金样本） |
| 单张 1080p 截图 P95 | <2s（CPU、模型已加载；低配机放宽） |
| OCR 失败对聊天的破坏率 | 0（失败仅占位） |
| 空结果提示覆盖率 | 100%（不静默发送空串） |
| win7 核心路径可用性 | 100%（无引擎时明确提示，不崩溃） |
| 安装包增量 | 不含模型 ≤5MB；含模型 ≤25MB（建议值，需实测确认） |

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| onnxruntime 与 Win7/Py3.8 不兼容 | win7 无法用 RapidOCR | Win7 只用 Tesseract 4.1；RapidOCR 实验路径真机验证；能力位降级 |
| main 安装包无 Pillow（刻意不含） | 现有 Tesseract 路径在安装版不可用 | OCR 核心不依赖 Pillow：OpenCV 解码 / 临时文件 / PyMuPDF PNG；需要时延迟导入降级 |
| 模型分发体积/许可 | 安装包膨胀/合规 | 外置 + Electron 下载；PP-OCR/Tesseract 均 Apache-2.0；VLM 权重许可逐个复核 |
| 中文截图精度不及预期 | 用户体验差 | 黄金样本实测；可切 Tesseract/视觉模型；结果可编辑 |
| OCR 文本注入污染上下文 | 噪声/提示注入误导 | 来源标签 + 边界声明 + 长度截断 + 质量提示 |
| 大图/恶意图片 | 内存/CPU 打满 | 字节/像素上限、缩放、超时、并发限制 |
| 聊天链路阻塞 | 首帧延迟 | 线程池 + 超时 + 失败占位；模型预热 |
| 双分支漂移 | win7 破坏 | 核心 py38 安全；新增代码两环境跑测试 |
| 与 visionModel 策略冲突 | 行为变化 | 默认顺序保持现状；新行为需显式设置 |
| 能力未知被误判 | 图片被塞给文本模型 | 维持 unknown→vision；OCR 只在确认不支持时触发 |
| 无媒体持久化 | 刷新后无法回看原图 | 明确一期不承诺；如需要另立「聊天图片落盘」需求 |
| 批量 OCR 内存 | worker 512MB 可能不够 | 单独参数化内存/超时；分页处理 |

---

## 10. YAGNI / 明确不做

- 不做 VLM 本地推理（PaddleOCR-VL / dots.mocr / DeepSeek-OCR / olmOCR / MinerU）；
- 不做版面分析/表格结构化/阅读顺序（一期只出文本行）；
- 不做手写体、公式、乐谱识别保证；
- 不做云端 OCR 默认接入；
- 不做自动翻译；
- 不做图片内容理解（场景/人物）；
- 不为 OCR 单独常驻服务或端口；
- 不承诺聊天图片长期存储与历史回看；
- 不在 Win7 上承诺 RapidOCR（仅实验、默认关闭）。

---

## 11. 推荐决策（待评审确认）

1. **架构**：统一 `backend/services/ocr/` 子系统，替换 Office 私有实现，所有调用点走同一接口。
2. **引擎**：main 默认 RapidOCR(ONNX，PP-OCRv5 mobile)；Tesseract 兼容/降级；
   win7 默认 Tesseract 4.1（RapidOCR 实验、默认关闭）。
3. **聊天策略**：默认 `原生视觉 > visionModel > 本地 OCR > 报错`；OCR 仅在确认无视觉能力时自动触发；
   `prefer_local_for_images` 需用户显式开启。
4. **模型分发**：外置 + 设置页下载（Electron 清单 + SHA-256），不默认进安装包。
5. **UI 诚实**：附件显示路由标签；OCR 结果可查看/复制/编辑/重试；失败给可操作原因。
6. **工具**：新增 `ocr_image`，接入工具三件套与 profile 白名单。
7. **失败语义**：OCR 故障永远不升级为聊天失败；空结果显式提示。
8. **双分支**：核心零阻塞 py38；ONNX 引擎能力位探测；Win7 不以 RapidOCR 作为承诺。

---

## 12. 参考资料

开源引擎/模型：

- RapidOCR 文档与 FAQ（Win7 不支持说明）：https://rapidai.github.io/RapidOCRDocs/main/
  https://rapidai.github.io/RapidOCRDocs/main/en/faq/faq/
- RapidOCR 模型列表/对比：
  https://rapidai.github.io/RapidOCRDocs/main/model_list/
  https://github.com/RapidAI/RapidOCRDocs/blob/main/docs/blog/posts/about_model/model_summary.md
- PaddleOCR / PP-OCRv5（竖排、手写准确率）：
  http://www.paddleocr.ai/v3.0.3/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
- PP-OCRv6 官方文档（CPU 基准、参数量）：
  https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html
- PaddleOCR-VL：https://ernie.baidu.com/blog/posts/paddleocr-vl/ ·
  https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6
- Tesseract 支持的操作系统（Win10/11）：
  https://tesseract-ocr.github.io/tessdoc/supported-operating-systems.html
- tessdata_fast / best：https://github.com/tesseract-ocr/tessdata_fast ·
  https://github.com/tesseract-ocr/tessdata_best
- ONNX Runtime 兼容性与版本：https://onnxruntime.ai/docs/reference/compatibility ·
  https://pypi.org/project/onnxruntime/#history
- ONNX Runtime Win7 失败案例：https://stackoverflow.com/questions/76324358/failed-to-use-onnxruntime-on-windows-7
- EasyOCR：https://github.com/JaidedAI/EasyOCR
- Surya（OpenRAIL-M 权重）：https://github.com/datalab-to/surya
- dots.mocr：https://github.com/rednote-hilab/dots.mocr
- DeepSeek-OCR（MIT）：https://github.com/deepseek-ai/DeepSeek-OCR
- olmOCR：https://github.com/allenai/olmocr
- MinerU（Py3.11+，AGPL-3.0）：https://github.com/opendatalab/MinerU
- GOT-OCR2.0：https://github.com/Ucas-HaoranWei/GOT-OCR2.0
- Florence-2：https://huggingface.co/microsoft/Florence-2-large
- Nanonets-OCR-s：https://huggingface.co/nanonets/Nanonets-OCR-s
- Qwen3-VL：https://github.com/QwenLM/Qwen3-VL
- HunyuanOCR（非 OSI 许可）：https://github.com/Tencent-Hunyuan/HunyuanOCR
- Tesseract.js：https://github.com/naptha/tesseract.js

产品实践：

- OpenAI File inputs：https://developers.openai.com/api/docs/guides/file-inputs
- Claude Vision / PDF support：https://platform.claude.com/docs/en/build-with-claude/vision.md ·
  https://platform.claude.com/docs/en/build-with-claude/pdf-support.md
- Claude 上传限制：https://support.claude.com/en/articles/8241126-upload-files-to-claude
- Gemini media resolution：https://ai.google.dev/gemini-api/docs/media-resolution
- Perplexity 图片上传：https://www.perplexity.ai/help-center/en/articles/10354840-uploading-images-on-perplexity
- Open WebUI 文档抽取：https://docs.openwebui.com/features/chat-conversations/rag/document-extraction
- AnythingLLM OCRLoader：
  https://github.com/Mintplex-Labs/anything-llm/blob/master/collector/utils/OCRLoader/index.js
- LibreChat OCR：https://www.librechat.ai/docs/features/ocr
- Jan 文件上传：https://docs.jan.ai/desktop/file-upload
- Ollama 图片能力提交：
  https://github.com/ollama/ollama/commit/9517864603cae252d28a608a7afbc490b42976d6
- LM Studio 图片问题：https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/362
- Dify 文档提取：https://github.com/langgenius/dify
- Notion OCR Scanner：https://www.notion.com/ko/custom-agent-templates/ocr
- Obsidian Text Extractor：https://github.com/scambier/obsidian-text-extractor
- Zotero 搜索（无 OCR）：https://www.zotero.org/support/preferences/search ·
  https://github.com/UB-Mannheim/zotero-ocr
- Apple VisionKit：https://developer.apple.com/documentation/visionkit
- PowerToys Text Extractor：
  https://learn.microsoft.com/en-us/windows/powertoys/text-extractor
- OCRBench v2（困难 OCR 基准）：https://proceedings.neurips.cc/paper_files/paper/2025/hash/8c2e6bb15be1894b8fb4e0f9bcad1739-Abstract-Datasets_and_Benchmarks_Track.html

项目内相关文件：

- `backend/office/ocr.py`、`backend/tests/unit/office/test_ocr.py`
- `backend/core/legacy/agent.py::_prepare_messages_with_images`（801-836）
- `backend/wiki/vision.py`、`backend/wiki/vision_ingest.py`
- `backend/memory/embedder_factory.py`、`electron/modelDownloadIpc.ts`
- `src/widgets/chat/ChatInput.tsx:121-132,719-730,758-763`
- `backend/data/settings_repo.py`、`src/entities/setting/settingsRegistry.ts`
- `docs/superpowers/specs/2026-10-14-vision-model-fallback-design.md`
- `docs/superpowers/specs/2026-09-12-multimodal-capabilities-design.md`
- `docs/plans/2026-10-31_word-document-intelligence.md`（明确 OCR 另案）
