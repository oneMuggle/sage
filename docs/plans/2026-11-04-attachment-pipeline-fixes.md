# 聊天附件链路修复（P0 读不到 + P1 状态不可见 + P2 能力对齐）

> 分支：`feat/attachment-pipeline`（基线：`main`）
> 起始日期：2026-11-04
> 状态：进行中
> 关联分析：当前会话附件链路调查（R1–R7 根因）

## 背景与目标

用户反馈：在新会话页 / 会话页拖入文件后，UI 能看到文件名+大小的 chip，但发送后：
1. 没有明确 UI 提示附件是否被读取；
2. 模型回复看不出读过文件。

根因定位：

- **R1（P0）** `backend/services/multimodal/media_store.py` 的 `load()` 按后缀推断类型，
  白名单只有 `png/jpg/jpeg/webp / pdf/docx/xlsx/txt/md`，其余（py/ts/csv/json/yaml/
  html/sql/log…）全部被判定成 `AUDIO`，被 `legacy_routes.py:1436` 静默跳过。
  回归来源：`0fb10c4bb`（#2001）扩展白名单到约 50 种格式但只补了 `.xlsx`。
- **R2（P1）** `MediaStore` 不持久化 `original_filename` / `source` / `created_at`，
  `load()` 返回 `metadata={}`，导致注入给 LLM 的 `<attached_document>` 只有 id 没有文件名。
- **R3（P1）** 全链路 `continue` + debug log，前端没有任何 per-file 状态。
  新会话页对不支持类型也没有提示，会静默丢失。
- **R4（P1）** `ChatInput` 收集的 `audioAttachments` 没进发送参数。
- **R5（P2）** 25MB / 10 个 / 100k 字符上限静默；大文件发送时才上传。
- **R6（P2）** 插话/编排路径未携带附件；PDF 没有视觉通道，扫描 PDF 依赖手动 OCR。
- **R7（P2）** 消息气泡附件 chip 只显示名称，没有大小/状态。

目标：

1. 让所有支持的附件类型都能被 LLM 读到，且带文件名；
2. 让用户在任何失败节点都能看到明确的 per-file 状态，可重试/移除；
3. 把附件容量纳入上下文水位，与主流 AI 应用对齐。

## 涉及的文件与模块

### 后端
- `backend/services/multimodal/media_store.py` — 加 sidecar 元数据；扩 `load()` 后缀白名单。
- `backend/api/chat_attachment_routes.py` — `/chat/attachments` 写入元数据 sidecar；
  `get_chat_attachment_text` 与索引路由兼容 sidecar。
- `backend/api/legacy_routes.py` — R37 注入段：`continue` 前推事件；注入块带 filename/type；
  失败原因随 `attachments_processed` 事件发往前端。
- `backend/api/legacy_models.py` — 不需要改，`attachment_media_ids` 已存在。
- `backend/chat/context_sources.py` — `attached_document` 块加 `name`/`type` 属性。
- `backend/tests/unit/test_media_store.py`、`test_chat_attachment_text.py`
  以及新增 `test_chat_attachment_injection.py`：参数化覆盖所有扩展名。

### 前端
- `src/widgets/chat/InputCard.tsx` / `ChatInput.tsx` — composer chip 加状态色；
  Welcome 页补不支持提示；音频附件字段补齐或显式隐藏。
- `src/widgets/chat/MessageClientMeta.tsx` — 附件 chip 加大小、状态、展开明细。
- `src/pages/Chat.tsx` — 接收后端 `attachments_processed` 事件；持久化到 `client_meta.attachment_status`。
- `src/features/send-message/attachmentStatus.ts`（新增）— 前端状态类型与工具。
- `src/shared/api/attachmentAutoIndex.ts` — 失败时提示。
- 国际化：`src/shared/lib/i18n/locales/zh|en/...` 新增键。

### 测试
- 后端：`save → load` 参数化覆盖 `ALLOWED_TEXT_EXTENSIONS`；注入段 e2e 级断言。
- 前端：`MessageClientMeta` 状态 chip 渲染；`Chat` 接收 `attachments_processed`。

## 技术方案

### Phase 0：读得到（决定性修复）

