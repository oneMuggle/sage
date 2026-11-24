# 聊天附件上传错误透传 + 孤儿文件 + 编码兼容 + 口径统一

> **状态**: 进行中
> **日期**: 2026-11-24
> **分支**: `fix/attachment-error-surfacing`
> **相关代码**:
> - 前端 `src/shared/lib/hooks/useFileUpload.ts` (`startEagerUpload`, :139-168)
> - 主进程 `electron/mediaIpc.ts` (`registerMediaIpc`)
> - 后端 `backend/api/chat_attachment_routes.py` (`upload_chat_attachment`, :92-152)

## 背景

用户反馈最新安装包拖拽上传文件提示 **"上传响应缺少 media_ref.id"**，该错误是面板开发者视角的技术黑话，掩盖了真实的失败原因。

### 根因（三层错误丢失链）

1. **后端 `chat_attachment_routes.upload_chat_attachment`** 所有失败分支（扩展名非法/不支持类型/超限/编码错误/解析超时/解析失败）都用 **HTTP 200 承载业务错误** `return {"error": ...}`。
2. **主进程 `mediaIpc.ts`** 只按 `!resp.ok` 判定失败，200 即视为成功，把 `{"error"}` 原样回传给前端。
3. **前端 `useFileUpload.startEagerUpload`** 拿不到 `res.media_ref.id` 就抛固定文案 `'上传响应缺少 media_ref.id'`，**完全丢弃后端返回的真实 `error` 字段**。

### 实测证据（sage-backend 环境直调端点）

| 输入 | HTTP | 返回 |
|------|------|------|
| UTF-8 txt | 200 | `{"media_ref":{"id":"…"}}` ✓ |
| 真实 PDF/DOCX | 200 | `{"media_ref":{"id":"…"}}` ✓ |
| **GBK 编码 txt** | 200 | `{"error":"文本文件不是有效的 UTF-8 编码"}` + 落盘 2 文件（孤儿） |
| **无点文件名 Makefile** | 200 | `{"error":"不支持的文件类型: (无扩展名)"}` |
| 空 content-type 的 png 当文件 | 200 | `{"error":"不支持的文件类型: png"}` |
| 损坏 PDF | 200 | `{"error":"文档解析失败（格式损坏或内容过大）"}` |

### 附带缺陷

- **孤儿文件泄漏**：`store.save()` 在 `:118-125` 先于编码校验 `:130-134`。GBK txt 失败后磁盘已落 `.txt` + `.meta.json`，前端拿不到 id → 孤儿。
- **前后端扩展名口径漂移**：前端 `name.split('.').pop()`（无点文件得到整个名字）vs 后端 `"." in filename`（无点 → ext=""）。

## 目标

| # | 目标 | 验收标准 |
|---|------|----------|
| **A** | 错误可见性：真实错误透传到 UI | 用户上传 GBK txt 看到"文本文件不是有效的 UTF-8 编码"，不再见"缺少 media_ref.id" |
| **B** | 编码兼容：GBK txt 可上传 | 后端优先 UTF-8 解码；失败回退 GBK/GB18030；仍失败才报编码错误（并给可操作提示） |
| **C** | 前后端口径统一：无点文件名判定一致 | Makefile / Dockerfile 两端都放行；LICENSE 等不在白名单两端都拒绝 |
| **D** | 孤儿文件治理 | 失败路径不留孤儿文件（解析/编码失败时回滚或校验前移） |
| **E** | 错误状态码规范化 | 错误分支返回 HTTP 4xx（400 参数错/415 类型不支持/413 超限/422 编码/504 超时），主进程 `resp.ok=false` 自动 reject |

## 涉及的文件与模块

### 后端
- `backend/api/chat_attachment_routes.py`
  - `upload_chat_attachment` 重构：
    - 错误分支改用 `JSONResponse(status_code=...)`
    - 引入错误码枚举 `error_code` 字段（`unsupported_type` / `unsupported_encoding` / `parse_failed` / `parse_timeout` / `too_large`）
    - 文本解码：UTF-8 → GBK/GB18030 回退；仍失败报 `unsupported_encoding`
    - **校验顺序重排**：先解码/解析，后 `store.save()`，避免孤儿
    - 无点文件名：新增 `NO_EXT_FILENAMES` 白名单（Makefile / Dockerfile），精确匹配

### 主进程
- `electron/mediaIpc.ts`
  - `registerMediaIpc`：解析 JSON 后若含 `error` 字段（向后兼容），抛 `new Error(json.error)`
  - HTTP 失败时（status 4xx/5xx），读 `json.error_code` + `json.error` 拼装抛错

