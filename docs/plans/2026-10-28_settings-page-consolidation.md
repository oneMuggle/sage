# 设置页信息架构整理（Settings IA Consolidation）

- 日期：2026-10-28
- 状态：实施中（P0 / P1 / P2 已完成，P3 待做）
- 范围：`src/pages/settings/` 及其导航 / 搜索索引 / 相关测试；不涉及后端接口

## 1. 背景与目标

设置页在 2026-09 的「设置治理 Phase 2」中做过一次拆分（GeneralTab → BasicTab +
ToolsConnectionsTab），但**旧页面没有删除**，此后又陆续新增了 6 个 tab。当前结果：

- 19 个 tab 挤在 6 个手风琴分组里，组标题同时承担「导航」和「展开」两种语义；
- 三套设置界面重复渲染同一批偏好项，「通用」「基础」「工具与连接」互相重叠；
- tab 元数据分散在 5 个地方，新增一个 tab 要同步改 5 处，且已经出现漂移。

目标：

1. **消除重复**：每个设置只有唯一入口，不存在两处可改同一偏好；
2. **降低认知成本**：所有 tab 一屏可见（分组标签平铺），不再靠手风琴隐藏；
3. **单一事实源**：导航 / 搜索 / 分组 / 别名从一个 tab registry 派生；
4. **降噪**：审计调试按钮、隐藏的可聚焦元素、硬编码文案集中清理。

非目标（本轮不做）：

- 不把 `settingsRegistry` 元数据自动生成为设置 UI（元数据只有 25 条，实际控件远超此数，
  先补齐元数据再谈生成，属 YAGNI）；
- 不做移动端/窄屏适配（桌面应用，导航固定 208px 可接受）；
- 不改后端 `app_settings` / preference 存储结构。

## 2. 现状盘点（证据）

### 2.1 三套重叠界面

| 设置区块 | GeneralTab（通用） | BasicTab（基础） | ToolsConnectionsTab（工具与连接） |
|---|---|---|---|
| 主题 / 语言 / 字体 / 托盘 / 时区 / 演示模式 | ✅ | ✅ | — |
| 权限模式 | ✅（含 PermissionRulesManager） | — | ✅（含 TrustEscalation，缺 RulesManager） |
| 模型降级 | ✅ | — | ✅ |
| 钩子 Hooks | ✅ | — | ✅ |
| 消息网关（Telegram/Discord/Slack） | ✅（错误地标为「诊断」） | — | ✅（同样标为「诊断」） |
| 用量 / 费用上限 | ✅ | — | — |
| 数据重置 | ✅ | — | — |
| 自动检查点 / 附件检索注入 / Arena 账号 | ✅ | — | — |

说明：`GeneralTab.tsx`（772 行）注释仍写着「通用设置 Tab」，`BasicTab.tsx` /
`ToolsConnectionsTab.tsx` 注释写着「从原 GeneralTab 拆分而来」——拆分后旧文件未下线。

### 2.2 「通用」是僵尸 tab

`settingsNavigation.ts` 的 `initialSettingsTab('general')` 返回 `'basic'`，`Settings.tsx`
的 `LEGACY_TAB_ALIASES` 同样把 `general → basic`。也就是说：

- 点击分组标题「基础与外观」会跳到 `group.keys[0]`，即 **通用**；
- 但在通用页做的任何导航状态，刷新后都被迁移到 **基础**，用户永远回不到通用；
- 通用页却是当前内容最全的一页（15+ 区块），也是搜索索引里唯一映射到 `general` 的条目
  所在（`tab: 'general'` 仅 1 条）。

### 2.3 导航分组错位

`settingsPresentation.ts` 的 6 个分组：

- 「基础与外观」= 通用 + 基础（两个近义 tab，且首项是僵尸页）；
- 「工具与安全」塞了 7 个 tab：工具与连接、MCP、插件、编排、进化、技能、全局规则；
- 「记忆与资料」含文献库（Zotero），但真正的知识库入口在 `/memory` 页；
- 「诊断、用量与更新」里的「更新源」与「更新」两个 tab 名称极易混淆；
- 展开逻辑是 `selected || query` 才显示子项，未选中的分组子项全部不可见——19 个 tab
  实际同屏最多看到 6 个。

