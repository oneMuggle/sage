# 聊天附件链路（P0 读得到 + P1 状态可见 + P2 能力对齐）

> 归档日期：2026-11-04
> 关联 PR：#2855（main）
> 来源计划：`docs/plans/2026-11-04-attachment-pipeline-fixes.md`

## 1. 问题背景

用户在会话页 / 新对话页把文件拖进输入框后，UI 能看到文件名与大小，但：

1. 消息发出后，**文件内容没有进入 LLM 上下文** —— 模型回复里看不到读过文件；
2. **没有任何 UI 提示**附件是否被读取、是否失败；
3. 支持的格式只有极少数，**其余静默丢弃**。

根因定位（R1–R7）：

| 编号 | 根因 | 位置 |
| --- | --- | --- |
| R1 | `MediaStore.load()` 按后缀推断类型，白名单只有 `png/jpg/jpeg/webp/pdf/docx/xlsx/txt/md`，其余（py/ts/csv/json/yaml/html/sql/log…）全部落进 `AUDIO` 分支，被注入循环静默 `continue` | `backend/services/multimodal/media_store.py` |
| R2 | `MediaStore` 不持久化 `original_filename` / `source` / `created_at`，`load()` 返回 `metadata={}`，注入给 LLM 的 `<attached_document>` 只有 id 没有文件名 | `backend/services/multimodal/media_store.py` |
| R3 | 全链路 `continue` + debug log，前端没有任何 per-file 状态 | `backend/api/legacy_routes.py` |
| R4 | `ChatInput` 收集的 `audioAttachments` 没进发送参数 | 前端 composer |
| R5 | 25MB / 10 个 / 100k 字符上限静默；大文件到发送时才上传 | 前后端 |
| R6 | 插话 / 编排路径未携带附件；PDF 无视觉通道 | — |
| R7 | 消息气泡附件 chip 只显示名称，没有大小 / 状态 | `MessageClientMeta.tsx` |

R1 的回归来源是 `0fb10c4bb`（#2001）：该次把上传白名单扩展到约 50 种格式，
但只给 `load()` 的回退表补了 `.xlsx`，两张表从此口径不一致。

## 2. 架构总览

```
用户选文件 / 拖文件 / 粘贴
        │
        ├─ useFileUpload.preflightAttachment()      ← 选择阶段即校验（大小/扩展名/数量/重名）
        │     └─ 失败 → 红标 chip + 原因，不进列表
        │
        ├─ status: ready → uploading → uploaded      ← 选中即上传（Electron 环境）
        │     └─ 失败 → status='failed' + reason，可移除
        │
        ├─ 发送：attachment_media_ids 携带 media id
        │
        ▼
POST /chat/attachments → MediaStore.save()
        │                    ├─ 写 <id>.<ext>（媒体字节）
        │                    └─ 写 <id>.meta.json（sidecar 元数据）★ 新增
        ▼
chat_stream_create → R37 注入段
        ├─ load(media_id) → 优先读 sidecar，缺失时按完整后缀表回退 ★ 新增
        ├─ <attached_document id name type>正文</attached_document>  ★ 新增 name/type
        └─ 逐附件产出 status{ok|skipped|error, reason, chars, mode}
              │
              ├─ 流事件 attachments_processed ──→ 前端即时渲染气泡状态
              └─ 落库 client_meta.attachments_status ──→ 刷新后仍可回读
```

## 3. 后端：MediaStore sidecar 元数据

### 3.1 写入

`save()` 在写媒体字节的同时写一份同目录 sidecar `<id>.meta.json`：

```json
{
  "id": "abc123456789",
  "kind": "document",
  "mime_type": "text/x-python",
  "original_filename": "app.py",
  "source": "chat_upload",
  "metadata": {"original_filename": "app.py"},
  "created_at": "2026-11-04T12:34:56.789012+00:00"
}
```

- 纯 stdlib `json`，不引入新依赖；
- sidecar 写失败**只 log 不阻断**主流程（元数据丢失可回退后缀推断）；
- `metadata.original_filename` 规范化落盘，下游（RAG 引用溯源）直接取。

### 3.2 读取与回退

`load()` 优先读 sidecar 还原完整 `MediaRef`；sidecar 缺失（历史数据）时走**后缀推断回退分支**，
保证零迁移。

回退表 `FALLBACK_DOCUMENT_SUFFIXES` 与上传端 allowlist **同口径**：

- 基础文本 `.txt .md .csv`
- 编程语言 `.py .js .ts .jsx .tsx .java .go .rs .rb .php .c .cpp .h .hpp .cs .swift .kt .scala .r`
- 前端 `.html .css .scss .less .vue .svelte`
- 数据/配置 `.json .yaml .yml .xml .toml .ini .cfg .conf`
- 脚本/构建 `.sh .bash .bat .ps1 .sql .makefile .cmake .gradle`
- 特殊命名 `.dockerfile .gitignore .properties`
- 日志 `.log`
- 二进制文档 `.pdf .docx .xlsx`