### 前端
- `src/shared/lib/hooks/useFileUpload.ts`
  - `startEagerUpload`：失败时 reason 用后端 error 原文；`media_ref.id` 缺失作为最终兜底
  - `preflightAttachment`：无点文件名用白名单（含 `CHAT_NO_EXT_FILENAMES`）
- `src/shared/lib/chatAttachmentFormats.ts`
  - 新增 `CHAT_NO_EXT_FILENAMES = new Set(['makefile', 'dockerfile'])`
  - 文档 `CHAT_DOCUMENT_EXTENSIONS` 不变

### 测试
- 后端 `backend/tests/unit/test_chat_attachment_errors.py`（新建）
  - 断言各错误分支 HTTP 状态码 / error_code / 无孤儿文件 / GBK 兼容
- 主进程 `electron/__tests__/mediaIpc.test.ts`（新建）
  - 模拟后端返回 `{error, error_code}`，验证 reject 抛错含真实文案
- 前端 `src/shared/lib/hooks/__tests__/useFileUpload.error.test.ts`（新建）
  - mock `uploadAttachment` reject 时 reason 等于后端 error

## 技术方案

### 错误码枚举（后端）

```python
class AttachmentErrorCode(str, Enum):
    UNSUPPORTED_TYPE = "unsupported_type"          # 文件类型/扩展名不在白名单
    UNSUPPORTED_ENCODING = "unsupported_encoding"  # 文本编码无法解码
    TOO_LARGE = "too_large"                        # > 25MB
    PARSE_FAILED = "parse_failed"                  # PDF/DOCX 解析抛异常
    PARSE_TIMEOUT = "parse_timeout"                # 解析超时
```

### HTTP 状态码映射

| 错误码 | 状态码 |
|--------|--------|
| `unsupported_type` | 415 |
| `unsupported_encoding` | 422 |
| `too_large` | 413 |
| `parse_failed` | 422 |
| `parse_timeout` | 504 |

### 无点文件名白名单

```python
#: 无扩展名但允许上传的文件名（小写精确匹配）
NO_EXT_FILENAMES = {"makefile", "dockerfile"}
```

后端判定：
```python
name = (file.filename or "").lower()
if "." in name:
    ext = name.rsplit(".", 1)[-1]
elif name in NO_EXT_FILENAMES:
    ext = name  # 作为伪扩展名参与后续判定
else:
    ext = ""
```

前端预检同步：
```typescript
export const CHAT_NO_EXT_FILENAMES = new Set(['makefile', 'dockerfile']);

export function preflightAttachment(...) {
  const name = file.name.toLowerCase();
  const hasDot = name.includes('.');
  const ext = hasDot ? (name.split('.').pop() ?? '') : name;
  if (!CHAT_DOCUMENT_EXTENSIONS.has(ext) && !CHAT_NO_EXT_FILENAMES.has(name)) {
    return { ok: false, reason: 'unsupported' };
  }
  ...
}
```

### GBK 编码回退

```python
def _decode_text_content(content: bytes) -> Optional[str]:
    """UTF-8 → GBK/GB18030 回退；仍失败返回 None。"""
    for encoding in ("utf-8", "gbk", "gb18030"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None
```

> 注：不用 charset-normalizer，避免新增依赖。GBK/GB18030 覆盖中文 Windows 99% 场景。

### 校验前移（避免孤儿）

重构 `upload_chat_attachment`：

```python
@router.post("/chat/attachments")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:
    # 1. 解析文件名与扩展名（含无点白名单）
    # 2. 校验扩展名 → 415 unsupported_type
    # 3. 校验 content-type → 415 unsupported_type
    # 4. 读内容 → 校验大小 → 413 too_large
    # 5. 文本：先解码（UTF-8→GBK→GB18030），失败 → 422 unsupported_encoding
    # 6. 文档：先解析（异步线程，带超时），失败/超时 → 504/422 parse_timeout/parse_failed
    # 7. 全部通过 → store.save()
    # 8. 返回 {"media_ref": ref, "api_url": ..., "text": ...}
```

关键：**`store.save()` 在所有校验之后**。失败路径不留磁盘痕迹。

### 主进程错误透传

```typescript
const json = await resp.json() as {
  media_ref?: unknown;
  api_url?: string;
  error?: string;
  error_code?: string;
};
if (json && typeof json.error === 'string') {
  throw new Error(json.error);
}
return json;
```

### 前端错误文案

