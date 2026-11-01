# 设置页信息架构整理（Settings IA Consolidation）

> P0–P3（2026-10-28 ~ 2026-10-29）。设置页从「19 个 tab 挤在 6 个手风琴分组里 +
> 三套重叠界面」重构为「单一 tab registry 派生 + 平铺分组 + 审计导出集中」。
> 同步文档：[用户手册 · 设置](../user-manual/20-settings.md)、
> [32 Settings Schema 规范化](./32-settings-canonicalization.md)（持久化层，本文只讲 IA）。

## 一、问题与目标

2026-09 的「设置治理 Phase 2」把 `GeneralTab` 拆成 `BasicTab` + `ToolsConnectionsTab`，
但**旧页面没有下线**，此后又新增 6 个 tab。重构前的事实：

| 问题 | 证据 |
|---|---|
| 三套重叠界面 | 主题/语言/权限模式/Hooks/网关 在 通用、基础、工具与连接 重复出现 |
| 「通用」是僵尸 tab | `initialSettingsTab('general')` 恒返回 `basic`，进去就再也回不来 |
| 导航靠手风琴 | 未选中分组的子项全部隐藏，19 个 tab 同屏最多见 6 个 |
| 元数据五处分散 | `Settings.tsx` / `settingsNavigation` / `settingsPresentation` / 搜索索引类型 / 索引条目各写一份，新增 tab 至少改 4 处 |
| 调试噪音 | 11 个 tab 内 17 处「复制摘要 / JSON」按钮；`SettingRow` 每行渲染 2 个 `sr-only` 可聚焦按钮（整页 100+ 隐藏 tab stop） |

本轮目标按优先级：**去重**（每个设置唯一入口）→ **降认知成本**（所有 tab 一屏可见）→
**单一事实源**（导航/搜索/分组/别名从 registry 派生）→ **降噪**（审计按钮集中、i18n 收口）。

非目标：不把 `settingsRegistry` 元数据自动生成为 UI（元数据条数远少于控件数，YAGNI）；
不做窄屏适配；不改后端 `app_settings` 存储结构。

## 二、目标信息架构

7 组 / 17 个 tab，左侧固定搜索框 + 平铺分组（分组标题是**不可点击的 section label**）：

| 分组 | 成员 |
|---|---|
| 基础 | 基础 |
| 模型与服务 | 模型与服务（页内子导航：端点 / 模型 / 参数与降级 / 更新源） |
| 智能体 | 编排、权限与工具、MCP、插件与技能、全局规则 |
| 记忆与知识 | 记忆、Zotero 文献库 |
| 网络与远程 | 网络、远程工作区 |
| 使用与维护 | 使用统计、更新 |
| 诊断与实验 | 运行环境与诊断、进化、Harness、审计导出 |

`general` 的 localStorage 历史值通过别名永久迁移到 `basic`（**只增不减**，见
`SETTINGS_TAB_ALIASES`），老用户不会落到空白页。

### GeneralTab 区块去向

P0 删除 `GeneralTab.tsx` 时逐项核对（漏一项 = 用户设置入口消失）：

| 原区块 | 去向 |
|---|---|
| 主题 / 语言 / 字体 / 流式 / 时区 / 托盘 / 演示 | 基础（删除 BasicTab 内的重复实现，演示模式取 GeneralTab 的健壮版 → `DemoModeSection.tsx`） |
| 对话记忆（自动记忆提取 / 确认删除 / 上下文轮次） | 记忆（`MemoryKnowledgeTab` 早已有此实现，直接删重复） |
| 超长文档检索注入 | 基础 → 高级折叠区（`AttachmentRagCard`） |
| 自动检查点、花费上限 | 记忆（同样早已存在） |
| 权限模式 + `PermissionRulesManager` | 权限与工具（补上 RulesManager） |
| 模型降级 | 模型与服务 → 参数与降级 |
| 数据重置 | 基础 → 数据（`ResetDefaultsSection`） |
| 用量（请求明细） | 使用统计（汇总/趋势与 `UsageStatsTab` 重复，只迁独有部分） |
| 日志卡片 / LLM 诊断预览 | 运行环境与诊断 |
| Arena 账号池开关 | 模型与服务 |
| 消息网关 ×3 | 权限与工具 →「消息网关」（原错标为「诊断」） |

## 三、单一 tab registry

`src/pages/settings/settingsTabs.tsx` 是导航/分组/别名/类型的唯一事实源：

