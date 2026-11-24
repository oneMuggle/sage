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
- 二进制文档 `.pdf .docx .xlsx .pptx`

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
| `extract_failed:<ExcType>` | pdf/docx/xlsx/pptx 解析抛错 |
| `empty_text` | 提取结果为空 |
| `context_build_failed` | 上下文构建返回 None |

#### 发送侧与上传侧共用同一分发表（2026-11-15）

`chat_attachment_routes.extract_attachment_text(content, ext)` 现在是唯一的
“扩展名 → 文本”入口：`pdf/docx/xlsx/pptx` 走对应二进制解析器，其余按 UTF-8 解码。
`/chat/attachments` 上传接口、`/chat/attachments/{id}/text`、附件索引与
`legacy_routes` 发送侧注入循环全部调用它；发送侧使用
`extract_attachment_text_async`（线程池 + 30s `wait_for`），超时状态为
`parse_timeout`。

历史回归：发送侧曾只对 `pdf/docx` 调提取器，`xlsx` 落入 `bytes.decode("utf-8")`
分支 → `UnicodeDecodeError` → 附件状态 `not_utf8`。本次修复后上传白名单
`ALLOWED_DOC_EXTENSIONS` 与提取集合 `EXTRACTABLE_DOC_EXTENSIONS` 共用同一
`frozenset`，新增格式只改一处。

PPTX 提取按页输出：`[第N页] 标题`、正文段落、表格单元格（制表符分隔）与
`[备注]`；纯图片幻灯片没有文字层时返回空文本，前端显示 `empty_text`。

解析安全边界：docx/xlsx/pptx 解析前检查 zip 中央目录（成员数 ≤10,000、
单成员与解压后总量均 ≤100MB，且拒绝负 size），上传/读取端点的解析在线程池
执行并设 30s 墙钟上限；解析异常只回传通用文案，细节仅以 `error_type`
记录到服务端日志。

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

### 7.1 共享 hook（2026-11-15 起为唯一入口）

`src/shared/lib/hooks/useGlobalFileDrop.ts`，Chat 页与新对话页（Welcome）共用：

- 在 **document 捕获阶段**监听 `dragenter` / `dragleave` / `dragover` / `drop`，
  任何含文件的 drop 一律 `preventDefault()` 后派发 `sage:composer-drop`
  CustomEvent，composer（`ChatInput` / `WelcomeInputCard`）消费后交给各自的
  `useFileUpload` —— **不再区分 composer 内/外**，也不再有第二套 composer
  局部拖放状态；
- `isDragOver` 驱动整页遮罩（`pointer-events-none`，永不阻断输入）；
- 复位路径：`drop` / `dragend` / 拖出窗口（`dragleave` 且 `relatedTarget` 为
  `null`）一律清零。

### 7.2 两个容易踩的点

- **Electron 21 / Chromium 106 的 `DataTransfer.types` 是 `DOMStringList`**，没有
  `Array.from` 之外的 iterable 协议，统一 `Array.from(e.dataTransfer?.types ?? [])` 后判断；
- 遮罩用 `fixed` 而非 `absolute` —— Welcome 页根容器是 `overflow-y-auto`，`absolute`
  遮罩会随内容滚走。

### 7.3 拖拽计数去抖

`dragenter` / `dragleave` 在嵌套元素间成对冒泡，用计数器抵消子元素带来的误增误减，
避免遮罩闪烁。会话标志（dragenter 时置位）取代"每次现查 `dataTransfer.types`"——
部分 Chromium 版本在 dragleave 时 `dataTransfer` 不可靠，现查会漏减计数。

### 7.4 拖放遮罩卡死回归（2026-11-15）

旧实现按 `composerSelector` 分流：卡外 drop 被捕获阶段 `stopPropagation` 拦截，
卡内依赖 `InputCard` 自己的 React `onDrop` 复位局部 `isDragOver`。但卡内覆盖层
（`absolute inset-0 z-10`）本身不在 textarea 内，drop 目标落在覆盖层时会被判为
"卡外" → 全局拦截 + `stopPropagation` → 局部状态无人复位 → 遮罩永久停留且
（覆盖层无 `pointer-events-none`）阻断输入。

修复：删除 composer 局部拖放状态与遮罩（单一入口 + 单一状态），补 `dragend` /
离开窗口复位；回归测试见 `ChatInput.globalDrop.test.tsx`。

## 8. 音频附件暂时隐藏

`ChatInput` / `InputCard` 中的音频上传入口与 chip 暂时隐藏，避免"显示了但没发"。
后续接入 ASR 通道时再放回。

## 9. 测试