```typescript
} catch (err) {
  const reason = err instanceof Error ? err.message : String(err);
  setTarget(prev => prev.map(f => f.id === id ? {
    ...f, status: 'failed', reason
  } : f));
}
```

不再使用固定"上传响应缺少 media_ref.id"文案。

## 实施步骤（TDD）

- [x] **M1 后端错误状态码 + 孤儿治理** (2026-11-24)
  - [x] 写 `test_chat_attachment_errors.py`：GBK txt → 失败 + `unsupported_encoding` + 0 孤儿；Makefile → 200；LICENSE → 415；损坏 pdf → 422 `parse_failed`；无孤儿
  - [x] 重构 `upload_chat_attachment`：校验前移 + 错误码枚举 + HTTP 状态码
  - [x] 验证所有测试绿，孤儿计数 = 0
- [x] **M2 GBK 编码兼容** (2026-11-24)
  - [x] 在 M1 测试加 case：GBK txt 上传成功（HTTP 200，media_ref.id 存在）
  - [x] 实现 `_decode_text_content` 回退链 UTF-8 → GBK → GB18030
  - [x] 验证测试绿
- [x] **M3 无点文件名白名单** (2026-11-24)
  - [x] 测试：Makefile → 200；Dockerfile → 200；LICENSE → 415
  - [x] 后端实现 `NO_EXT_FILENAMES` 白名单
  - [x] 验证绿
- [x] **M4 主进程错误透传** (2026-11-24)
  - [x] 写 `electron/__tests__/mediaIpc.test.ts`：mock fetch 返回 422 + `{error, error_code}`，验证 reject
  - [x] 改 `mediaIpc.ts`：解析后检查 `json.error`
  - [x] 验证测试绿
- [x] **M5 前端错误文案 + 口径统一** (2026-11-24)
  - [x] 改 `startEagerUpload`：丢固定文案，用 err.message
  - [x] 改 `preflightAttachment`：无点文件名用白名单（含 `CHAT_NO_EXT_FILENAMES`）
  - [x] 改 `chatAttachmentFormats.ts`：新增 `CHAT_NO_EXT_FILENAMES`
  - [x] 验证测试绿
- [ ] **M6 集成验证**
  - [ ] 启动后端 `npm run dev` + `electron --no-sandbox .`
  - [ ] 手动拖拽：UTF-8 txt、GBK txt、Makefile、PDF、损坏 pdf，验证 UI 显示真实错误/成功
  - [ ] 检查 `backend/data/media/` 无孤儿
- [ ] **M7 文档与归档**
  - [ ] 更新 `docs/technical/` 相关章节（如有）
  - [ ] 本计划文档标记完成并归档

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| 错误状态码变更破坏已有调用方 | 前端 Chat.tsx 发送兜底也调 `/chat/attachments`（line 375） | 审计确认只有 Chat.tsx + 主进程；前者只检查 `res?.media_ref?.id`，失败路径本来就走 `toast.warning`，4xx 同样进 catch，行为不变 |
| GBK 回退引入数据污染（乱码被接受） | 低：GBK 解码是真实语义，比 UTF-8 失败强 | 显式回退链 UTF-8 → GBK → GB18030；保留 `mime_type` 标注 |
| 校验前移改变副作用顺序 | 低：`_schedule_mineru_enrichment` 依赖 store 已存，需调整到 save 后 | 保留 save 后调用，仅在保存成功时调度 |
| 无点白名单过窄（用户要传 README） | 中：README 不在白名单则 415 | 用户可接受；后续按需扩展白名单。当前只放 makefile/dockerfile 是保守选择 |
| 前端 `preflightAttachment` 行为变化影响现有 UI | 低：仅放宽（无点白名单命中）+ 收紧（非白名单无点拒绝，本来也会被后端拒绝） | 加测试覆盖 |

## 依赖与外部约束

- 无新 Python 依赖（用标准库 `codecs`）
- 无新 npm 依赖
- 主进程 fetch 已是 `node-fetch`，无需变更

## 完成定义（DoD）

- [ ] 所有新增测试绿（pytest + vitest）
- [ ] 现有 `test_chat_attachments.py` / `useFileUpload.test.ts` 仍绿
- [ ] 真机拖拽 UTF-8 txt / GBK txt / Makefile / PDF / 损坏 pdf 都按预期显示
- [ ] `backend/data/media/` 失败后无孤儿（磁盘文件数 = 成功请求数 × 2）
- [ ] PR 通过 CI（main 触发 `ci.yml`）
- [ ] 计划文档归档 / 删除
