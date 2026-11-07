# Markdown 渲染器统一（聊天 / 产物面板 / Wiki）

> 状态：已实现（2026-11-02，main PR #2805 / release-win7 PR #2810）
> 适用：聊天消息、侧边栏产物预览、Wiki 预览、文件预览
> 相关代码：`src/widgets/markdown/`、`src/widgets/chat/MessageMarkdownParts.tsx`、`src/widgets/chat/preview/FileContentRenderer.tsx`、`src/widgets/chat/artifacts/ArtifactViewer.tsx`、`src/widgets/wiki/MarkdownPreview.tsx`

## 1. 背景

改造前仓库内存在三份互不一致的 Markdown 渲染实现：

| 文件 | 质量 | 问题 |
| --- | --- | --- |
| `MessageMarkdownParts.tsx` | 较好 | 表格复制 / sticky 表头 / 任务列表，但与其他两处行为漂移 |
| `wiki/MarkdownPreview.tsx` | 部分 | 手写映射，`prose` class 是死代码（未安装 `@tailwindcss/typography`） |
| `chat/preview/FileContentRenderer.tsx` | 差 | 只映射了 `code`，标题/引用/表格全部退化为扁平文本 |

根因：Tailwind preflight 把 `h1–h6` / `p` 的 margin、font-size 全部 reset，而产物面板没有重新赋形。

目标：收敛为单一实现，达到 Typora 级排版，并补齐表格 / 代码块 / TOC 增强；零新增依赖。

## 2. 模块结构

```
src/widgets/markdown/
├── Markdown.tsx          # 主组件（tier / 锚点 / 表格限高 / 流式开关）
├── components.tsx        # createMarkdownComponents 工厂 + MarkdownTable + tableToTsv
├── plugins.ts            # MD_REMARK_PLUGINS / MD_REHYPE_PLUGINS
├── outline.ts            # extractHeadings / buildMarkdownOutline / slugifyHeading（纯函数）
├── MarkdownOutline.tsx   # TOC 组件（IntersectionObserver + 点击跳转）
├── links.ts              # isLocalFilePathHref（从 MessageMarkdownParts 抽出）
├── i18n.ts / useMdI18n.ts
├── markdown.css / outline.css
└── __tests__/            # code / gfm / math / outline
```

统一出口 `src/widgets/markdown/index.ts`，消费者只从这里 import。

## 3. 两档 tier

| tier | 代码块 | 图片 | 表格 | 使用方 |
| --- | --- | --- | --- | --- |
| `minimal` | plain `<pre><code>` | `<img loading="lazy">` | 复制 + 限高 | `FileContentRenderer`、Wiki `MarkdownPreview` |
| `chat` | Shiki / Mermaid / HTML 预览 | `MarkdownImage` | 复制 + 限高 + sticky 表头 | 聊天 `MessageMarkdownParts` |

`const useRichBlocks = tier === 'chat' && !plainFences;`

- 原计划的 `full` 档（KaTeX 显式 opt-in）被砍掉：三处实现本来就默认启用 KaTeX，无需单独档位。
- 插件集合统一为 `remark-gfm + remark-math + rehype-katex`（`plugins.ts`），可通过 `remarkPlugins` / `rehypePlugins` prop 覆盖。
- `pre` 映射为透明包装，避免 Shiki 组件出现嵌套 `<pre>`。
- `code` 映射区分 inline / fenced；fenced 在 `chat` 档按语言分发到 `MermaidBlock` / `HtmlCodeBlock` / `ShikiCodeBlock`。

## 4. 流式渲染性能

- `MessageMarkdownParts` 的 `MarkdownChunk` 使用 `memo` 自定义比较器：仅当 `md` 或 `plainFences` 变化才重渲染。
- 流式期间传 `plainFences`，代码块走 plain `<pre><code>`，避免 Shiki 每帧重高亮抖动；流式结束后切回 Shiki。
- `Markdown` 内部用 `markdownComponentsDeps()` 生成 `useMemo` 依赖，只有语义字段变化才重建 components map。

## 5. 标题锚点与 TOC