```ts
export interface SettingsTabDef {
  key: SettingsTabKey;
  labelKey: TranslationKey;
  group: SettingsGroupId;
  render: () => JSX.Element;   // 必须返回元素，不能 `() => BasicTab()`
  visibleWhen?: () => boolean;
  aliases?: readonly string[];
}
```

派生关系：

| 消费方 | 派生方式 |
|---|---|
| `SettingsTabKey` | 由 `SETTINGS_TABS` 的 key 联合派生 |
| `settingsNavigation.initialSettingsTab` | 只剩「别名迁移 + 未知值回退 basic」 |
| `settingsPresentation.settingsGroups` | 分组顺序/组名/成员全部来自 `SETTINGS_GROUPS` + `SETTINGS_TABS` |
| `Settings.tsx` | 只负责搜索、锚点定位、渲染；`LEGACY_TAB_ALIASES` / `migrateTab` 已删除（迁移只剩一份） |
| `CommandPalette` | `import type` 引入 `SettingsTabKey`（编译期擦除），不把设置页拖进包 |

`providers` / `endpoints` / `models` / `plugins` / `skills` 不再是独立 tab，
`initialSettingsTab` 的 `providersEnabled` 形参随之删除。

**陷阱**：`render` 写成 `() => BasicTab()` 会在 render 期间直接调用组件函数、违反 hooks 规则，
必须写成 `() => <BasicTab />`。

## 四、搜索索引与守卫

保留 `SETTINGS_SEARCH_INDEX` 手写条目（重写 86 条收益有限），改用**测试守卫**防漂移。
`__tests__/settingsTabs.guards.test.ts` 断言：

1. 设置 `.tsx` 源码中每个字面量 `anchor="..."` 都在索引中有同名 `key`；
2. 每条索引的 `tab` 都是 `SETTINGS_TAB_KEYS` 成员；
3. 每个可见 tab 至少有一条搜索条目；
4. `SETTINGS_TABS.length === 17`。

守卫落地当场抓出 3 处历史漏登记：`orch.maxIterations`、`inputHistorySize`、
`harness`（整个 tab 无条目）。**新增设置项时**：给 `SettingRow` 加 `anchor` +
在索引登记一行（`keywords` 必须**全小写**，`settingsSearchIndex.test.ts` 会断言），
否则测试红。动态锚点（`anchor={variable}`）无法静态检测，不在守卫范围。

「开发模式缺 anchor 时 `console.warn`」未实现：动态锚点大量存在，逐行 warn 会变噪音。

## 五、降噪与可访问性

### 审计导出集中化

`AuditExportTab.tsx` 按来源分组列出既有 `formatXxxAuditSnapshot/Json` 导出，每行一个「复制」按钮；
删除 11 个 tab 文件里 17 处页面内复制按钮；删除 `SettingRow` 内两个 `sr-only` +
`tabIndex=0` 的隐藏审计按钮（键盘/读屏修复）。各 section 默认 `idle`，显式点击才采集
（避免打开设置页即全量抓数据）；「复制全部」只合并已就绪的 section，未就绪的跳过而不阻塞。
`audit*Governance()` 导出仅测试引用，本轮**不删**，只停止新增。

### 隐藏可聚焦元素

验收要求「无隐藏可聚焦元素」。`AdvancedSection` 用 `hidden={!open}`
（`display:none` ⇒ 内容不可聚焦）+ `aria-expanded` + `aria-controls`，不是 `opacity-0`。
P3 顺带修掉 `ThemeSelector` 自定义主题删除按钮：原为 `opacity-0` + hover 才可见，
键盘可达但看不见 → 补 `focus-visible:opacity-100`。

## 六、i18n 与保存反馈

- 文案落在独立字典 `locales/{zh,en}/settingsUi.ts`（约 450 key，zh/en 键集一致），
  由 `zh.ts` / `en.ts` 聚合；`en` 仍是 `Record<TranslationKey, string>`，tsc 保证补全。
- `t()` 无插值，统一 `.replace('{placeholder}', ...)`，两侧占位符逐字一致。
- 守卫 `__tests__/settingsI18n.cjk.test.ts` 剥掉注释与字符串字面量内容后，检查 JSX 裸文本、
  `placeholder|title|aria-label|alt|label|desc`、`toast.*` / `setError` / `new Error` 输出点；
  审计 formatter 与 `RemoteWorkspacesTab` 的 `L(zh, en)` 在豁免清单。
  **盲区**：嵌在 JSX 表达式里的三元/字符串字面量不会被扫到，需人工复核（P3 就是这样
  漏掉了 `AdvancedSection` 的「展开/收起」与 `ApplyModeBadge` 的「保存后：」）。