1. **MediaStore 持久化 sidecar 元数据**
   - `save()` 在同目录写 `<id>.meta.json`：`{kind, mime_type, original_filename, source, metadata, created_at}`。
   - `load()` 优先读 sidecar，缺失时回退后缀推断；**回退表改用完整的文档后缀集合**
     （与 `ALLOWED_TEXT_EXTENSIONS | ALLOWED_DOC_EXTENSIONS` 同口径）。
   - 历史已存在的媒体文件无 sidecar：走回退分支（不会崩溃）。
   - 不引入新依赖，纯 stdlib `json`。

2. **注入块带文件名**
   - `legacy_routes.py` 的 R37 段把 `original_filename`（来自 sidecar）塞进
     `<attached_document id="..." name="..." type="...">`。
   - 取不到文件名时退化为 media id（向后兼容）。

3. **`attachments_processed` 流事件**
   - 注入段每个 media id 处理后记录 `{media_id, filename, status: 'ok'|'skipped'|'error', chars, reason?}`。
   - 不论成功失败都推到 `entry.queue`，前端据此渲染。
   - 同时把整段结果写入本轮第一条 assistant 行的 `rag_citations` 同级列（如 `attachments_status`），让 `get_messages` 回读后状态仍在。

4. **音频附件要么接 ASR，要么隐藏**
   - 短期方案（本 PR）：在 composer 隐藏音频上传按钮与 chip（注释/feature flag），
     避免"显示了但没发"。
   - 后续 PR 单独做 ASR 通道时再加回。

5. **测试**
   - `test_media_store.py` 新增：参数化遍历全部 `ALLOWED_TEXT_EXTENSIONS` 断言
     `save → load` 的 `kind == DOCUMENT`。
   - `test_chat_attachment_text.py` 新增：对 csv/py/json 等扩展名断言 `get_chat_attachment_text` 200 返回 text。
   - `test_chat_attachment_injection.py`（新增）：mock 一个 chat stream 请求，
     验证 `<attached_document name="x.py">` 出现在 `build_request_messages_from_events` 的
     `trailing_system` 里。

### Phase 1：状态可见

1. **Composer per-file 状态**
   - `useFileUpload` 给每个附件加 `status: 'reading'|'ready'|'uploading'|'uploaded'|'parsing'|'parsed'|'failed'` 与 `reason?`。
   - 改为"选中即上传"：`addFile`/`addImage` 触发时调 `window.electronAPI.media.uploadAttachment`；
     失败时 status='failed'，允许重试/移除。
   - chip 加状态色（绿/黄/红）+ 进度条（上传中）。

2. **发送门控**
   - 有失败/解析中附件时，发送按钮文案变为"有 x 个文件失败"，
     点击展开内联提示"移除 / 仍然发送"，永不静默丢弃。

3. **Welcome 页统一提示**
   - 与 ChatInput 一样，对不支持的扩展名给 `attachment_not_sent` toast；
     上传循环不再静默 `continue`。

4. **消息气泡附件卡片**
   - `MessageClientMeta` 渲染：名称、大小、类型图标、状态徽标（"已读取 / 已截断 / 解析失败"）。
   - 可展开明细（每个附件字符数 / 注入模式 full/truncated/rag / 失败原因）。
   - 后端把状态写入 `message_meta.attachments_status`（与 `attachments` 同名数组一一对应），
     `client_meta` 回读即可渲染。

5. **国际化**
   - 新增 `chat.attachment.status.uploading|uploaded|parsing|parsed|truncated|failed`；
   - 新增 `chat.attachment.summary` = "已读取 {count} 个文件 · 共 {chars} 字符"。

### Phase 2：能力对齐

1. **PDF 视觉通道**：视觉模型下，把 PDF 每页渲染成图片（上限 50 页）
   与文本提取并行发给 LLM；扫描件自动走本地 OCR。
2. **上下文计量**：`ContextMeter` 显示附件占 token，超 100k 截断时给 inline 提示。
3. **预检**：前端发送前校验 25MB / 10 个 / 重复文件名；失败 chip 直接标红。
4. **拖放/粘贴范围**：拖放监听提到聊天页根容器；粘贴支持非图片文件（按 mime 分流）。
5. **编排路径**：planner 提示词里注入"本轮附带 N 个文件，概要：..."；
   子代理任务提示携带摘要。