- 每个实例传入唯一 `headingAnchorPrefix`：聊天用 `useId()` 清洗为 `chat-<alnum>`；产物面板用 `artifact-<sanitize(name)>`。
- 渲染 heading 时通过 `node.position.start.line` 查 `headingIdForLine(headings, line, prefix)`，id 与 TOC 完全一致。
- `extractHeadings` 用正则扫描源文本（ATX + Setext，跳过 fenced code），行号 1-based，与 mdast 对齐；`slugifyHeading` Unicode 感知（中文可用），重复标题自动加 `-1` / `-2`。
- `MarkdownOutline` 用 `IntersectionObserver` 监听 `[id^="${prefix}-"]` 的 h1–h6；`scrollContainerRef` 作为 root；点击 `scrollIntoView({ block: 'start', behavior: 'smooth' })`，不改 URL hash。
- 产物面板（`ArtifactViewer`）在 markdown 产物有标题时默认展开右侧大纲，工具栏按钮可折叠。

## 6. 样式

`markdown.css` 全部作用域在 `.md-content`，只用既有 design token：

- 标题 h1–h6 显式恢复字号/字重/margin；h1/h2 带底部分隔线。
- blockquote 左边框 + 淡背景 + 圆角；表格边框、单元格 padding、sticky 表头。
- `.md-table-wrap[data-clamp]` 限高（默认 24rem）+ `overflow: auto`；窄屏横向滚动。
- 任务列表用 `li:has(> input[type="checkbox"])` 去掉列表符号。
- 暗色模式靠 token 自动切换，无额外规则；不引入 `@tailwindcss/typography`。
- 不硬编码 `text-[Npx]`，过 `scripts/check-font-scale.mjs`。

## 7. i18n

`i18n.ts` 自包含中英字典（表格复制/已复制、代码复制/折叠/换行、大纲标题/项数），通过 `useMdI18n()` 读取；优先复用全局 `useOptionalI18n()` 的 locale，Provider 缺失时默认中文。不向 `shared/lib/i18n` 注入，避免 shared→widgets 反向依赖。

## 8. 链接与安全

- `isLocalFilePathHref` 迁到 `widgets/markdown/links.ts` 并从 `index.ts` 再导出，聊天与预览共用。
- 本地文件链接：有 `onLocalFileClick` 时拦截并打开预览；无回调时降级为纯文本。外部链接统带 `target="_blank" rel="noopener noreferrer"`。
- 不开 `rehype-raw`，原始 HTML / `on*` 属性默认被剥。

## 9. 迁移与清理

- `FileContentRenderer` 的 `MarkdownRendered` 删除，改为 `<Markdown tier="chat" />`。
- `MessageMarkdownParts` 删除本地 `CodeBlock` / `MarkdownTable` / `PlainCodeBlock` / `markdownComponents` / `liveMarkdownComponents` / `FILE_EXT_RE` / `NON_FILE_SCHEME_RE`（约 180 行），保留 thinking / tool-use / image gallery 等聊天专有 UI。
- Wiki `MarkdownPreview` 改为 `<Markdown tier="minimal" />`，`evaluateWikiMarkdownPreviewGovernanceAudit` 保持不动。
- 删除 `WikiResearchPanel`、`AboutTab`、Wiki 预览中的死 `prose` / `prose-invert` class。

## 10. 测试与验证

| 套件 | 覆盖 |
| --- | --- |
| `Markdown.gfm.test.tsx` | 表格 / 任务列表 / 删除线 / autolink |
| `Markdown.code.test.tsx` | inline code、fenced、未知语言降级、复制 |
| `Markdown.math.test.tsx` | `$inline$` 与 `$$display$$` 走 KaTeX |
| `Markdown.outline.test.ts` | 层级抽取、slug 唯一化、fenced 内 `#` 跳过、行号映射 |

本地门禁：`npm run typecheck`、`npx vitest run`、`node scripts/architecture-check.mjs`、`node scripts/check-font-scale.mjs`、`npm run build` 全绿。

## 11. 双分支

纯前端变更，无 pydantic / py38 差异。main 合并后 cherry-pick 到 `release/win7`；唯一冲突是 Wiki `MarkdownPreview.tsx`（win7 保留旧实现），取 main 侧并保留审计函数。win7 无 LaTeX 预览栈，`FileContentRenderer` 不引入 main-only 的 `latex` 分支。

## 12. 已知边界

- `minimal` 档不渲染 Mermaid（按纯代码块展示），需要图表预览请用 `chat` 档。
- TOC 仅产物面板接入；聊天消息与 Wiki 暂不显示大纲。
- 表格复制输出 TSV，与原聊天行为一致；不支持复制为 Markdown 源码。

