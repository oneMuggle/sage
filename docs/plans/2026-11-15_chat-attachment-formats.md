# 聊天附件格式扩展：PPTX 支持 + XLSX 注入修复 + 前后端口径收敛

- 日期：2026-11-15
- 分支：`feat/chat-attachment-formats`（基于 `origin/release/win7` 9f391daf1）
- 关联问题：会话输入框不支持 `.pptx`；`.xlsx` 可上传但发送时被跳过；文件选择器与拖放白名单不一致；图片通道前后端 MIME 口径不一致。

## 1. 背景与根因

### 1.1 PPTX 无法作为聊天附件

Sage 已具备 PPTX 解析能力：

- Office 工作台：`backend/office/ppt.py` 的 `read_ppt`，依赖 `python-pptx==0.6.23`（双分支均已安装）。
- `@` 引用：`backend/chat/attachment_resolver.py:384` 的 `OFFICE_EXTS` 含 `.pptx`。
- 知识库导入：`backend/wiki/file_parser.py:98` 支持 `.pptx`。

但聊天附件上传链路的白名单没有放行：

- 前端 `src/shared/lib/hooks/useFileUpload.ts:7` 的 `CHAT_DOCUMENT_EXTENSIONS` 只有 `pdf/docx/xlsx`。
- 后端 `backend/api/chat_attachment_routes.py:80` 的 `ALLOWED_DOC_EXTENSIONS = {"pdf", "docx", "xlsx"}`。
- 因此拖入/选择 `.pptx` 时前端预检直接判 `unsupported`，根本不会进入上传与解析。

### 1.2 XLSX 上传成功但发送时被跳过

`backend/api/legacy_routes.py:1591` 的发送侧注入循环只对 `pdf/docx` 调用二进制提取器：

```python
if _r37_ext in ("pdf", "docx"):
    r37_text = ... _extract_document_text(...)
else:
    r37_text = r37_bytes.decode("utf-8")
```

`.xlsx` 是 zip 二进制（`PK\x03\x04`），UTF-8 解码必然抛 `UnicodeDecodeError`，附件状态被标记为 `not_utf8`。上传接口与 `/chat/attachments/{id}/text` 都支持 xlsx，唯独发送侧分发表漏了它；上传接口测试覆盖不到这条路径，所以一直未被发现。

### 1.3 多处白名单漂移

- `src/widgets/chat/InputCard.tsx:683` 硬编码了一份较窄的 `accept` 列表（缺 rb/php/c/cpp/swift/kt/scss/vue/ps1 等）。
- `useFileUpload.ts` 中的 `CHAT_DOCUMENT_ACCEPT` 已定义但无人引用。
- 图片：前端选择器 `accept="image/*"`、预检接受任意 `image/*`，后端只接受 png/jpeg/webp/gif（`backend/api/chat_stream_support.py:83`），BMP/SVG/HEIC 会先通过前端、发送时才被后端拒绝。

## 2. 目标与范围

**目标（P0）**

1. `.pptx` 在聊天输入框可拖入、可选择、可上传、可解析并注入上下文。
2. `.xlsx` 在发送侧正确走 `openpyxl` 提取，不再出现 `not_utf8`。
3. 发送侧与上传侧共用同一套“扩展名 → 提取器”分发表，杜绝再次漂移。
4. 文件选择器 `accept` 由前端支持集派生；图片 MIME 与后端严格同口径。
5. Office 二进制文档解析前做解压预算检查（zip bomb 防护）。

**不在本次范围（后续 P1/P2）**

- 旧版 `.doc/.xls/.ppt` 的 LibreOffice 转换接入。
- 扫描版 PDF / 纯图片 PPT 的 OCR 与 MinerU 接入。
- 音频 ASR 通道、工作区文件选择器、限额提升。
- 统一 `DocumentExtractor` 注册表重构（本次先把聊天链路收敛）。

## 3. 涉及文件