图片后缀独立成表 `FALLBACK_IMAGE_SUFFIXES`（`.png .jpg .jpeg .webp .gif .bmp .svg`）；
两者都不命中时回退 `AUDIO`（与历史行为一致）。

### 3.3 附带修复

- `load()` 的 `rglob(f"{media_id}.*")` 现在**跳过 `.meta.json` 自身**，否则 sidecar 会被当成媒体文件读回；
- `delete()` 遍历完整个 `rglob` 结果再返回。旧实现 `for ...: unlink(); return True` 会在第一遍后退出，
  可能漏删另一个文件（sidecar 与媒体文件两个产物）。

## 4. 后端：注入段与可见状态

### 4.1 注入块带身份

`legacy_routes.py` 的 R37 注入段把 sidecar 里的文件名与 MIME 塞进注入块：

```
<attached_document id='abc123' name='app.py' type='text/x-python'>
...文件全文...
</attached_document>
```

取不到文件名时退化为 media id（向后兼容）。

### 4.2 逐附件状态

注入段对每个 media id 记录一条状态，**不论成功失败都产出**：

| 字段 | 说明 |
| --- | --- |
| `media_id` | 媒体 id |
| `filename` | 原始文件名（取不到则回退 media id） |
| `mime_type` | MIME |
| `status` | `ok` / `skipped` / `error` |
| `reason` | 失败或跳过原因（`ok` 时无此字段） |
| `chars` | 注入字符数（`ok` 时） |
| `mode` | `full` / `truncated` / `rag`（`ok` 时） |

失败原因取值：

| reason | 触发条件 |
| --- | --- |
| `load_failed` | 附件不存在或读取抛错 |
| `not_document(got=...)` | 类型不是 DOCUMENT（历史媒体被误判为 AUDIO 时可见） |
| `not_utf8` | 内容不是有效 UTF-8 |
| `extract_failed:<ExcType>` | pdf/docx/xlsx 解析抛错 |
| `empty_text` | 提取结果为空 |
| `context_build_failed` | 上下文构建返回 None |

### 4.3 状态的两个出口

1. **流事件 `attachments_processed`** —— 携带 `session_id` / `user_message_id` / `attachments[]`，
   前端收到后即时更新对应气泡；
2. **落库 `client_meta.attachments_status`** —— 写入 user 消息行的 `client_meta`，
   刷新会话后气泡状态仍在（事件只在流式期间可见，落库才是持久态）。

`client_meta` 序列化仍受 32 KiB 上限约束：每条状态 < 200 字符，10 个附件 < 2 KiB，安全。

### 4.4 事件类型契约

`attachments_processed` 是新增的流事件状态。`src/shared/lib/agentStateMapping.ts` 的
exhaustive check 补了对应分支（否则新增事件会被映射成 unknown 态）。

## 5. 前端：useFileUpload 状态机

### 5.1 per-file 状态

`AttachedFile` 新增字段：

```ts
interface AttachedFile {
  name: string;
  size: number;
  type: string;
  dataUrl?: string;
  mediaId?: string;                      // 选中即上传得到的 media id
  status?: 'reading' | 'ready' | 'uploading' | 'uploaded' | 'failed';
  reason?: string;                       // status='failed' 时的原因
  id?: string;                           // 内部标识，异步上传完成时精确定位条目
}
```

**选中即上传**：`addFile` / `addImage` 触发后立刻调 `window.electronAPI.media.uploadAttachment`，
状态流转 `ready → uploading → uploaded`；失败置 `failed` + reason，chip 显示红色并可移除。
无 `electronAPI` 时停留在 `ready`，由发送路径兜底上传（向后兼容）。

条目用 `crypto.randomUUID()` 生成的 `id` 定位，避免异步回调按文件名匹配（同名文件会串）。

### 5.2 预检（选择阶段即失败）

`preflightAttachment(file, existing, kind, totalCount)` 与后端口径一致：

| 限制 | 值 | reason |
| --- | --- | --- |
| 单文件大小 | 25 MB（`MAX_ATTACHMENT_SIZE`） | `oversize` |
| 附件数量 | 10（`MAX_ATTACHMENT_COUNT`） | `count_exceeded` |
| 扩展名白名单 | `CHAT_DOCUMENT_EXTENSIONS`（非图片） | `unsupported` |
| 同名重复 | — | `duplicate` |

预检失败**不静默**：条目以 `status='failed'` + reason 入列表，chip 显红并显示原因。

