# 本地 OCR（本地文字识别）

> 状态：已实现（2026-10-31，main PR #2696）
> 适用：聊天图片、Office/PDF 扫描页、Wiki 图片、Agent 工具
> 相关代码：`backend/services/ocr/`、`backend/office/ocr.py`、`backend/core/legacy/agent.py`、`backend/api/ocr_routes.py`、`backend/tools/ocr_image_tool.py`、`src/widgets/chat/ImageOcrPreview.tsx`、`src/pages/settings/LocalOcrCard.tsx`

## 1. 能力概述

本地 OCR 用于「没有多模态模型」或「只想取图片文字」的场景：

- 聊天图片：对话模型不支持视觉且未配置视觉模型时，自动把图片识别为文本继续对话；
- 手动优先：用户可设置「有视觉模型时也优先本地 OCR」，适合纯文字截图；
- 图片文字预览：聊天输入区展示识别结果，可复制、编辑、重新识别；编辑后的文本随消息发送；
- Office/PDF：扫描页（文本层近乎为空）走同一 OCR 服务；
- Wiki：视觉模型失败时回退本地 OCR；
- Agent 工具：`ocr_image` 可读取工作区图片或聊天媒体并返回文本。

## 2. 架构

```
聊天图片 data URL ─┐
Agent 工具图片路径 ─┤
Wiki 图片         ─┼─▶ OCR Service（backend/services/ocr/service.py）
Office/PDF 页面   ─┘        │
                            ├─ RapidOCR（onnxruntime + PP-OCR 模型）
                            └─ Tesseract（pytesseract + 系统二进制）
```

- 引擎实现：`backend/services/ocr/engines/rapidocr.py`、`tesseract.py`；
- 统一模型：`OcrLine / OcrResult / OcrOptions`（纯 dataclass，py38 安全）；
- 配置：`backend/services/ocr/config.py` 读取 preference `ocr_config`；
- 失败语义：`recognize_*` 永不抛异常，返回 `quality=failed` 与 `error` 字段；
- 缓存：进程内 LRU，键为 `(sha256, engine, lang, min_confidence, max_side, use_cls)`。

## 3. 路由顺序

`SageAgent._prepare_messages_with_images`（`backend/core/legacy/agent.py`）：

1. 对话模型明确支持（或能力未知）vision → 原生 `image_url`；
2. 确认不支持 vision 且配置了 visionModel → 视觉模型生成描述；
3. 本地 OCR 可用 → 识别为文本并替换图片；
4. 都不可用 → `VisionNotAvailableError`。

例外：`ocr_config.prefer_local_for_images=true` 且本地 OCR 可用时，即使对话模型支持 vision 也优先 OCR。

注入格式示例：

```
[图片 1 文字内容 · 本地 OCR · 引擎 rapidocr]
第一行……
第二行……

<用户原始文本>
```

`prefer_local_for_images` 与 `image_ocr_texts`（前端编辑后的文本）同时存在时，Agent 直接采用前端文本，不再重复识别。

## 4. 配置（preference `ocr_config`）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | true | 总开关 |
| `engine` | `auto/rapidocr/tesseract` | `auto` | `auto` 优先 RapidOCR，缺失时回退 Tesseract |
| `lang` | `auto/ch/en` | `auto` | Tesseract 语言；RapidOCR 使用模型语言 |
| `prefer_local_for_images` | bool | false | 有视觉模型时也优先 OCR |
| `min_confidence` | float 0–1 | 0.4 | 低置信度过滤 |
| `max_side` | int | 1280 | 长边上限；截图默认 1280，Office 扫描页覆盖为 2048 |
| `timeout_s` | float | 30 | Tesseract 调用超时；RapidOCR 由外层超时保护 |
| `use_cls` | bool | false | RapidOCR 方向分类；截图默认关闭，Office 扫描页开启 |

环境变量兼容：`SAGE_OCR=1`（Office 显式开启）、`SAGE_OCR_LANG`、`SAGE_OCR_MIN_CONFIDENCE`、`SAGE_OCR_MODEL_DIR`。

## 5. 引擎与打包

### RapidOCR（推荐）

- 可选依赖：`rapidocr>=3.10,<4` + `onnxruntime==1.19.2`；
- wheel 自带 PP-OCRv6 small det/rec + 方向分类模型（约 31MB），安装后离线可用；
- 自定义模型目录：`SAGE_OCR_MODEL_DIR` 或 `SAGE_USER_DATA_DIR/models/rapidocr/`
  （`det.onnx` + `rec.onnx`，可选 `cls.onnx`）。

