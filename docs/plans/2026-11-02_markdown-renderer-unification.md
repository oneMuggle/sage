# Markdown 渲染器统一（产物面板 / 聊天 / Wiki 共享）

- **日期**：2026-11-02
- **作者**：Sage team
- **状态**：设计中（等待实施）
- **分支**：`feat/markdown-renderer-unification`（基于 `main`，完成后 cherry-pick 到 `release/win7`）
- **范围**：全局统一

## 1. 背景与目标

### 1.1 现状问题

Sage 侧边栏「产物」面板的 Markdown 预览渲染能力严重不足，对比 Typora 与主流 AI 应用，存在以下硬伤：

| 元素 | 产物面板现状 | 根因 |
|---|---|---|
| 标题 h1–h6 | 与正文同大，无层级 | Tailwind preflight 已 reset，FileContentRenderer 未重新赋形 |
| 引用 blockquote | 纯缩进文本，无边框无底色 | 同上 |
| 表格 table | 无边框无单元格内边距，表头不突出 | 同上 |
| 列表 ul/ol | 缩进与列表符号缺失 | 同上 |
| 任务列表 | 复选框不渲染 | 同上 |
| 代码块 | Shiki 高亮 OK | 已实现 |
| 链接 / 图片 | 默认样式 | 无定制 |

**根因**：`src/widgets/chat/preview/FileContentRenderer.tsx:54-79` 的 `MarkdownRendered` 组件只映射了 `code` 一个元素，容器只有 `text-sm leading-relaxed`。Tailwind preflight 默认把所有 `h1–h6 { font-size: inherit; font-weight: inherit; margin: 0 }` + `p { margin: 0 }`，所以产物 markdown 呈现为"字面意义上的扁平文本"。

### 1.2 仓库内已有三份重复实现

| 文件 | 质量 | 覆盖 |
|---|---|---|
| `src/widgets/chat/MessageMarkdownParts.tsx` | ✅ 主流 AI 应用级 | 表格带复制按钮 + sticky 表头 + 限高滚动、任务列表、blockquote、h1–h3、ul/ol/li、链接 |
| `src/widgets/wiki/MarkdownPreview.tsx` | ⚠️ 部分 | h1–h3/table/th/td/blockquote 映射，但 `prose` class 是死代码 |
| `src/widgets/chat/preview/FileContentRenderer.tsx` | ❌ 差 | **只有 `code`** |

另外 `WikiResearchPanel.tsx:194` 与 `AboutTab.tsx:21` 用了 `prose` class 但 `@tailwindcss/typography` 根本没装 —— 也是死代码。

### 1.3 目标

1. **抽出共享 Markdown 渲染器** —— 三处实现收敛成一个，消除漂移
2. **达到 Typora 级排版质感** —— 标题/引用/表格/列表/任务列表/脚注/删除线/图片/链接/horizontal rule 全覆盖
3. **表格增强** —— 复制按钮 / 粘性表头 / 限高内滚动 / 窄屏横向滚动
4. **代码块增强** —— Shiki 高亮（复用现有懒加载）+ 一键复制 + 长代码折叠 + 软换行开关 + 语言标签
5. **大纲目录 TOC（Typora 式）** —— 标题抽取 → 缩进列表 → 滚动高亮当前位置 → 点击跳转
6. **清理死代码** —— 删 3 处无效 `prose` class
7. **零新增依赖** —— 复用现有 react-markdown / remark-gfm / rehype-katex / ShikiCodeBlock / MermaidBlock

## 2. 涉及的文件与模块

### 2.1 新增

| 文件 | 用途 |
|---|---|
| `src/shared/markdown/index.ts` | 统一出口 |
| `src/shared/markdown/Markdown.tsx` | 共享渲染器主组件 |
| `src/shared/markdown/Markdown.css` | `.md-content` 作用域样式 |
| `src/shared/markdown/components.tsx` | h1–h6/p/ul/ol/li/table/th/td/blockquote/a/img/hr/code/pre 映射 |
| `src/shared/markdown/plugins.ts` | remarkPlugins + rehypePlugins 集合 |
| `src/shared/markdown/MarkdownOutline.tsx` | TOC 组件 |
| `src/shared/markdown/outline.css` | TOC 样式 |
| `src/shared/markdown/useMarkdownOutline.ts` | AST → TocEntry[] hook |
| `src/shared/markdown/__tests__/*.tsx` | 4 个测试套件 |