### 2.4 元数据五处分散

| 位置 | 内容 |
|---|---|
| `Settings.tsx` 的 `tabs` 数组 | tab key + label |
| `settingsNavigation.ts` 的 `visibleTabs` | 合法 tab 列表 + 迁移别名 |
| `settingsPresentation.ts` 的 `GROUPS` | 分组 + 中英文组名（含已下线的 `memory-knowledge`） |
| `settingsSearchIndex.ts` 的 `SettingsTabKey` | tab key 联合类型 |
| `settingsSearchIndex.ts` 的 `SETTINGS_SEARCH_INDEX` | 86 条手写搜索条目 |

新增 tab 需要至少改 4 处；新增设置项需要手写搜索条目并记得给 `SettingRow` 加
`anchor`，否则搜索要么找不到、要么只能退回「按标签文本兜底定位」。

### 2.5 调试噪音与可访问性问题

- 14 个 tab 文件里有 21 处可见的「复制摘要 / JSON」审计按钮；
- 共享组件 `SettingRow` 对**每一行**渲染两个 `sr-only`、`tabIndex=0`、`role=status`
  的隐藏「快照 / JSON」按钮——全页 100+ 个隐藏 tab stop，键盘用户与读屏用户会撞上
  看不见的可交互元素；
- 26 个 `audit*Governance()` 导出仅被测试引用，属于 R 阶段治理脚手架。

### 2.6 国际化与保存反馈

- 52 处硬编码中文 `<h3>`，12 处 `as TranslationKey` 强转（说明 key 未进类型联合）；
- 大多数行是即时保存，但附件检索、端点、全局规则是显式「保存」按钮，且缺少统一
  的「已保存 / 保存失败」反馈。

### 2.7 规模数字

- `src/pages/settings/` 32 个 tsx + 10 个 ts，共 13.3k 行；`__tests__` 59 个文件 7.6k 行；
- `settingsSearchIndex.ts` 729 行 / 86 条；`settingsRegistry.ts` 25 条元数据。

## 3. 目标信息架构

### 3.1 导航形态

- 左侧固定搜索框 + **平铺分组列表**：分组标题是小号、不可点击的 section label，
  所有子项常显，不再手风琴；
- `Cmd/Ctrl+K` 聚焦搜索；搜索结果保留「tab 名 + 设置项」两级展示；
- 保留 `sage:settings-tab` 的记忆，但别名只增不减（`general → basic` 永久保留）。

### 3.2 目标 tab（7 组 / 15–17 项）

| 分组 | tab | 来源 |
|---|---|---|
| 基础 | **基础** | 通用 + 基础合并；按「外观与语言 / 对话行为 / 启动与托盘 / 时间 / 高级 / 数据」分节 |
| 模型与服务 | **模型与服务** | 端点 + 模型合并，页内子导航：端点 / 模型选择 / 参数与降级 / 更新源 |
| 智能体 | 编排 | 不变 |
| 智能体 | **权限与工具** | 原「工具与连接」：权限模式 + 规则管理 + 信任升级 + Hooks + 消息网关（修正「诊断」错误标签） |
| 智能体 | MCP | 不变 |
| 智能体 | **插件与技能** | 插件 + 技能合并 |
| 智能体 | 全局规则 | 不变 |
| 记忆与知识 | 记忆 | 不变（内部已有两段） |
| 记忆与知识 | 文献库 | 不变 |
| 网络与远程 | 网络与凭据 | 不变 |
| 网络与远程 | 远程工作区 | 不变 |
| 使用与维护 | 使用统计 | 并入「费用上限」 |
| 使用与维护 | 更新 | 并入「更新源」 |
| 诊断与实验 | 运行环境与诊断 | 原「开发环境」：本机运行时 / 项目诊断 / 试跑 / 日志 |
| 诊断与实验 | 进化 | 不变（或与 Harness 合并为「实验特性」，二选一） |
| 诊断与实验 | Harness | 同上 |
| 诊断与实验 | **审计导出（新）** | 收纳全部「复制摘要 / JSON」按钮 |