### Tesseract（兼容/降级）

- 可选依赖：`pytesseract` + 系统 `tesseract` 二进制；中文需 `chi_sim` 语言包；
- Win7 建议 Tesseract 4.1 兼容构建；Tesseract 5 官方只支持 Win10/11。

### 平台矩阵

| 平台 | RapidOCR | Tesseract |
|---|---|---|
| main（Py3.11，Win10/11） | 推荐（ORT 1.19.2） | 可用 |
| win7（Py3.8，Win7） | 不承诺；ORT 1.14.1 仅实验 | 推荐（4.1） |

RapidOCR/onnxruntime 未进默认安装包；缺依赖时能力位降级，不影响主程序启动。

## 6. REST / 工具

- `GET /api/v1/ocr/capabilities`：引擎、模型、语言可用性；
- `POST /api/v1/ocr/image`：请求 `{image: data URL, lang?}`，返回 `OcrResult`；
- Agent 工具 `ocr_image`：参数 `path`（工作区内）或 `media_id`、`lang`；READ 级、`requires_tool_context=True`；
- 安全：只接受 data URL / 工作区路径；单图上限 10MB；路径越界拒绝。

## 7. 前端

- `ChatInput` 启动时探测 OCR 能力；无视觉模型且 OCR 可用时不再禁用图片上传；
- `ImageOcrPreview`：输入区展示每张图片的 OCR 文本，支持复制、编辑、重新识别；
- 编辑后的文本经 `image_ocr_texts` 随 `POST /api/v1/chat/stream` 发送；
- 设置页「本地 OCR」卡片：状态、引擎、语言、测试识别、优先策略；持久化 `ocr_config`。

## 8. 性能

在开发机（Python 3.10 + RapidOCR 3.x + ORT 1.19.2，PP-OCRv6 small）实测：

| 场景 | 参数 | 结果 |
|---|---|---|
| 900×240 中英混排 | 默认 | 首次约 2.3s（含加载），预热约 1.8s |
| 1920×1080 / 10 行文本 | 默认（2048/开分类） | 约 3.0–3.2s |
| 1920×1080 / 10 行文本 | 1280/关分类 | 安静环境约 1.2–2.0s；CPU 争用可达 2.5–4s |
| 1600×900 / 10 行文本（`scripts/ocr_benchmark.py`） | 1280/关分类，3 次 | 中位 **1272ms**，CER **1.59%** |
| 缓存命中 | — | 0ms（进程内） |

Office 扫描页使用 2048 + 方向分类以保真；聊天截图使用 1280 + 关分类以提速。

## 9. 测试与基准

- 单元/集成：`backend/tests/unit/services/test_ocr_service.py`、`test_agent_vision_ocr.py`、
  `test_ocr_image_tool.py`、`backend/tests/unit/api/test_ocr_routes.py`、
  `backend/tests/unit/api/test_wiki_vision_ocr.py`、`backend/tests/unit/office/test_ocr.py`；
- 前端：`ChatInput.ocrFallback.test.tsx`、`ImageOcrPreview.test.tsx`、`LocalOcrCard.test.tsx`；
- 可复现基准：`python scripts/ocr_benchmark.py`（需可选依赖；生成合成图并计算 CER/耗时）。

## 10. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 设置页显示不可用 | `rapidocr`/`onnxruntime`/`pytesseract` 未安装，或 tesseract 不在 PATH | 安装可选依赖；或用设置页「测试识别」验证 |
| 模型文件不齐 | 显式模型目录缺少 `det.onnx`/`rec.onnx` | 补全模型或删除目录改用 wheel 自带模型 |
| 识别结果为空 | 图片质量低/无文字 | 查看质量提示；重试或换视觉模型 |
| Win7 不可用 | ORT >=1.15 不支持 Win7 | 使用 Tesseract 4.1；RapidOCR 仅实验 |
| 结果很慢 | CPU 争用/大图 | 降低 `max_side`；关闭 `use_cls`；等待预热 |

## 11. 已知边界

- 不做表格结构/阅读顺序/公式还原（只输出文本行）；
- 手写体、旋转、竖排等效果取决于模型；失败时给出占位符与质量提示；
- 聊天图片不落盘；刷新后原图不可回看（现状如此）；
- Win7 的 RapidOCR 路径未经真机承诺。