### 2.2 修改

| 文件 | 改动 |
|---|---|
| `src/widgets/chat/preview/FileContentRenderer.tsx` | `MarkdownRendered` 替换为 `<Markdown features="minimal" />` |
| `src/widgets/wiki/MarkdownPreview.tsx` | 替换为 `<Markdown features="minimal" />`（保留 `evaluateWikiMarkdownPreviewGovernanceAudit` 不动） |
| `src/widgets/wiki/WikiResearchPanel.tsx:194` | 删死 `prose` class |
| `src/pages/Help/AboutTab.tsx:21` | 删死 `prose-invert` class |
| `src/widgets/chat/MessageMarkdownParts.tsx:165-276` | markdown body 部分替换为 `<Markdown features="chat" \| "full" />`；保留 chat 专有 UI（thinking dots、tool use badge、image gallery、sources card） |
| `src/widgets/chat/artifacts/ArtifactViewer.tsx` | markdown 渲染加 TOC outline 条 |

### 2.3 不动

- `src/widgets/chat/ShikiCodeBlock.tsx` —— 原样复用
- `src/widgets/chat/MermaidBlock.tsx` —— 原样复用
- `src/widgets/chat/MarkdownImage.tsx` —— 原样复用
- 后端 endpoint —— 无变更
- `package.json` —— 不新增依赖

## 3. 技术方案

### 3.1 `<Markdown />` 主 API

```tsx
import { Markdown } from '@/shared/markdown';

<Markdown
  content={text}
  features="full"               // 'minimal' | 'chat' | 'full'
  onLinkClick={(href, event) => ...}   // 可选：链接拦截
  onImageClick={(src, event) => ...}   // 可选：图片点击
  onHeadingClick={(id) => ...}         // 可选：大纲联动
  headingAnchorPrefix="doc-1"          // 唯一化锚点 id（避免多实例冲突）
  maxTableRows={500}                   // 表格限高（产物/Wiki 默认 500，聊天 200）
  codeFoldOver={40}                    // 代码块折叠阈值
  showLineNumbers={true}
/>
```

**三档 features**（覆盖现有三处实现的不同需求）：

| features | 包含 | 对应调用方 |
|---|---|---|
| `minimal` | GFM 排版层 + 代码块（Shiki）+ 基础表格 | 产物面板 `FileContentRenderer`、Wiki `MarkdownPreview` |
| `chat` | minimal + 代码复制/折叠/换行开关 + 表格增强（复制/sticky/限高） | 聊天 `MessageMarkdownParts` 主体 |
| `full` | chat + Mermaid + KaTeX 数学 | 需要 Mermaid 的场景 |

### 3.2 组件映射表（`components.tsx`）

合并三处现有实现的最优版本：

| 元素 | 来源 | 增强 |
|---|---|---|
| `h1–h6` | `MessageMarkdownParts.tsx` h1–h3 + 扩展 h4–h6 | 加 `id={prefix}-${slug(text)}` 锚点供 TOC 用 |
| `table` | `MessageMarkdownParts.tsx` 现有增强版 | 包一层 `.md-table-wrap[data-clamp]` 实现限高滚动 + 复制按钮 + sticky 表头 |
| `th/td` | `MessageMarkdownParts.tsx` | 保留 sticky top:0 |
| `blockquote` | `MarkdownPreview.tsx` 的边框 + 背景色（用 token 重写） | V2：remark-github-blockquote-alert |
| `ul/ol/li` | `MessageMarkdownParts.tsx` | 任务列表 checkbox 渲染 |
| `code` | `FileContentRenderer.tsx` 现有 inline 判断 + `ShikiCodeBlock` | 支持 fold/line-numbers/wrap-toggle |
| `pre` | 空包装（避免 Shiki 外层重复 pre） | 同 chat |
| `a` | `MarkdownPreview.tsx` | `target="_blank" rel="noopener noreferrer"`；应用内链接走 `onLinkClick` |
| `img` | `MarkdownImage` 复用 | 点击预览 |
| `hr` | 用 `.md-content hr` CSS | 无 |
| Mermaid | `features="full"` 时注入 `code` 的 mermaid 分支 | 复用 `MermaidBlock.tsx` |
| KaTeX | `features="chat" \| "full"` 时启用 `remarkMath + rehypeKatex` | minimal 不开避免 KaTeX CSS 重复加载 |