同名文件按主流应用行为**替换**旧条目（不是报错），因为替换是高频操作。

`preflightAttachment` 需要读取"当前"附件数，而 `setState` 是异步的 —— 用
`filesRef` / `imagesRef` 保存最新值供同步查询，避免闭包里的陈旧值。

### 5.3 粘贴扩展

粘贴处理器从"只接受图片"扩展为同时接受图片与文档文件，走同一条预检 + 状态机。

## 6. 前端：消息气泡附件卡片

`MessageClientMeta.tsx` 渲染附件卡片：

- 文件名 + 大小 + 类型图标；
- 状态徽标：**已读取 / 已跳过 / 读取失败 / 内容过长已截断 / 按相关度检索注入**；
- 可展开明细：每个附件的字符数、注入模式（full/truncated/rag）、失败原因；
- 汇总行：`已读取 N 个文件 · 共 M 字符`；
- 数据来源：`client_meta.attachments_status`（落库态，刷新后可回读）。

## 7. P2：整页拖放

### 7.1 共享 hook

新增 `src/shared/lib/hooks/useGlobalFileDrop.ts`，Chat 页与新对话页（Welcome）共用：

- 在 **document 捕获阶段**监听 `dragenter` / `dragleave` / `dragover` / `drop`，
  使"把文件拖到页面任意位置"都能被接收（对标 ChatGPT / Claude 的整页拖放）；
- 落在 `composerSelector` 内的 drop **不拦截**，交给 composer 自己的 React `onDrop`
  （保留输入卡原有高亮反馈）；
- 容器外的 drop 派发 `sage:composer-drop` CustomEvent，composer 消费后交给各自的
  `useFileUpload`，与输入卡内 drop 行为完全一致；
- `isDragOver` 驱动整页遮罩。

### 7.2 两个容易踩的点

- **Electron 21 / Chromium 106 的 `DataTransfer.types` 是 `DOMStringList`**，没有
  `Array.from` 之外的 iterable 协议，统一 `Array.from(e.dataTransfer?.types ?? [])` 后判断；
- 遮罩用 `fixed` 而非 `absolute` —— Welcome 页根容器是 `overflow-y-auto`，`absolute`
  遮罩会随内容滚走。

### 7.3 拖拽计数去抖

`dragenter` / `dragleave` 在嵌套元素间成对冒泡，用计数器抵消子元素带来的误增误减，
避免遮罩闪烁。

## 8. 音频附件暂时隐藏

`ChatInput` / `InputCard` 中的音频上传入口与 chip 暂时隐藏，避免"显示了但没发"。
后续接入 ASR 通道时再放回。

## 9. 测试

| 层次 | 文件 | 覆盖 |
| --- | --- | --- |
| 后端单测 | `backend/tests/unit/test_media_store.py` | sidecar 读写往返、扩展名参数化、删除清理 |
| 后端单测 | `backend/tests/unit/test_chat_attachment_text.py` | 真实 MediaStore 上传 → 读取链路（csv/py/json/ts/html/sql） |
| 前端单测 | `src/features/send-message/__tests__/attachmentsProcessed.test.ts` | `attachments_processed` 事件消费 |
| 前端单测 | `src/widgets/chat/__tests__/Message.clientMeta.test.tsx` | 气泡状态 chip 渲染 |
| 前端单测 | `src/shared/lib/hooks/__tests__/useFileUpload.test.ts` | 预检各分支 + 状态流转 |
| 前端单测 | `src/shared/lib/hooks/__tests__/useGlobalFileDrop.test.ts` | 整页拖放分发 / composer 内放行 / 遮罩状态 / 文本拖放忽略 / 卸载清理 |
| 前端单测 | `src/widgets/chat/__tests__/ChatInput.composerDrop.test.tsx` | composer 消费 `sage:composer-drop` 的图片/文档分流 |

## 10. Win7 适配说明

- `json` / `pathlib` 均为 stdlib，Python 3.8 可用；
- 类型注解用 `Optional[dict]` 而非 `dict | None` —— 3.8 不支持 PEP 604 联合类型语法；
- `datetime.now(timezone.utc)` 保留 `# noqa: UP017`（`UTC` 常量是 3.11+）。

## 11. 未完成项（后续 PR）

| 项 | 内容 |
| --- | --- |
| PDF 视觉通道 | 视觉模型下把 PDF 每页渲染成图片与文本提取并行发送；扫描件自动走本地 OCR |
| 上下文计量 | `ContextMeter` 显示附件占 token，超 100k 截断时给 inline 提示 |
| 编排 / 插话路径 | planner 提示词注入附件概要；插话请求支持 `attachment_media_ids` 或明确告知不含附件 |