合并后可选项：进化 + Harness 合并为「实验特性」可再减 1 项；端点/模型若嫌 tab 内
容过长（合计约 900 行），可先只做去重、合并延后到 P1 之后。

### 3.3 GeneralTab 区块去向（P0 必做，逐项核对，不能丢设置）

| GeneralTab 原区块 | 去向 |
|---|---|
| 主题 / 语言 / 外观（字体+流式） / 时区+日志时区 / 托盘 / 演示 | 基础（BasicTab 已有，删除重复实现） |
| 对话：自动记忆提取、确认删除、上下文轮次上限 | 记忆 → 顶部「对话记忆」小节 |
| 超长文档检索注入（实验） | 基础 →「高级」折叠区 |
| 自动检查点（AutoCheckpointCard） | 权限与工具 →「安全网 / 检查点」 |
| 权限模式 + PermissionRulesManager | 权限与工具（补上 RulesManager，删除重复的 PermissionModeSelector） |
| 模型降级 FallbackModelInput | 模型与服务 →「参数与降级」 |
| 数据重置 ResetDefaultsSection | 基础 →「数据」 |
| 钩子 HooksCard | 权限与工具（已有，删重复） |
| 用量与费用上限 SpendLimitInput + UsagePanel | 使用统计 |
| 诊断 DiagnosticsCard（日志） | 运行环境与诊断 |
| 消息网关 GatewayCard ×3 | 权限与工具 →「消息网关」（重命名，不是诊断） |
| 高级：DiagnosticCard + ArenaAccountsToggle | DiagnosticCard → 运行环境与诊断；Arena → 模型与服务 |
| 各区块「复制摘要 / JSON」 | 审计导出 tab（去掉页面内按钮） |

## 4. 技术方案

### 4.1 单一 tab registry（P2 核心）

新建 `src/pages/settings/settingsTabs.tsx`：

```ts
export type SettingsTabKey = /* 联合类型，由 registry 的 key 派生 */;

export interface SettingsTabDef {
  key: SettingsTabKey;
  labelKey: TranslationKey;
  group: 'core' | 'models' | 'agent' | 'knowledge' | 'network' | 'maintenance' | 'advanced';
  render: () => JSX.Element;
  visibleWhen?: () => boolean;      // providers 开关等
  aliases?: readonly string[];      // 历史 localStorage 值
}

export const SETTINGS_TABS: readonly SettingsTabDef[] = [ ... ];
```

- `Settings.tsx` 只负责搜索、锚点定位、渲染，导航与内容都从 registry 派生；
- `settingsNavigation.ts` 的 `visibleTabs` / 别名从 registry 生成；
- `settingsPresentation.ts` 的分组顺序与组名从 registry 的 `group` 生成；
- `SettingsTabKey` 从 registry 派生，搜索索引的 `tab` 字段直接引用它；
- `EndpointsTab` / `ModelsTab` 改为内部调用 `useSettings()`（已是全局 zustand store），
  去掉 props 透传，registry 的 `render` 才能统一。

### 4.2 搜索索引防漂移

不重写 86 条手写索引（工作量大且收益有限），改为**加守卫**：

1. 单测扫描 `src/pages/settings/*.tsx` 的 `anchor="..."`，断言每个 anchor 都在
   `SETTINGS_SEARCH_INDEX` 中有对应 `key`；
2. 单测断言每条索引的 `tab` 都是 registry 中的 key；
3. 单测断言每个可见 tab 至少有一条搜索条目；
4. 可选：开发模式下 `SettingRow` 缺 anchor 时 `console.warn`（仅 dev）。

### 4.3 审计导出集中化

- 新增 `AuditExportTab`：按 tab 分组列出已有的 `formatXxxAuditSnapshot/Json` 导出，
  每行一个「复制」按钮；
- 删除各 tab 内的复制按钮；
- 删除 `SettingRow` 内的 `sr-only` 审计按钮（a11y 修复，此项可提前到 P0）。

