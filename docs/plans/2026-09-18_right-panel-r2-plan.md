# 右侧面板 Round 2 计划——P1-5 预览升级 + P2 交互打磨

> 日期: 2026-09-18
> 前序: main #1112（R1 状态全局化/自动唤起/内联卡片/全屏档位）、win7 #1142（对齐）
> 目标分支: main（合并后 cherry-pick 对齐 release/win7，注意 MessageList 的 topic_separator
> 分支结构与 useArtifactContent 的 refresh 字段是两分支已知差异）

## R1 后复盘（剩余差距 → 本轮取舍）

| 差距 | 处置 |
| --- | --- |
| 代码/JSON 预览是裸 `<pre>`，无语法高亮 | ✅ 本轮批次 A（复用 ShikiCodeBlock，消息流同源） |
| Markdown 产物按纯文本展示，无渲染视图 | ✅ 本轮批次 A（ReactMarkdown + 渲染/源码切换） |
| HTML 沙盒 iframe 无刷新（agent 迭代后看旧画面） | ✅ 本轮批次 A |
| CSV 预览无复制 | ✅ 本轮批次 A（复制全文按钮） |
| overlay 抽屉无遮罩/点外不关/Esc 不关 | ✅ 本轮批次 B |
| Tab 无计数徽标 | ✅ 本轮批次 C（仅产物 Tab——数据已在 artifactListStore；变更数据在 ChangesSection 组件内，上抬留后续） |
| 产物/变更空态无引导 | ✅ 本轮批次 C |
| 版本历史（需后端 schema） | ❌ R3 独立轮次 |
| 面板内编辑 + diff 确认 | ❌ R4+（依赖 SplitDiff 接线） |
| Ctrl+Shift+P 与"命令面板"心智冲突 | ❌ 暂不动（Electron 内无实际冲突，换绑收益低） |

## 方案

### 批次 A：ArtifactViewer 预览升级（零新依赖）

1. **代码/JSON 高亮**：`content.kind === 'code' | 'json'` 分支改用
   `ShikiCodeBlock`（`src/widgets/chat/ShikiCodeBlock.tsx`，消息流已用，
   异步高亮自带 loading）。语言按扩展名映射（.py→python、.ts(x)→typescript、
   .js(x)→javascript、.json→json、.md→markdown、.sh→bash、.rs→rust、
   .go→go、.java→java、.css/.html 等常用子集；未识别回落 text）。
2. **Markdown 渲染**：`kind === 'markdown'` 默认渲染视图（ReactMarkdown +
   remarkGfm，代码块走 ShikiCodeBlock 同消息流口径），header 加
   渲染/源码双态切换（Eye / FileCode 图标），源码态为 ShikiCodeBlock。
3. **HTML 刷新**：kind === 'html' 时 header 加刷新按钮 → iframe key 重挂载。
4. **CSV 复制**：CsvPreview header 加"复制全文"按钮（navigator.clipboard）。

### 批次 B：overlay 抽屉三件套

- overlay 模式打开时渲染半透明遮罩（`bg-black/40`，`aria-hidden`，
  点击 → setOpen(false)）；push 模式不受影响。
- overlay 打开时 Esc 关闭（push 的 Esc 只用于退最大化，不关面板）。
- 遮罩随面板 200ms 平移淡入淡出（同 duration），`prefers-reduced-motion`
  由全局 media query 兜底。

### 批次 C：信息密度

1. **产物 Tab 计数**：PanelHeader 的产物 tab 文案渲染 `产物 (N)`
   （N = artifactListStore 该会话条数；0 或无会话不显示计数）。
2. **空态引导**：
   - 产物空态：追加一句"让 agent 写文件/生成文档后，产物会出现在这里"；
   - 变更空态：同样补一句引导（ChangesSection 现有空态文案检查后补）。

## 不做（本轮明确排除）

- 变更 Tab 计数（需把 ChangesSection 数据上抬，收益/成本比低，后延）
- 版本历史 / 面板内编辑（见上表）
- 自动唤起的设置页入口（R1 已有面板内 Bell 开关，够用）

## 验收

- 单测：ArtifactViewer（markdown 渲染/源码切换、代码高亮挂载、HTML 刷新
  remount、CSV 复制调用 clipboard）、RightPanel（overlay 遮罩渲染与点击
  关闭、overlay Esc 关闭、push 无遮罩）、PanelHeader（产物计数徽标）。
- 回归：既有 ArtifactViewer/ArtifactsSection/RightPanel/PanelHeader/
  Message* 全绿；tsc / eslint / vitest 全绿。
- 手测路径：md 产物默认渲染可切源码；py 产物高亮；HTML 改完点刷新生效；
  窄屏开面板有遮罩、点外/Esc 关；产物 Tab 显示计数。

## Win7 对齐

本轮触碰文件：ArtifactViewer.tsx（两分支可能有 refresh 差异——win7 的
useArtifactContent 多返回 refresh，ArtifactViewer 若两分支同源则可直接
cherry-pick）、RightPanel.tsx、PanelHeader（在 RightPanel.tsx 内）、
ArtifactsSection.tsx、ChangesSection.tsx（空态文案）、MessageList.tsx（无改动
则无冲突）。合并后核对两分支差异再 cherry-pick，PR 到 release/win7。