## 13. Mermaid 交互式图表（2026-11-04，rich-preview-rendering Task 3）

```mermaid 代码块在 `chat` 档走 `MermaidDiagram` 组件（从原 `MermaidBlock` 抽出交互逻辑），
提供对标 ChatGPT / Claude / Typora 的图表交互：

| 交互 | 行为 |
| --- | --- |
| 拖拽平移 | `pointerdown → pointermove → pointerup` + `setPointerCapture` |
| Ctrl+滚轮缩放 | 范围 0.4–3.0，步进 1.25；原生非 passive `wheel` 监听（React `onWheel` 默认 passive 无法 `preventDefault`），回调 ref 持有 viewport 元素让事件监听跨重挂载存活 |
| 双击画布 | 复位到 100%（`scale(1)` 并清空 `translate`） |
| 工具条 | 放大 / 缩小 / 适应屏幕（按 SVG viewBox 与容器比计算缩放）/ 实际大小 / 源码视图切换 / 下载 PNG / 下载 SVG / 复制源码 / 全屏 |
| 全屏 | `createPortal` 到 `document.body`，ESC / 背景点击 / × 按钮关闭；portal 模式工具条独立（bar variant，按钮更大） |
| 错误详情 | 先 `await mermaid.parse(code)` 预检，抛错后渲染 `mermaid-fallback` + `mermaid-error-detail`（含具体行号）+ `ShikiCodeBlock` 源码 |

**模块拆分**：

- `src/widgets/chat/MermaidDiagram.tsx`（550 行，新）：所有渲染 / 交互 / 审计逻辑；
  `MermaidBlockAuditInput` / `formatMermaidBlockAuditSnapshot` / `formatMermaidBlockAuditJson` 在此定义，向后兼容地 re-export。
- `src/widgets/chat/MermaidBlock.tsx`（38 行，薄包装器）：主题跟随（`MutationObserver` 观察 `html.dark`）+ `<MermaidDiagram code theme />`。
- mermaid 仍走动态 `import()` 独立 chunk，不打开含图表的会话不加载，主包零增长。

**DOM 契约**（与历史测试一致）：`mermaid-loading` / `mermaid-fallback` / `mermaid-figure`（承载 `data-mermaid-block-audit` 快照）/ `mermaid-canvas`（承载 `transform`）/ `mermaid-viewport`（指针/滚轮交互宿主）/ `mermaid-toolbar`（hover variant + bar variant）/ `mermaid-source-textarea`（只读源码）/ `mermaid-fullscreen`（portal）/ `mermaid-block-audit-copy` / `mermaid-block-audit-copy-json`（sr-only 审计控制）。全屏态 portal 独占 DOM，避免与 inline view 的 `getByLabelText` 歧义。

**测试覆盖**（10 单测 + 4 旧单测）：

- 工具条 9 个入口（`mermaid-zoom-in/out` / `mermaid-fit` / `mermaid-actual-size` / `mermaid-toggle-source` / `mermaid-download-png` / `mermaid-download-svg` / `mermaid-copy-source` / `mermaid-fullscreen-open`）
- 源码切换：点击后显示 `textarea` 带原文，再次点击恢复 `mermaid-figure`
- 解析失败：`mermaid.parse` reject → `mermaid-fallback` + `mermaid-error-detail` 含原始错误信息
- 拖拽平移：`pointerDown(10,10) → pointerMove(30,40) → pointerUp` → transform 含 `translate(20px, 30px)`
- Ctrl+滚轮缩放：`ctrlKey=true` 时 `deltaY<0` 放大到 125%，`ctrlKey=false` 无变化
- 双击复位：drag 后再双击 → transform 仅含 `scale(1)` 无 translate
- 工具条缩放按钮与实际大小 / 适应屏幕复位
- 下载 SVG：`URL.createObjectURL` 的 blob type 含 `image/svg+xml`，size > 0
- 复制源码：`navigator.clipboard.writeText` 写入原文
- 全屏：`mermaid-fullscreen-open` → portal，ESC → portal 关闭，inline `mermaid-figure` 恢复
- 卸载清理：`copiedTimerRef` 在组件卸载时 `clearTimeout`，避免残留 `setState`

`MermaidBlock.test.tsx` 与 `MermaidBlock.toolbar.test.tsx` 全部保持绿（契约零破坏）。
```