| 层次 | 文件 | 覆盖 |
| --- | --- | --- |
| 后端单测 | `backend/tests/unit/test_media_store.py` | sidecar 读写往返、扩展名参数化（含 .pptx）、删除清理 |
| 后端单测 | `backend/tests/unit/test_r39_pdf_docx_extract.py` | pdf/docx/xlsx/pptx 上传与读取、统一分发表、zip 解压预算 |
| 后端单测 | `backend/tests/unit/test_chat_attachment_text.py` | 真实 MediaStore 上传 → 读取链路（csv/py/json/ts/html/sql） |
| 后端单测 | `backend/tests/unit/test_chat_attachment_errors.py` | 上传错误码状态码 / GBK+GB18030 上传与回读 / 无点白名单 / 孤儿计数（见 §11.6） |
| 主进程单测 | `electron/__tests__/mediaIpc.test.ts` | 上传失败时 reject 抛后端真实文案（见 §11.6） |
| 前端单测 | `src/features/send-message/__tests__/attachmentsProcessed.test.ts` | `attachments_processed` 事件消费 |
| 前端单测 | `src/widgets/chat/__tests__/Message.clientMeta.test.tsx` | 气泡状态 chip 渲染 |
| 前端单测 | `src/shared/lib/hooks/__tests__/useFileUpload.test.ts` | 预检各分支 + 状态流转 |
| 前端单测 | `src/shared/lib/hooks/__tests__/useGlobalFileDrop.test.ts` | 拖放唯一入口（含 composer 内）/ preventDefault / drop·dragend·离开窗口复位 / 文本拖放忽略 / 卸载清理 |
| 前端单测 | `src/widgets/chat/__tests__/ChatInput.globalDrop.test.tsx` | 遮罩随 drop/取消消失、drop 落覆盖层与 textarea 均入列、指针穿透 |
| 前端单测 | `src/widgets/chat/__tests__/ChatInput.composerDrop.test.tsx` | composer 消费 `sage:composer-drop` 的图片/文档分流 |

## 10. Win7 适配说明

- `json` / `pathlib` 均为 stdlib，Python 3.8 可用；
- 类型注解用 `Optional[dict]` 而非 `dict | None` —— 3.8 不支持 PEP 604 联合类型语法；
- `datetime.now(timezone.utc)` 保留 `# noqa: UP017`（`UTC` 常量是 3.11+）。

## 11. 上传错误透传与编码兼容（2026-11-24）

### 11.1 三层错误丢失链

上传失败时用户曾只看到 **"上传响应缺少 media_ref.id"** —— 面板开发者视角的技术黑话，
真实原因（编码不支持 / 类型不支持 / 解析失败）在三层各自被丢弃：

| 层 | 原行为 | 修复后 |
| --- | --- | --- |
| 后端 `upload_chat_attachment` | 所有失败分支都用 **HTTP 200** 承载 `{"error": ...}` | 用 `JSONResponse(status_code=4xx/5xx, {"error_code", "error"})` |
| 主进程 `electron/mediaIpc.ts` | 只看 `!resp.ok`，200 即视为成功，`{error}` 原样回传 | 无论状态码都先解析 JSON；`json.error` 为字符串即抛 `Error(json.error)` |
| 前端 `useFileUpload.startEagerUpload` | 拿不到 `media_ref.id` 就抛固定文案，**丢弃后端 `error`** | catch 里用 `err.message` 作为 `reason`；`media_ref.id` 缺失仅作最后兜底 |

主进程保留**向后兼容分支**：后端若仍返回 HTTP 200 + `{error}`，同样判定为失败并抛真实文案。

### 11.2 错误码与 HTTP 状态码映射

```python
class AttachmentErrorCode(str, Enum):
    UNSUPPORTED_TYPE = "unsupported_type"          # 类型/扩展名不在白名单
    UNSUPPORTED_ENCODING = "unsupported_encoding"  # 文本编码无法解码
    TOO_LARGE = "too_large"                        # > 25MB
    PARSE_FAILED = "parse_failed"                  # PDF/DOCX 解析抛异常
    PARSE_TIMEOUT = "parse_timeout"                # 解析超时
```

| 错误码 | HTTP | 典型触发 |
| --- | --- | --- |
| `unsupported_type` | 415 | `.exe` / 无点 `LICENSE` |
| `too_large` | 413 | > 25 MB |
| `unsupported_encoding` | 422 | 三种编码都解不出 |
| `parse_failed` | 422 | 损坏 PDF / 格式不符 |
| `parse_timeout` | 504 | 解析超 30s 墙钟 |

错误响应体统一为 `{"error_code": "...", "error": "可读中文文案"}`；
`error` 是面向用户的中文，解析器异常细节只以 `error_type` 记进服务端日志，不外泄。

路由声明 `response_model=None` —— 返回体是 `dict | JSONResponse` 联合类型时，
FastAPI 需要显式跳过响应模型推导，否则 `JSONResponse` 会被序列化校验拦下。

