# 修复 main 上三处 Markdown 公式渲染失效

- 日期：2026-10-21
- 分支：`fix/main-katex-remark-math-20261021` → `main`
- 来源：win7 对齐过程中发现（`chore/win7-align-b5` 批次）

## 1. 问题

`rehype-katex` 只负责把**已经存在的 math AST** 渲染成 KaTeX 节点。
真正产出 math AST 的是 `remark-math`。两者缺一不可：

```
"$E=mc^2$"  --remark-math-->  math AST  --rehype-katex-->  <span class="katex">…</span>
"$E=mc^2$"  --(无 remark-math)-->  纯文本   --rehype-katex-->  什么都不做
```

main 上 5 处 `ReactMarkdown` 的插件挂载情况：

| 文件 | `remark-math` | `rehype-katex` | 结果 |
|---|---|---|---|
| `src/widgets/chat/MessageMarkdownParts.tsx` | ✅ | ✅ | 正常 |
| `src/widgets/chat/artifacts/ArtifactViewer.tsx` | ✅ | ✅ | 正常 |
| `src/features/chat/BtwOverlay.tsx` | ❌ | ✅ | **公式降级为纯文本** |
| `src/pages/Help/HelpTab.tsx` | ❌ | ✅ | **公式降级为纯文本** |
| `src/widgets/wiki/MarkdownPreview.tsx` | ❌ | ❌ | **完全无公式支持** |

中间两处最阴：代码里明明白白写着 `rehypePlugins={[rehypeKatex]}`，看起来"已经挂了 KaTeX"，
实际一次都没生效过。

## 2. 来源与可信度

这个问题是 win7 侧在 **alpha.36 (Bug #6)** 发现并修好的（win7 有
`MarkdownPreview.latex.test.tsx` / `BtwOverlay.latex.test.tsx` 两个测试锁着）。
main 后来在 Markdown 渲染重构里把插件漏掉了，`package.json` 里的
`remark-math: ^6.0.0` 依赖一直都在，只是没人引用它。

所以这不是 win7 独有需求，而是 **main 的回归**。

## 3. 改动

三处补插件：

- `src/widgets/wiki/MarkdownPreview.tsx`：补 `remark-math` + `rehype-katex`（两件都缺）
- `src/features/chat/BtwOverlay.tsx`：补 `remark-math`
- `src/pages/Help/HelpTab.tsx`：补 `remark-math`

## 4. 测试

### 4.1 从 win7 移植的行为测试（2 个文件）

- `src/widgets/wiki/__tests__/MarkdownPreview.latex.test.tsx`
  - 行内 `$E=mc^2$` 产出 `.katex`
  - 块级 `$$…$$` 产出 `.katex-display`
  - 未配对的 `$5` 保持纯文本
- `src/features/chat/__tests__/BtwOverlay.latex.test.tsx`

### 4.2 新增仓库级不变量测试

`src/shared/lib/__tests__/markdownKatexPlugins.test.ts`：

> 任何 `import ... from 'rehype-katex'` 的源文件，也必须 `import ... from 'remark-math'`。

选这个形式而不是给 HelpTab 写组件测试，理由：
- HelpTab 依赖接口加载内容，组件测试要大量 mock，收益低
- 不变量测试**一次覆盖全部 5 处**，并且能拦住以后新增的 `ReactMarkdown` 用法
- 「挂了 katex 忘了 math」是组合错误，逐组件测试很容易继续漏

## 5. 验证

| 闸门 | 结果 |
|---|---|
| `tsc --noEmit` | 0 错误 |
| 移植的两个 latex 测试 + 原有 `Message.latex.test.tsx` | 3 files passed |
| 新增不变量测试 | 2 passed |
| **不变量测试的负向验证** | 临时移除 `HelpTab.tsx` 的 `remark-math` → 精确报出 `pages/Help/HelpTab.tsx` 为 offender，恢复后转绿 |
| `vitest run`（全量） | 见 PR |
| `eslint src` | 0 error |

负向验证是必要的：第一版测试里 `SRC_ROOT` 少算了一级目录，只扫了 `src/shared`，
测试"通过"其实是空转。这类扫描型测试必须做一次人为破坏来确认覆盖面。

## 6. 与 win7 的关系

修好之后 main 与 win7 在这三处行为一致。win7 侧对应文件已在
`chore/win7-align-b5-20261021` 分支里对齐（`MarkdownPreview` 保留 win7 版本、
`BtwOverlay` 取 main + 嫁接 `remarkMath`）。

main 先修、win7 后合并，可以避免 win7 继续维护一份"修好的副本"。