| 文件 | 变更 |
| --- | --- |
| `backend/api/chat_attachment_routes.py` | `ALLOWED_DOC_EXTENSIONS` 增加 pptx；新增 `extract_attachment_text` 统一分发器；新增 `_extract_pptx_text`；新增 zip 解压预算守卫；`/text` 与索引端点复用同一提取集合 |
| `backend/api/legacy_routes.py` | 发送侧注入循环改为线程池调用 `extract_attachment_text`，删除 pdf/docx 特判 |
| `backend/services/multimodal/media_store.py` | `FALLBACK_DOCUMENT_SUFFIXES` 增加 `.pptx`；`load/delete` 校验 media_id，阻断 glob 注入 |
| `src/shared/lib/chatAttachmentFormats.ts`（新增） | 附件扩展名 / accept / 图片 MIME / 大小上限常量；独立于 hook，避免测试 mock 时丢失常量 |
| `src/shared/lib/hooks/useFileUpload.ts` | 从新模块导入并再导出常量；图片预检按 MIME 校验 |
| `src/widgets/chat/InputCard.tsx` | 文档/图片 `accept` 改用共享常量 |
| `src/pages/Chat.tsx` | `CHAT_DOC_MIME` 增加 pptx MIME |
| `backend/tests/unit/test_r39_pdf_docx_extract.py` | 增加 PPTX 上传/读取用例、统一分发器用例、zip 预算用例 |
| `backend/tests/unit/test_media_store.py` | 回退表用例增加 `.pptx` |
| `src/shared/lib/hooks/__tests__/useFileUpload.test.ts` | 增加 pptx 预检、图片 MIME 拒绝、accept 覆盖性用例 |
| `docs/user-manual/35-attachment-capability.md` | 支持格式与常见问题更新 |
| `docs/technical/131-attachment-pipeline.md` | 链路、白名单、发送侧分发器更新 |

## 4. 技术方案

### 4.1 后端统一“扩展名 → 文本”分发器

在 `chat_attachment_routes.py` 中新增纯函数，上传接口、`/text`、索引、发送侧注入全部走它：

```python
#: 与 ALLOWED_DOC_EXTENSIONS 同口径；新增格式只改这一处。
EXTRACTABLE_DOC_EXTENSIONS = frozenset({"pdf", "docx", "xlsx", "pptx"})
ALLOWED_DOC_EXTENSIONS = EXTRACTABLE_DOC_EXTENSIONS


def extract_attachment_text(content: bytes, ext: str) -> str:
    """按扩展名把附件字节转成可注入聊天的文本。

    二进制文档走对应解析器；其余按 UTF-8 文本解码。发送侧
    （legacy_routes）在线程池中调用本函数，避免再维护第二份分支。
    """
    normalized = ext.lstrip(".").lower()
    if normalized in EXTRACTABLE_DOC_EXTENSIONS:
        return _extract_document_text(content, normalized)
    return content.decode("utf-8")
```

`_extract_document_text` 内新增：

```python
if ext == "pptx":
    return _extract_pptx_text(content)
```

### 4.2 PPTX 文本提取

不新增依赖，直接使用已钉死的 `python-pptx`，按页输出标题、正文、表格单元格、备注：

```python
def _extract_pptx_text(content: bytes) -> str:
    import io

    from backend.core.lazy import load_attr

    Presentation = load_attr("pptx", "Presentation", globals())
    prs = Presentation(io.BytesIO(content))
    lines: List[str] = []
    for index, slide in enumerate(prs.slides, start=1):
        title = ""
        title_shape_id = None
        try:
            title_shape = slide.shapes.title
            if title_shape is not None and title_shape.has_text_frame:
                title_shape_id = id(title_shape)
                title = title_shape.text_frame.text.strip()
        except (AttributeError, KeyError):
            title = ""
        lines.append(f"[第{index}页]" + (f" {title}" if title else ""))
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                for para_index, para in enumerate(shape.text_frame.paragraphs):
                    if id(shape) == title_shape_id and para_index == 0 and title:
                        continue  # 标题已在页头输出
                    text = para.text.strip()
                    if text:
                        lines.append(text)
            elif getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        lines.append("\t".join(cells))
        try:
            notes_slide = slide.notes_slide
            notes = notes_slide.notes_text_frame.text.strip() if notes_slide is not None else ""
            if notes:
                lines.append(f"[备注] {notes}")
        except (AttributeError, KeyError, ValueError):
            pass
    return "\n".join(lines)
```

### 4.3 发送侧注入接线

`legacy_routes.py` 中原来的 if/else 替换为：

```python
r37_text = await _r66_car.extract_attachment_text_async(r37_bytes, _r37_ext)
# 内部 = asyncio.wait_for(run_in_executor(extract_attachment_text), 30s)
```

超时单独标记 `parse_timeout`（前端 i18n 已补）；其它 `UnicodeDecodeError`
（非 UTF-8 文本）与解析异常继续走既有 `skipped/error` 分支，前端附件卡片行为不变。

### 4.4 前后端白名单同口径

前端：

```ts
// src/shared/lib/chatAttachmentFormats.ts
export const CHAT_DOCUMENT_EXTENSIONS = new Set([
  // ...原有扩展名
  'pdf',
  'docx',
  'xlsx',
  'pptx',
]);

export const CHAT_DOCUMENT_ACCEPT = Array.from(CHAT_DOCUMENT_EXTENSIONS)
  .sort()
  .map((ext) => `.${ext}`)
  .join(',');
```