### 4.4 保存反馈与高级项

- 统一走「即时保存 + 行内轻提示」；显式保存的卡片（附件检索、端点、全局规则）
  保留按钮，但补 dirty 状态与离开提示；
- 用 `settingsRegistry.visibility` 把 `advanced` 项默认折叠到 `<AdvancedSection>`；
  实施前先补齐 registry 元数据（25 → 覆盖所有可搜索项），否则只对已有条目生效；
- 每行支持「已修改 / 恢复默认」，数据来自 registry 的 `defaultValue`。

### 4.5 i18n 清理

- 52 处硬编码 `<h3>` 全部改为 `t('settings.section.*')`；
- 12 处 `as TranslationKey` 补 key 到类型联合后去掉强转；
- 增加守卫测试：settings 目录下 JSX 文本不得出现 CJK（注释除外），防止回潮
  （参考 `fontScaleGate` 的既有做法）。

## 5. 实施步骤（分阶段，每阶段独立可验证）

### P0 — 去重止血（1 PR，风险最低，先做）

- [x] 删除 `GeneralTab.tsx` 与 `general` tab；按 §3.3 表格迁移 13 个独占区块
- [x] 从 `settingsPresentation.GROUPS` 移除 `general`；`LEGACY_TAB_ALIASES` 保留 `general → basic`
- [x] 搜索索引中 `tab: 'general'` 的条目改指向新归属（`reset_settings → basic`）
- [x] 「诊断」区块重命名为「消息网关」（ToolsConnectionsTab）
- [x] 删除 `SettingRow` 中隐藏的审计按钮（键盘 / 读屏修复）
- [x] 更新受影响的测试（`BasicTab` / `ToolsConnectionsTab` / `Settings.anchor` / `settingsNavigation`）
- [x] 验收：同一偏好只出现一次；刷新后不会落到不可持久化的 tab；全量前端测试绿

实施备注（P0 落地时发现）：

- `autoMemory` / `confirmDelete` / `auto_checkpoint` / `spend_limit_usd` 在
  `MemoryKnowledgeTab` 中早已有实现，GeneralTab 里的同名区块是纯重复，直接删除，无需迁移。
- `UsagePanel` 的汇总/趋势与 `UsageStatsTab` 重复，只把独有的「请求明细」
  （`UsageRequestsTable`）迁入使用统计；`UsagePanel` 暂时保留为组件（仍有独立测试）。
- 演示模式采用 GeneralTab 的健壮版本（IPC 失败回滚 + 错误提示），拆为
  `DemoModeSection.tsx` 替换 BasicTab 里较简单的内联开关。
- 通用页的「超长文档检索注入」「恢复默认设置」拆为独立组件文件，挂到 BasicTab。
- 日志卡片（`DiagnosticsCard`）与 LLM 诊断预览（`DiagnosticCard`）挂到运行时/诊断 tab；
  Arena 账号池开关挂到「模型」tab。

### P1 — 导航与合并（1 PR）

- [x] 导航改为平铺分组（分组标题不可点击），去掉手风琴展开逻辑（P1-a）
- [x] 合并：插件 + 技能；端点 + 模型 + 更新源（页内子导航）（P1-b）
- [x] 重命名：开发环境 → 运行环境与诊断；工具与连接 → 权限与工具（P1-a）
- [x] 更新 `settingsSearchIndex` 的 tab 归属与关键词（P1-b）
- [x] 同步 `docs/user-manual/20-settings.md` 的章节结构
- [x] 验收：任意 tab 1 次点击可达；分组标签与内容一致；搜索命中率不降

### P2 — 单一数据源（1–2 PR）

- [x] 新建 `settingsTabs.tsx` registry，派生导航 / 分组 / 别名 / 类型
- [x] `EndpointsTab` / `ModelsTab` 改用 `useSettings()`（P1-b 合并后已被 `ModelsServicesTab`
      取代 —— 注册表渲染的是合并后的 tab，内部的 props 透传保留给既有组件测试）
- [x] 搜索索引守卫测试（§4.2 四条）
- [x] 验收：新增 tab 只改 registry 1 处；新增设置项漏登记搜索时测试失败

