# 右侧面板 Round 4 计划——版本互比 + 变更预取 + 产物类型过滤

> 日期: 2026-09-19
> 前序: main #1112/#1153/#1172、win7 #1142/#1158/#1182
> 目标分支: main（合并后 cherry-pick 对齐 release/win7）

## R3 后复盘（剩余差距 → 本轮取舍）

| 差距 | 处置 |
| --- | --- |
| 版本 diff 只能 "vN ↔ 当前"，无法任意两版本互比（评估回滚损失时需要 v2↔v5） | ✅ 批次 A：diff 右侧对象可选（当前版本 / 任意版本） |
| 打开变更 Tab 才拉取变更列表（徽标数据滞后 + 首次切换慢） | ✅ 批次 B：会话切换即预取 changesListStore |
| 产物多时无类型过滤 | ✅ 批次 C：产物 Tab 类型过滤 chips（全部/代码/文档/表格/图片） |
| AI 修改产物的 diff 确认 | ❌ 需后端事件契约（artifact_update_pending），跨栈专项，继续后置 |

## 批次 A：版本互比

- `VersionHistory`：diff 打开时，在 diff 区域顶部渲染 "对比对象" 选择器
  （当前版本 / 其它各版本）；选择后重新拉取两侧内容生成 diff。
- 状态扩展：`diffFor`（左侧固定为点击的版本）+ `diffAgainst`（'current' |
  versionNum，默认 'current'）。
- 复用既有 `unifiedDiff` + `SplitDiff`，零新依赖。

## 批次 B：变更预取

- `RightPanel` 增加会话切换副作用：`sessionId` 变化即
  `changesListStore.fetch(sessionId)`（store 层 inflight 去重，重复触发
  无额外成本）。
- 收益：徽标数据即时可用；切到变更 Tab 无首次加载等待。
- 产物列表无需处理（RightPanel 常挂载，useArtifacts 随会话切换已拉取）。

## 批次 C：产物类型过滤

- `ArtifactsSection` header 右侧加过滤 chips：全部 / 代码(code,json) /
  文档(markdown,text,pdf,docx,pptx) / 表格(csv,xlsx) / 图片(image)。
- 组件本地 state；过滤只影响列表渲染，不影响计数徽标（徽标口径 = 全量）。
- 空态：过滤后无匹配显示 "无该类型产物"。

## 验收

- 单测：VersionHistory 互比（选择另一版本重新生成 diff）、
  ArtifactsSection 过滤渲染与切换、RightPanel 预取触发。
- tsc / eslint / vitest 全量绿。

## Win7 对齐

合并后核对两分支差异再 cherry-pick（win7 已有 VersionHistory/editMode/
changesListStore 基底——R3 已对齐，预期冲突面小）。