`useFileUpload.ts` 从该模块导入并再导出，保持既有 import 路径兼容；`InputCard.tsx`
改为 `accept={CHAT_DOCUMENT_ACCEPT}`，删除硬编码列表。`Chat.tsx` 的 `CHAT_DOC_MIME` 增加：

```ts
pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
```

后端 `MediaStore.FALLBACK_DOCUMENT_SUFFIXES` 增加 `.pptx`（sidecar 丢失时仍能判为 DOCUMENT，而不是 AUDIO）。

### 4.5 图片 MIME 口径

```ts
// src/shared/lib/chatAttachmentFormats.ts
/** 与后端 chat_stream_support._ALLOWED_IMAGE_MIME_PREFIXES 同口径。 */
export const CHAT_IMAGE_MIME_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
]);
export const CHAT_IMAGE_ACCEPT = Array.from(CHAT_IMAGE_MIME_TYPES).join(',');
```

`preflightAttachment` 图片分支由 `file.type.startsWith('image/')` 改为 `CHAT_IMAGE_MIME_TYPES.has(file.type)`；`InputCard` 图片输入改为 `accept={CHAT_IMAGE_ACCEPT}`。BMP/SVG/HEIC 在选中时直接红标“不支持的文件类型”，不再等到发送时被后端拒绝。

### 4.6 安全：Office zip 解压预算

`docx/xlsx/pptx` 都是 zip 容器。解析前先限制中央目录条目数（≤10,000），
再逐条校验 `file_size` 非负且不超过预算，最后校验解压后总量（≤100MB）：

```python
MAX_OFFICE_ZIP_MEMBERS = 10_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def _guard_office_zip_budget(content: bytes) -> None:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > MAX_OFFICE_ZIP_MEMBERS:
            raise ValueError(...)
        total = 0
        for info in members:
            size = info.file_size
            if size < 0 or size > MAX_OFFICE_UNCOMPRESSED_BYTES:
                raise ValueError(...)
            total += size
            if total > MAX_OFFICE_UNCOMPRESSED_BYTES:
                raise ValueError(...)
```

上传、`/text`、索引与发送侧解析均在线程池执行，并用 `asyncio.wait_for`
设 30s 墙钟上限；解析异常只回传通用文案，细节仅以 `error_type` 记日志。

## 5. 实施步骤

### Task 1：后端统一分发器 + PPTX 提取（TDD）

- [x] 1.1 在 `backend/tests/unit/test_r39_pdf_docx_extract.py` 增加 `_make_pptx_bytes` 与 `TestPptxExtraction`（上传接口 + `/text` 往返）。
- [x] 1.2 增加 `TestExtractDispatcher`：`extract_attachment_text(xlsx_bytes, "xlsx")` 含单元格文本；`(pptx_bytes, "pptx")` 含幻灯片正文；`(b"hello", "txt")` 返回原文。
- [x] 1.3 增加 zip 预算用例：`monkeypatch.setattr(chat_attachment_routes, "MAX_OFFICE_UNCOMPRESSED_BYTES", 1)` 后调用 `_guard_office_zip_budget` 抛 `ValueError`。
- [x] 1.4 运行定向测试，确认新用例失败。
- [x] 1.5 实现 `EXTRACTABLE_DOC_EXTENSIONS`、`extract_attachment_text`、`_extract_pptx_text`、`_guard_office_zip_budget`，并让 `/text`、索引端点使用统一集合。
- [x] 1.6 重跑定向测试，全部通过。

### Task 2：后端发送侧与回退表

- [x] 2.1 `backend/tests/unit/test_media_store.py` 的 `cases` 增加 `"abc129.pptx": MediaKind.DOCUMENT`；先运行确认失败。
- [x] 2.2 `media_store.py` 的 `FALLBACK_DOCUMENT_SUFFIXES` 增加 `.pptx`。
- [x] 2.3 `legacy_routes.py` 注入循环改为调用 `_r66_car.extract_attachment_text`，更新注释。
- [x] 2.4 重跑 media store 测试与附件提取测试。

### Task 3：前端白名单与图片口径（TDD）

- [x] 3.1 `useFileUpload.test.ts` 增加：`pptx` 在文档支持集；`preflightAttachment(pptx)` 通过；`bmp` 图片被拒；`CHAT_DOCUMENT_ACCEPT` 覆盖全部支持扩展名。
- [x] 3.2 运行 vitest，确认新用例失败。
- [x] 3.3 `useFileUpload.ts` 增加 pptx、派生 `CHAT_DOCUMENT_ACCEPT`、新增 `CHAT_IMAGE_MIME_TYPES/CHAT_IMAGE_ACCEPT`、图片预检按 MIME。
- [x] 3.4 `InputCard.tsx` 使用两个共享 accept 常量。
- [x] 3.5 `Chat.tsx` 增加 pptx MIME。
- [x] 3.6 重跑 vitest，全部通过。

