# 项目模块 P2 计划——行内会话子列表 + 命令面板接入

> 日期: 2026-09-13 · 基线: main `e102f55e`（P1 #727 合入后）
> 分支: `feat/projects-p2` · 前置: P1（`docs/technical/61-projects-module.md`）

## 0. P1 回顾与 P2 定位

P1 把侧边栏"项目"占位落地为注册表：登记 / 打开（复用最近会话或新建并
绑定）/ 移除 / 目录缺失标记。P1 技术文档 §8 列了四个 P2 候选，本计划按
"证据支撑 + 低风险 + win7 对齐成本"裁剪为两项落地、两项缓行。

## 1. 落地项

### 1.1 项目行展开会话子列表（ProjectSection）

- 行左侧加 chevron 展开开关（stopPropagation，不触发行点击=打开项目）；
- 展开时懒加载 `projectApi.listSessions(id)`（P1 端点已就绪，≤20 条）；
- 子行**轻量自绘**（title + 相对时间 + 消息数），不复用 `SessionItem`——
  它订阅 5 个 store（chatStream/artifact/permission/question/scheduled）
  并带导出/置顶/重命名/TwoStepDelete 全套操作，嵌套场景过重；
- 子行点击 → `onOpenSession(sessionId)`（Sidebar 统一入口）；
- 项目 open/createSession 成功后若该行处于展开态则刷新子列表；
- 空子列表显示"项目内暂无会话"。

### 1.2 命令面板接入（CommandPalette + commandItems）

- 新增 **"项目"分组**：面板打开时 `projectApi.list()` 取前 8 个，条目
  显示 name + path，回车 → `projectApi.open(id)` → `loadSessions()` →
  复用面板既有 `handleOpenSession(session.id)`（setCurrent + navigate +
  关面板）；410/失败静默降级为 toast 不打断面板；
- `commandItems.ts` 新增 `add-project` ActionCommand（FolderPlus）：
  selectDirectory → register → open → 进入新会话；
- 把键盘 ⌘ 数字路径与 onSelect 路径重复的 `if (cmd.id === ...)`
  **收敛为单一 `runAction(id)`**（行为不变，消除双点维护）；
- 文案沿用该文件既有硬编码中文惯例（CommandPalette 全文件未接 i18n，
  单独为两个词引 i18n 反而制造分裂）。

## 2. 缓行项（证据记录）

| 候选 | 结论 | 依据 |
| --- | --- | --- |
| 拖拽文件夹登记 | 缓行 | 应用无全局 drop 面：electron/main.ts 仅有 `will-navigate` 防护；聊天附件 drop 只拿 `File` 对象无路径；唯一可行先例是 OfficeFilePicker 的 `(file as {path?}).path`（Electron 专属），但侧栏引入 drop 区需处理拖拽高亮/多点嵌套/拒绝 web 拖放，收益低于风险 |
| wiki recent_projects 迁移统一 | 缓行（长期） | `recent_projects` 不是 UI 历史：它喂 `wiki/project_authorization` 安全白名单、`search_routes` 搜索范围默认值与 MCP 列表；存储走 POSIX-only `secure_*` 原语（Windows 上测试 skip，属于已记录缺口）；与 projects 注册表语义不同（自动记录 vs 用户显式登记、无 id/会话归属）。迁移必须先在 SQLite 上复刻授权语义，属独立批次 |

## 3. 改动面

| 文件 | 改动 |
| --- | --- |
| `src/widgets/sidebar/sections/ProjectSection.tsx` | 展开态 + 子列表渲染 |
| `src/widgets/command/commandItems.ts` | +1 ActionCommand |
| `src/widgets/command/CommandPalette.tsx` | 项目分组 + runAction 收敛 + add-project |
| `src/widgets/sidebar/sections/ProjectSection.test.tsx` | +展开/子行/空态用例 |
| `src/widgets/command/CommandPalette.test.tsx` | +项目分组/添加项目用例 |
| `CHANGELOG.md` | Added(projects) 追加 P2 条目 |
| `docs/technical/61-projects-module.md` | 追加 P2 小节 |

**后端零改动**（P1 端点全覆盖）；Electron commands 零改动。

## 4. main ↔ win7 对齐

- ProjectSection / 其测试为 P1 新文件，win7 cherry-pick 时随 P1 一起走；
- **CommandPalette.tsx 在 win7 分支分歧大（-237 行）**：P2 对该文件的
  改动按 main 结构走，cherry-pick 到 win7 需人工适配（分组插入与
  runAction 收敛都是局部小改，可跟随其本地结构重放）；commandItems.ts
  为纯追加，低风险；
- 无新依赖、无后端/IPC 变更，Python 侧零接触。

## 5. 验收

1. `npm run typecheck` 干净；改动文件 eslint/prettier 全过；
2. `ProjectSection.test.tsx` / `CommandPalette.test.tsx` 全绿；
3. 全量前端套件不新增失败（基线：updateManager/officePaths/officeIpc
   三个 Windows 环境存量失败文件）；
4. 后端 pytest 不涉及（零后端改动），ruff 不涉及。

## 6. 后续（P3 候选，非本批）

- 拖拽文件夹登记（独立批次，复用 OfficeFilePicker 模式 + 侧栏 drop 区）；
- 项目分组拖拽排序（对齐会话列表 dnd-kit 模式）；
- wiki recent_projects SQLite 化统一（先移植授权语义）。
