# Win7：B5 批次残余的前端对齐

- 日期：2026-10-27
- 基线：`release/win7`
- 相关：#2274（B5 批次，已关闭未合并）、R111、P1-8、P0-1

## 背景

`#2274`「对齐 src/* 到 main 并补 electron 命令路由（P2 B5 批次）」当时以
216 个文件的体量提交，后被关闭、分支保留。本轮先做归因，再决定补什么。

## 归因结果：216 个文件里 177 个早已一致

按路径逐一比对 blob sha（win7 tip vs `main`）：

| 结论 | 数量 |
|---|---|
| 已与 main 完全一致 | 177 |
| 仍有差异 | 35 |
| win7 缺失 | 1 |
| main 侧已删除 | 3 |

再对 35 个做「代码行 vs 注释行」拆解：

- **10 个只差注释或行尾符** —— 其中 3 个（`ProjectArchetypeStudio.tsx`、
  `TypeDetectionPreview.tsx`、`WorkspaceBranchPicker.tsx`）逐行完全相同、
  仅 CRLF/LF 不同。无功能含义，不动，避免无意义的大 diff。
- **24 个有真实代码差异**，但其中一批经核查**并不是功能缺口**：

### 被误判为缺口的（实际已实现，只是放的位置不同）

| 命令 | main 的位置 | win7 的位置 |
|---|---|---|
| `office_word_repair` | `commandRoutes/office.ts` | `commandRoutes/office.ts`（**同一文件已有**） |
| `usage_get_session` | `commandRoutes/settings.ts` | `commandRoutes/sessions.ts` |
| `permissions_session_auto_approvals` | `commandRoutes/settings.ts` | `commandRoutes/sessions.ts` |

`electron/ipc-manifest.json` 里三条全在，契约测试 T1「manifest 必须等于
COMMAND_ROUTES」一直是绿的 —— 这本身就是证据：命令都在，只是域文件划分不同。
**整取 main 的 settings.ts 会把 win7 的域划分打散，属于纯噪声，不做。**

同理：

- `ipc-manifest.json`：win7 比 main **多**一条 `agent_chat`（main 没有），
  其余只差排序。不能覆盖。
- `src/shared/api/types.ts`：win7 已把 753 行的巨石拆成 `types/` 目录
  （`types.ts` 只剩 58 行 barrel）。这是 win7 侧的合理结构，不能回退成单体。
- `src/shared/api/types/chatAndEventTypes.ts`：差异仅为注释措辞与联合类型
  成员顺序，语义等价。

## 本轮真正补的四项

### 1. R111：工具调用显示插件归属

`src/widgets/chat/Message.tsx` 在转录里给每个工具调用渲染
「插件：X」后缀，数据来自 `usePluginNames` 的模块级缓存。

win7 缺的是整个 hook 文件（`src/shared/lib/hooks/usePluginNames.ts`），
同时 `permissionInsights.findPluginToolOwner`、i18n 键
`permission.from_plugin`、`pluginClient.list()` **都已存在** ——
又是一个「底座齐了、最后一环没接」。

### 2. P1-8：账号删除改两步确认

`AccountTable.tsx` 的删除按钮由原生 `window.confirm` 换成项目内的
`TwoStepDelete`（首次点击进入 armed 态显示「确认删除?」，二次点击才删），
`Arena.tsx` / `ArenaAccounts.tsx` 两个页面同步去掉页层 `window.confirm`。

`TwoStepDelete.tsx` 在 win7 与 main **逐字相同**（diff 为 0），props
`onConfirm/label/armedLabel` 一致，可直接接。动机是不一致：项目内
`SessionItem`/`MemoryItem` 都已是两步确认，且原生弹窗无法展示待删账号的
email 供核对。

### 3. P0-1：记忆检索与删除的测试

`MemoryBrowser.tsx` 两边**同为 643 行且逐字相同**，搜索框
（`memory-search-input`）、`searchMemories`、`deleteMemory` 在 win7 都已接线。
缺的只有 109 行测试（防抖、语义检索调用、删除后刷新与 toast）。
纯补覆盖，不动产品代码 —— 也顺带证明这条链路在 win7 是好的。

### 4. WikiChat 源码面板测试的稳定性

500 个 checkbox 的断言由 `getAllByRole` 改成
`container.querySelectorAll('input[type="checkbox"]:checked')`，超时 15s → 20s。
`getAllByRole` 在大量节点上要算可访问性树，CI 上容易超时。win7 CI 更慢，
这条对 win7 更有价值。

## 未纳入（附理由）

| 项 | 理由 |
|---|---|
| `ShikiCodeBlock.tsx` 改 `createHighlighterCore` + 按语言懒加载 | 需要 `@shikijs/langs`、`@shikijs/themes` 两个新依赖与 lockfile 更新；本机无 npm，无法重算 `package-lock.json`，`npm ci` 会失败。留待有 npm 的环境单独做。 |
| `settings.ts` / `sessions.ts` 域划一 | 命令等价，改了只是搬家 |
| `types.ts` 回退成单体 | 逆着 win7 已有的模块化 |
| i18n 四份文案全量同步 | 双向都有 win7 独有键，全量覆盖有丢键风险；本轮新增代码所需的键已全部存在 |
| `CommandPalette.test.tsx` | win7 比 main **多** 160 行用例 |
| 纯注释 / 纯 CRLF 差异 | 无功能含义 |

## 验证

- 前端：`npm run typecheck`（`tsc --noEmit`）与 `vitest` 相关用例由 CI 执行。
  本机 `npm` 不可用、worktree 无 `node_modules`，无法本地预跑 —— 这是本轮
  的已知短板，CI 结果为准。
- 后端无改动。