### Task 4：文档同步

- [x] 4.1 `docs/user-manual/35-attachment-capability.md`：支持格式加入 PowerPoint（.pptx），图片格式限定 png/jpeg/webp/gif，补充“旧版 .ppt 需转存为 .pptx”的说明。
- [x] 4.2 `docs/technical/131-attachment-pipeline.md`：更新白名单、统一分发器、发送侧路径与 pptx 提取说明。
- [x] 4.3 更新本文档实施步骤勾选状态。

### Task 5：全量验证

- [x] 5.1 后端：`ruff check backend/`（py38 环境，ruff 0.4.4）。
- [x] 5.2 后端：`python scripts/check_py38_compat.py`（若脚本参数以 CI 为准）。
- [x] 5.3 后端定向 pytest：`test_r39_pdf_docx_extract.py`、`test_media_store.py`、`test_chat_attachment_text.py`。
- [x] 5.4 前端：`vitest run src/shared/lib/hooks/__tests__/useFileUpload.test.ts` 及相关聊天输入测试。
- [x] 5.5 前端：`tsc --noEmit`、`eslint` 改动文件、`node scripts/architecture-check.mjs`。
- [ ] 5.6 手工冒烟（若环境允许）：上传 `.pptx` → 发送 → 气泡卡片显示“已读取”；上传 `.xlsx` → 不再显示 `not_utf8`。

### Task 6：安全评审加固（实施中补充）

- [x] 6.1 Office zip 预算守卫按 wiki 加固版补齐：成员数上限 10,000、拒绝负 size、单成员与聚合均限制 100MB。
- [x] 6.2 上传 / `/text` / 索引端点的解析移入线程池，并加 30s `asyncio.wait_for` 上限，避免阻塞事件循环。
- [x] 6.3 PPTX 备注读取先判断 `has_notes_slide`，避免对无备注 deck 逐页新建 notes part。
- [x] 6.4 `MediaStore.load/delete` 校验 media_id 字符集，阻断 `*` / `../*` 等 glob 注入（防止任意附件读取/删除）。
- [x] 6.5 上传扩展名限定 `[a-z0-9]{1,16}`；解析异常不再把第三方库原文回传客户端。
- [x] 6.6 补测试：zip 成员数/单成员超限、media_id glob 注入。
- [x] 6.7 发送侧改用 `extract_attachment_text_async`（线程池 + 30s 上限），超时原因 `parse_timeout`；补异步包装器与 `legacy_routes` 源码契约测试，防止回退到 UTF-8 解码分支。

## 6. 验收标准

1. `.pptx` 通过拖放/选择/粘贴三入口均可加入附件条，发送后附件卡片状态为“已读取”，字符数 > 0。
2. `.xlsx` 发送后附件卡片状态为“已读取”，不再出现 `not_utf8`。
3. 文件选择器展示的扩展名与拖放白名单一致（由同一常量派生）。
4. BMP/SVG/HEIC 图片在选中阶段即显示“不支持的文件类型”，不会进入发送。
5. 后端定向测试、前端定向测试、tsc、eslint、architecture-check 全部通过。

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| `python-pptx` 在 py38 分支为 0.6.23，API 与新版有差异 | 只使用 `Presentation` / `slides` / `shapes` / `text_frame` / `table` / `notes_slide` 这些稳定 API；在 py38 环境跑定向测试 |
| 复杂 PPTX（纯图片、嵌入对象）提取为空 | 状态显示 `empty_text`，文档中提示转存或使用 OCR（P1 再接） |
| zip 解压预算误伤大文件 | 上限设为 100MB（压缩上限 25MB），仅统计中央目录声明大小，不实际解压 |
| 图片 MIME 收紧影响 SVG/BMP 用户 | 属于前后端口径对齐；P1 再做 canvas 自动转 JPEG |
| 发送侧改走线程池带来的性能变化 | 文本解码开销极小；原本 pdf/docx 已在线程池，xlsx/pptx 也本应如此 |

## 8. 后续（不在本次）

- P1：LibreOffice 旧格式转换、GBK 编码回退、扫描件 OCR、工作区文件选择器、限额配置化。
- P2：统一 `DocumentExtractor` 注册表，覆盖聊天附件 / `@` 引用 / 知识库导入 / Office 工作台。