### 3.3 样式方案（`markdown.css`）

作用域 `.md-content`，全部用现有 design token（`var(--color-*)` / `var(--ui-font-size)` / `var(--font-code)`），零新 dep，暗色模式通过 token 自动切换无需额外规则。

关键：

```css
.md-content { font-size: var(--ui-font-size, 14px); line-height: 1.6; color: var(--color-text); }

/* 标题 —— preflight 已 reset，这里显式覆盖 */
.md-content h1 { font-size: 1.75rem; font-weight: 700; margin: 1.5rem 0 0.75rem; border-bottom: 1px solid var(--color-line); padding-bottom: 0.5rem; }
.md-content h2 { font-size: 1.4rem; font-weight: 600; margin: 1.25rem 0 0.5rem; border-bottom: 1px solid var(--color-line); padding-bottom: 0.375rem; }
.md-content h3 { font-size: 1.15rem; font-weight: 600; margin: 1rem 0 0.4rem; }
.md-content h4 { font-size: 1rem; font-weight: 600; margin: 0.75rem 0 0.375rem; }
.md-content h5, .md-content h6 { font-size: 0.875rem; font-weight: 600; margin: 0.5rem 0 0.25rem; color: var(--color-text-secondary); }

/* 引用块 */
.md-content blockquote {
  border-left: 4px solid rgb(var(--color-primary-rgb) / 0.4);
  background: rgb(var(--color-bg-muted-rgb) / 0.5);
  padding: 0.5rem 0.75rem;
  margin: 0.75rem 0;
  color: var(--color-text-secondary);
  border-radius: 0 4px 4px 0;
}

/* 表格 + 粘性表头 */
.md-table-wrap { overflow-x: auto; margin: 0.75rem 0; }
.md-table-wrap[data-clamp] { max-height: 24rem; overflow-y: auto; }
.md-content th { background: var(--color-bg-muted); font-weight: 600; position: sticky; top: 0; z-index: 1; }

/* 任务列表 */
.md-content li:has(> input[type="checkbox"]) { list-style: none; margin-left: -1.5rem; }
```

约束：
- 不引入 `@tailwindcss/typography`
- 不依赖 preflight reset，所有样式显式覆盖
- 绝不硬编码 `text-[14px]` 等 —— 用 `text-ui-sm` / `text-ui-base` 或纯 CSS，过 fontScaleGate
- 暗色模式通过 token 自动变色，零额外 CSS

### 3.4 TOC 大纲（`useMarkdownOutline` + `MarkdownOutline`）

```tsx
// useMarkdownOutline.ts
export type TocEntry = {
  id: string;           // 与 h* 渲染的 id 一致
  level: 1|2|3|4|5|6;
  text: string;
  depth: number;        // 0 = h1, 1 = h2 ...
};

export function useMarkdownOutline(content: string, prefix = 'md'): TocEntry[] {
  return useMemo(() => {
    // 用 remark-parse + unified 走一遍 AST（不渲染）
    // 提取 heading 节点，slug(text) 生成 id
  }, [content, prefix]);
}
```

`<MarkdownOutline entries activeId onJump />`：缩进列表，activeId 高亮。

宿主挂载（`ArtifactViewer.tsx`）：
- TOC 条：容器宽度 < 400px 时折叠成 "大纲 · 12 项" chip（点击弹出 popover）；≥ 400px 时展开
- IntersectionObserver 监听 `[id^="${prefix}-"]` 的 h* 元素，activeId 实时更新
- 仅在 markdown 产物激活时挂 observer

### 3.5 安全