实施备注（P2 落地时发现）：

- 注册表落在 `settingsTabs.tsx`（`.tsx` 而非 `.ts`），因为 `render` 要返回 JSX。
  `render` 必须返回**元素**（`() => <BasicTab />`），不能是 `() => BasicTab()` ——
  后者在 render 期间直接调用组件函数，违反 hooks 规则。
- `settingsSearchIndex.ts` 用 `import type` 引入 `SettingsTabKey`（编译期擦除），
  因此 `CommandPalette` 不会因为注册表把整个设置页拖进它的 chunk。
- `settingsNavigation.ts` / `settingsPresentation.ts` 改为从注册表派生：
  `initialSettingsTab` 只剩「别名迁移 + 未知值回退 basic」；
  `settingsGroups` 的分组顺序/组名/成员全部来自 `SETTINGS_GROUPS` + `SETTINGS_TABS`。
  `Settings.tsx` 里的 `LEGACY_TAB_ALIASES` / `migrateTab` 已删除（迁移逻辑只剩一份）。
- `providers` / `endpoints` / `models` / `plugins` / `skills` 不再是独立 tab，
  `initialSettingsTab` 的 `providersEnabled` 形参随之删除。
- 守卫测试（`__tests__/settingsTabs.guards.test.ts`）落地 3 条自动化断言：
  源码里的 `anchor="..."` 字面量必须已登记搜索索引、索引条目的 `tab` 必须是注册表
  key、每个可见 tab 至少有一条搜索条目。守卫当场抓出 3 处历史漏登记：
  `orch.maxIterations`、`inputHistorySize`、`harness`（整个 tab 无搜索条目）。
- §4.2 第 4 条（开发模式 `console.warn` 提示缺 anchor）**未做**：动态锚点
  （`anchor={variable}`）大量存在，逐行 warn 会变成噪音；静态守卫已覆盖
  可静态检测的那部分。

### P3 — 体验与降噪（1–2 PR）

- [ ] 新增「审计导出」tab，移除 21 处页面内复制按钮
- [ ] i18n 清理 + CJK 守卫测试
- [ ] 保存反馈统一；显式保存卡片补 dirty 提示
- [ ] `Cmd/Ctrl+K` 聚焦搜索；最近访问排序
- [ ] 补齐 `settingsRegistry` 元数据，按 `visibility` 折叠高级项；每行「恢复默认」
- [ ] 验收：英文界面无硬编码中文；无隐藏可聚焦元素；审计能力集中且可发现

## 6. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| GeneralTab 独占设置迁移遗漏 | 用户设置入口消失 | §3.3 逐项核对清单 + 迁移前后搜索条目数对比测试 |
| 59 个测试文件、7.6k 行断言依赖现有 tab key / 文案 | P0/P1 会大面积红 | 每阶段同 PR 内更新测试；先跑 `npm test` 基线 |
| 重命名 localStorage tab key | 老用户落到空白页 | 只加别名，不改 key；`initialSettingsTab` 单测覆盖 |
| 设置页是热点文件（近 10 次提交中 6 次涉及） | 与进行中的分支冲突 | 开独立 worktree；先 rebase main；P0/P1 分 PR 降低冲突面 |
| win7 分支同步 | 前端改动需 cherry-pick | 无 py38 适配；按分支各自跑 architecture-baseline / coverage 门禁 |
| 删除 `audit*Governance` 会动 26 个测试 | 范围外风险 | 本轮**不删**，只停止新增；后续单独清理 |
| `settingsRegistry` 元数据不完整 | 自动折叠 / 恢复默认只覆盖部分项 | P3 先补齐再启用；未覆盖项保持现状 |

## 7. 建议先行项

P0 收益最大、风险最小：删除僵尸「通用」tab + 消除三套重复界面 + 修复 SettingRow
隐藏可聚焦元素。建议先评审 P0 的范围与 §3.3 迁移表，确认后再决定 P1 的合并粒度
（尤其是端点/模型是否合并、进化/Harness 是否合并）。
