# 右侧面板 Round 3 计划——版本 diff 视图 + CodeMirror 编辑 + 变更计数上抬

> 日期: 2026-09-19
> 前序: main #1112(R1)/#1153(R2)、win7 #1142(R1)/#1158(R2,经 anyio 审计策略修复 #1163 后合入)
> 目标分支: main（合并后 cherry-pick 对齐 release/win7）

## R2 后复盘（剩余差距 → 本轮取舍）

| 差距 | 处置 |
| --- | --- |
| 版本历史只有列表+恢复，看不到版本间 diff（不知道恢复会丢什么） | ✅ 批次 A |
| 编辑模式是裸 textarea（无行号/编辑体验差） | ✅ 批次 B（@uiw/react-codemirror，已有依赖） |
| 变更 Tab 无计数徽标（数据锁在 ChangesSection 组件内） | ✅ 批次 C（changesListStore 上抬） |
| agent 修改产物时的 AI diff 确认 | ❌ R4+（需后端事件联动） |
| Ctrl+Shift+P 心智冲突 | ❌ 不动 |

## 批次 A：版本 diff 视图

1. 新 `src/shared/lib/unifiedDiff.ts`：行级 LCS 产出标准 unified diff
   字符串（`@@ -a,b +c,d @@` 头 + 空格/−/+ 行，上下文 3 行），格式与
   `splitDiffParser` 的输入约定一致，零新依赖，纯函数可单测。
2. `VersionHistory` 每行加"对比"按钮（GitCompare 图标）：加载该版本内容
   （`getArtifactVersion`）与当前内容（`readArtifactContent`），经
   `unifiedDiff` 生成 diff，用既有 `SplitDiff` 渲染在行下展开区；同一时间
   只展开一个 diff（再次点击收起）。

## 批次 B：CodeMirror 编辑

`ArtifactViewer` editMode 的 textarea → `@uiw/react-codemirror`（基本
配置：行号 + 折行；不做语言包扩展，避免新增依赖），value/onChange 与
既有乐观并发 hash 保存逻辑完全兼容。

## 批次 C：变更计数上抬

1. 新 `src/features/changes/changesListStore.ts`：`bySession:
   Record<sid, WorkspaceChanges>` + inflight 去重（镜像 artifactListStore）。
2. `ChangesSection` 的 changes/loading 改读 store（selection/diff/checkpoint
   等交互态保留本地）；`workspace_not_bound` 错误处理不变。
3. `RightPanel` 把 `changes?.changes.length`（未 clean 时）传给
   PanelHeader，变更 Tab 显示 "变更 (N)"（N>0 才显示）。

## 验收

- 单测：unifiedDiff（增/删/改/上下文截断/空输入）、VersionHistory
  diff 展开、ChangesSection store 计数、PanelHeader 变更徽标。
- tsc / eslint / vitest 全绿。

## Win7 对齐

合并后核对两分支差异再 cherry-pick（已知差异：win7 useArtifactContent
多 refresh、MessageList topic_separator、审计策略文件已在前置 PR #1163
更新——base 对齐后无冲突预期）。