### 11.3 编码回退链（UTF-8 → GBK → GB18030）

Windows 中文环境保存的 txt 常见 GBK 编码，旧实现用严格 `content.decode("utf-8")`，
GBK 文件要么上传失败、要么上传成功却读不回全文。

解码口径统一收敛到 `backend/services/attachment_extract.py` 的 `decode_text_content()`，
**上传侧（校验）、回读侧（取全文）、发送侧（注入上下文）三处共用**：

```python
TEXT_DECODE_FALLBACKS = ("utf-8", "gbk", "gb18030")

def decode_text_content(content: bytes) -> Optional[str]:
    for encoding in TEXT_DECODE_FALLBACKS:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None
```

三种编码都失败才报 `unsupported_encoding`（422）。`extract_attachment_text()`
在全部失败时抛 `UnicodeDecodeError`，保持发送侧 `not_utf8` 状态契约不变。

> **口径分裂是实测抓到的**：M6 集成验证时发现 GBK 文件上传返回 200，但
> `GET /chat/attachments/{id}/text` 返回 `{"error": "附件不是有效的 UTF-8 文本"}`
> —— 上传侧已用回退链、回读侧仍是严格 UTF-8。修复前先写了两条 RED 测试
> （`test_gbk_txt_text_roundtrip_after_upload` / `test_shared_extractor_decodes_gbk_text`），
> 再把回退链下沉到共享提取器。

不引入 `charset-normalizer` 等新依赖；GBK / GB18030 覆盖中文 Windows 绝大部分场景。

### 11.4 无点文件名白名单

前端 `name.split('.').pop()` 对无点文件得到整个名字，后端 `"." in filename` 得到空扩展名
—— 两端口径漂移，`Makefile` 因此被拒。

后端 `backend/api/chat_attachment_routes.py`：

```python
#: 无扩展名但允许上传的文件名（小写精确匹配）。
#: 前端 CHAT_NO_EXT_FILENAMES 必须与本常量同口径。
NO_EXT_FILENAMES: FrozenSet[str] = frozenset({"makefile", "dockerfile"})
```

无点文件命中白名单时，用文件名本身当**伪扩展名**参与后续判定，
最终落盘扩展名也是 `.makefile` / `.dockerfile`。

前端 `src/shared/lib/chatAttachmentFormats.ts`：

```typescript
export const CHAT_NO_EXT_FILENAMES = new Set(['makefile', 'dockerfile']);
```

`preflightAttachment` 显式分流：有点文件按扩展名匹配，无点文件查无点白名单；
两者都不命中才报 `unsupported`。

### 11.5 孤儿文件治理

旧实现 `store.save()` 先于编码校验执行 —— GBK txt 校验失败后磁盘已落
`.txt` + `.meta.json` 两个文件，而前端拿不到 id，这些文件成了永远无人回收的孤儿。

修复：**全部校验前移，`store.save()` 放在最后一步**。

```
1. 解析文件名与扩展名（含无点白名单）
2. 校验扩展名 + content-type → 415
3. 读内容 + 校验大小 → 413
4. 文本：解码（UTF-8→GBK→GB18030）失败 → 422
   文档：解析（线程池 + 30s 墙钟）失败/超时 → 422 / 504
5. 全部通过 → store.save()
6. _schedule_mineru_enrichment（依赖已存盘，故放在 save 之后）
```

M6 实测：7 个文件上传（5 成功 + 2 失败），磁盘文件数 `before=12 → after=22`，
增量恰好 `+10 = 5 × (内容 + meta)` —— **失败路径落盘 0 个文件**。

### 11.6 测试矩阵

| 层次 | 文件 | 覆盖 |
| --- | --- | --- |
| 后端单测 | `backend/tests/unit/test_chat_attachment_errors.py` | 各错误码状态码 / GBK+GB18030 上传与回读 / 无点白名单 / 孤儿计数 / 损坏 PDF |
| 后端单测 | `backend/tests/unit/test_chat_attachment_text.py` | 旧 HTTP 200 断言同步到新状态码契约（422 / 415 + `error_code`） |
| 主进程单测 | `electron/__tests__/mediaIpc.test.ts` | 后端返回 4xx + `{error, error_code}` 时 reject 抛真实文案；200 + `{error}` 的兼容分支 |

## 12. 未完成项（后续 PR）

| 项 | 内容 |
| --- | --- |
| PDF 视觉通道 | 已完成「页标记文本 + 图表抽取 + 内联引用」（见 §156）；剩余：视觉模型逐页读图与命中页低 DPI 复核 |
| 上下文计量 | `ContextMeter` 显示附件占 token，超 100k 截断时给 inline 提示 |
| 编排 / 插话路径 | planner 提示词注入附件概要；插话请求支持 `attachment_media_ids` 或明确告知不含附件 |