- react-markdown 默认不开 rehype-raw → LLM/用户上传 markdown 中的 `<script>` / `on*` 属性自动剥
- 链接默认 `target="_blank" rel="noopener noreferrer"`
- 应用内链接走 `onLinkClick` 拦截

## 4. 实施步骤

- [ ] **M1** 新建 `src/shared/markdown/` 模块（Markdown.tsx / components.tsx / plugins.ts / markdown.css / MarkdownOutline.tsx / outline.css / useMarkdownOutline.ts / index.ts + 4 个测试）
- [ ] **M2** 迁移 `FileContentRenderer.tsx` 的 `MarkdownRendered` → `<Markdown features="minimal" />`
- [ ] **M3** 迁移 `MarkdownPreview.tsx` → `<Markdown features="minimal" />`；清理 `WikiResearchPanel.tsx:194` 死 `prose` class
- [ ] **M4** 迁移 `MessageMarkdownParts.tsx` 的 markdown body → `<Markdown features="chat" | "full" />`；清理 `AboutTab.tsx:21` 死 `prose-invert` class
- [x] **M5** `ArtifactViewer.tsx` 加 TOC outline 条（OutlineBar）
- [ ] **M6** 验证：`npm run typecheck` + `npm run test:run` + `npm run build` 全绿
- [ ] **M7** 提交 + push + 创建 PR；CI 绿后 merge 到 main
- [ ] **M8** Cherry-pick 到 `release/win7` 并同步（pydantic 无差异，纯前端零适配）

## 5. 风险评估与缓解

| 风险 | 缓解 |
|---|---|
| Win7 分支同步（CLAUDE.md 强制） | cherry-pick 到 `release/win7`，纯前端零版本差异 |
| fontScaleGate 拦硬编码 `text-[Npx]` | 全部用 `text-ui-sm / text-ui-base` 或纯 CSS |
| architecture-baseline 棘轮 | 不追踪前端文件（已验证），无影响 |
| 体积棘轮（1.6→1.8MB 预算） | 不新增 dep；shiki/mermaid 已经懒加载；新增 CSS ~3KB + TS ~400 行 |
| TOC 性能 | `useMemo` + AST 解析 < 1ms；IntersectionObserver 仅 active 时挂 |
| 暗色模式 | token 自动切换，无需额外 CSS |
| Mermaid 初始化开销 | `features="full"` 显式 opt-in |
| 安全 | react-markdown 默认不开 rehype-raw |

## 6. 不在范围内（YAGNI）

- ❌ 源码/渲染双栏同屏（Typora 特色） —— 已有 source/render 切换
- ❌ 实时协同编辑（多光标）
- ❌ PDF 导出 —— 用后端 HTML 导出链路
- ❌ 公式编辑器 —— 用户直接写 LaTeX
- ❌ `remark-cjk-friendly` / `remark-smartypants` / `remark-emoji` —— V2 加，本次不引入新 dep
- ❌ 引入 `@tailwindcss/typography` —— 已有 design token 体系，手写 CSS 更贴合

## 7. 测试矩阵

- `Markdown.gfm.test.tsx`：表/任务列表/删除线/autolinks 全部渲染
- `Markdown.math.test.tsx`：`$inline$` + `$$display$$` 走 KaTeX
- `Markdown.code.test.tsx`：inline code、fenced block、未知语言降级、复制按钮
- `Markdown.outline.test.tsx`：TOC 抽取层级正确、activeId 联动、锚点 id 唯一
- `Markdown.sanity.test.tsx`：raw HTML `<script>` / `on*` 被剥、链接带 `rel="noopener noreferrer"`

## 8. 成功标准

- 产物面板 Markdown 预览的标题层级、引用、表格、列表、任务列表、图片、链接、分隔线全部正确渲染
- 表格带复制按钮 + 粘性表头 + 限高滚动
- 代码块 Shiki 高亮 + 复制 + 折叠 + 换行切换
- markdown 产物显示 TOC 大纲，滚动高亮当前位置
- 三处实现收敛成一个，无漂移
- 3 处死 `prose` class 已清理
- 零新增依赖
- `npm run typecheck` + `npm run test:run` + `npm run build` 全绿
- main 与 release/win7 功能对齐
