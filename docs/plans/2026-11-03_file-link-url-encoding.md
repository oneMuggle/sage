# 文件链接 URL 编码导致右栏预览 404 修复

> 日期：2026-11-03
> 分支：`fix/file-link-url-encoding`
> 影响范围：前端（消息内文件蓝色链接 → 右栏预览）

## 背景与目标

在会话中 LLM 输出生成文件的蓝色链接后，用户点击链接，右侧栏文件路径显示为
URL 编码字样（如 `/gxw%E7%AE%97`），下方提示 "error 文件不存在 HTTP 404"，
且产物列表未追踪到该文件。

**目标**：点击文件蓝色链接后，右栏正确显示原始路径并成功预览文件内容。

## 根因

`mdast-util-to-hast` 在将 markdown link AST 转换为 hast `<a>` 元素时，调用
`micromark-util-sanitize-uri` 的 `normalizeUri()` 函数，该函数对 URL 中的
非 ASCII 字符（如中文）做 percent-encoding。但 `components.tsx` 的 `<a>` 组件
覆盖在调用 `onLocalFileClick(href!)` 时，直接传了编码后的 `href`，未做
`decodeURIComponent` 解码。后端 `workspace_preview_routes.py` 的
`_resolve_workspace_target` 把编码路径当字面量处理，找不到文件 → 404。

数据流：

```
LLM 输出 "output/算法.md"
→ remarkFileRefLinks 创建 link 节点 url: "output/算法.md"
→ mdast-util-to-hast: normalizeUri → "output/%E7%AE%97%E6%B3%95.md"
→ components.tsx <a> onClick: onLocalFileClick(href!)  // href 已编码
→ rightPanelStore.openFilePreview(encodedPath)
→ FilePreviewPanel 显示编码路径 + 调 workspaceApi.previewFile(encodedPath)
→ 后端 _resolve_workspace_target 找不到字面路径 → 404
```

## 涉及的文件与模块

| 文件 | 改动 |
|---|---|
| `src/widgets/markdown/components.tsx` | **主修复**：onClick 中 decodeURIComponent |
| `src/widgets/markdown/links.ts` | `isLocalFilePathHref` 先 decode 再判定 |
| `src/widgets/chat/preview/FilePreviewPanel.tsx` | 防御性 decode 兜底 |
| `src/widgets/chat/__tests__/FileReferenceLinks.test.tsx` | 补充中文路径测试 |

## 实施步骤

- [x] Task 1: `components.tsx` — `onLocalFileClick(decodeURIComponent(href!))` + title 解码
- [x] Task 2: `links.ts` — `isLocalFilePathHref` 先 decode 再判定路径特征 + 新增 `safeDecodeUri`
- [x] Task 3: `FilePreviewPanel.tsx` — 入口 decode 兜底
- [x] Task 4: 补充测试用例（中文路径点击 → 正确解码路径传给回调）
- [x] Task 5: 本地 vitest 验证（17 + 4 + 74 = 95 tests all green）

## 风险评估

- 改动仅涉及前端渲染层，不涉及后端/API 变更
- `decodeURIComponent` 对纯 ASCII 路径是 no-op，不影响现有英文路径
- `try/catch` 包裹 decode 以容忍畸形 URI（如裸 `%`）