6. **插话（steering）**：steering 请求支持 `attachment_media_ids`，或者明确告知用户
   "附件仅随新 run 发送，本次插话不含附件"。

## 实施步骤

### Phase 0（P0）—— 本 PR 必达

- [x] 0.1 `MediaStore` 加 `save()` 写 sidecar `.meta.json`，`load()` 优先读 sidecar，回退用完整后缀表。
- [x] 0.2 `legacy_routes.py` R37 段注入块加 `name`/`type` 属性；推 `attachments_processed` 事件；
       把整体 status 列表写入 user 行 `client_meta.attachments_status`（随消息落库，刷新可回读）。
- [x] 0.3 `chat_attachment_routes.py` 上传端点保留，sidecar 写入由 `MediaStore.save()` 完成；
       索引/文本读取兼容无 sidecar 的历史数据。
- [x] 0.4 暂时隐藏音频上传入口（Composer + InputCard），避免"显示了没发"。
- [x] 0.5 后端测试：参数化扩展名、真实 MediaStore 上传→读取链路、sidecar 读写往返、删除清理。
- [x] 0.6 前端测试：`attachments_processed` 事件消费；消息气泡状态 chip 渲染。

### Phase 1（P1）—— 本 PR 内完成

- [x] 1.1 `useFileUpload` 加 per-file status；改为选中即上传（无 electronAPI 时回退发送时上传）。
- [x] 1.2 composer chip 状态色与进度（uploading/uploaded/failed）；失败可移除。
- [x] 1.3 发送门控：预上传失败文件提示"发送时将重试"（不静默）。
- [x] 1.4 Welcome 页补不支持扩展名的提示，与 ChatInput 一致。
- [x] 1.5 `MessageClientMeta` 附件卡片加大小/状态/展开明细；
       从 `client_meta.attachments_status` 读取。
- [x] 1.6 国际化键（拆分为 `locales/{zh,en}/attachmentStatus.ts` 以通过 800 行棘轮）。

### Phase 2（P2）—— 本 PR 内完成部分（2026-11-04 更新）

- [x] 2.3 前端预检：`useFileUpload` 加 `preflightAttachment()`，在 selection 阶段拒绝超过 25MB / 10 个 / 不支持扩展名 / 同名重复的附件，红标 chip 显示原因；粘贴扩展为同时接收图片与文档文件。
- [ ] 2.1 PDF 视觉通道（视觉模型）+ 扫描 PDF 自动 OCR。
- [ ] 2.2 上下文计量：`ContextMeter` 显示附件占 token，超 100k 截断时给 inline 提示。
- [x] 2.4 拖放范围扩大到页面根容器 —— 新增共享 hook `useGlobalFileDrop`（document capture 监听 +
       `sage:composer-drop` CustomEvent 分发），Chat 页与新对话页（Welcome）均接入，
       拖到页面任意位置都会显示遮罩并把文件交给对应 composer。
- [ ] 2.5 编排/插话路径的附件语义。

## 风险评估

1. **MediaStore sidecar 兼容**：历史媒体无 sidecar，必须走回退分支；回退表扩展了后缀，
   老图片/音频仍按后缀推断（行为一致）。
2. **新事件兼容性**：`attachments_processed` 是新事件，前端未订阅时忽略即可，
   `agentStateMapping.ts` 的 exhaustive check 需补 default case。
3. **client_meta 体积**：新增 `attachments_status` 后仍需遵守 32 KiB 上限；
   每个附件状态 < 200 字符，10 个附件 < 2 KiB，安全。
4. **py38 / win7**：`json`/`pathlib` 均 stdlib；win7 分支同步走 cherry-pick，
   不涉及 py38 兼容性变更。
5. **测试**：扩展名参数化会新增 ~50 个测试用例，预计不影响 CI 时长。

## 与项目其他规则的关系

- 双分支策略：本 PR 先合 main，再 cherry-pick 到 release/win7（附件链路两边都有）。
- 文档归档：完成后把方案并入 `docs/technical/` 新章节（编号顺延），
  并在 `docs/user-manual/` 新增"附件能力"段落。
- CI：`ci.yml` 与 `ci-win7.yml` 都会跑新增测试。