- 保存反馈：三处显式保存卡片中 `GlobalRulesTab` 原本已有 `isDirty` + 3 秒「已保存」，
  作为对照组；补齐 `AttachmentRagCard`（用「最近一次落盘配置」算 dirty，改回原值时提示消失）
  与 `EndpointsTab`（五字段逐项比对，切换端点前 `window.confirm`）。
- `as TranslationKey` 强转全部删除：`NetworkMode` / `SEARCH_ENGINES` 成员本就是字面量联合，
  模板字面量类型可直接推导合法 key。

## 七、高级项折叠与「恢复默认」

`settingsRegistry` 元数据通过工厂构建：`booleanSetting` / `enumSetting` 默认
`visibility: 'basic'`，`numberSetting` 默认 `advanced` + `applyMode: 'next-request'`，
`orchNumber` 默认 `advanced` + `next-run`。

**没有做全局自动折叠**：`orchNumber` 默认 advanced，一刀切会把编排 tab 几乎整页折进高级区。
实际做法是**把折叠边界显式化**——每处 `AdvancedSection` 内的行都必须能在 registry 查到
且 `visibility === 'advanced'`，由守卫钉住（`UpdatesTab` 的 6 个高级行据此补了 `anchor` +
搜索条目，并补齐 7 条缺失的 `orch.*` 元数据）。

`SettingRow` 新增可选 `value` / `onReset`：

```ts
export interface SettingRowProps {
  anchor?: string;
  value?: unknown;          // 当前值，用于与 registry 默认值比较
  onReset?: () => void;     // 提供才可能渲染「恢复默认」
  // ...
}
```

- 只有 `onReset && value !== undefined && metadata` 且值 ≠ `metadata.defaultValue` 时才渲染按钮；
- 比较先 `===`，再 `JSON.stringify`（registry 有对象型默认值），序列化失败保守视为「已修改」；
- 默认值**只**从 `getSettingMetadata(anchor).defaultValue` 取，调用点不重复硬编码；
- 守卫 `__tests__/settingsRegistryReset.p3.test.tsx`：按钮出现条件 / 点击回调 /
  编排 tab 每个字面量地址都有元数据 / 更新 tab 的 6 个地址全是 advanced。

## 八、搜索体验

- `Cmd/Ctrl+K` 走 `window` 级 keydown，命中后 `preventDefault` + `focus()` + `select()`；
  只认带 `meta/ctrl` 的组合（裸 `k` 不劫持，否则输入框打字会被抢焦点）；提示标签按
  `navigator.userAgent` 判平台，Windows/Linux 显示 `Ctrl+K`。
- 「最近访问」落在 `settingsRecents.ts`：`sage:settings-recent-tabs` 存 JSON 字符串数组，
  上限 3 条（`MAX_SETTINGS_RECENTS`），读取时用 `SETTINGS_TAB_KEYS` 过滤 —— 已下线 key
  （`general` / `memory-knowledge`）不会渲染成死按钮。当前 tab 从列表中剔除（下方已高亮），
  并按当前搜索词过滤。写入放在 `useEffect([recents])` 而非 state updater 内部，
  避免 StrictMode 双调用产生副作用。

## 九、验证

| 验收项 | 手段 |
|---|---|
| 同一偏好只出现一次 | P0 逐项核对表 + 迁移前后搜索条目数对比 |
| 刷新不落到不可持久化 tab | `initialSettingsTab` 单测覆盖别名迁移 |
| 新增 tab 只改 registry 1 处 | `settingsTabs.guards.test.ts`（tab 数、索引归属、anchor 覆盖） |
| 英文界面无硬编码中文 | `settingsI18n.cjk.test.ts` + 人工复核 JSX 表达式内文案 |
| 无隐藏可聚焦元素 | `AdvancedSection` 用 `hidden` 属性；自定义主题删除按钮补 `focus-visible` |
| 审计能力集中且可发现 | 审计导出 tab + 每个可见 tab 至少一条搜索条目 |

全量 `src/pages/settings` + `src/entities/setting` 共 86 个测试文件 512 条断言全绿；
`tsc --noEmit` 与 `eslint` 干净。

## 十、后续与已知边界

- `audit*Governance()`（26 个，仅测试引用）待单独清理；
- 动态锚点无静态守卫，新增动态行时需手动登记搜索条目；
- CJK 守卫不扫 JSX 表达式内字符串，仍有回潮风险；
- 设置页是热点文件（近 10 次提交中 6 次涉及），后续改动先 rebase main；
- 前端改动需 cherry-pick 到 `release/win7`，无 py38 适配，按分支各自跑
  architecture-baseline / coverage 门禁。
