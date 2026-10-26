# R109 已保存权限规则遮蔽标注规格

- 日期：2026-10-26
- 基线：`main` `6b68010246a806bfad7d0fefa6fce53e6884130e`
- 状态：已开 PR（#2557），待合并
- 编号说明：R109 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：后端裁决对用户规则恒按全局 **deny > allow >
  ask**（`backend/tools/permissions.py` 文件头与
  `_match_rules`），记住新规则时「decision 照常追加，
  冲突仍由 enforcer 的 deny > allow > ask」化解
  （`permission_routes.py` 注）。于是完全可能出现：
  用户先「整插件拒绝」后又单独「放行某个工具」（或反
  之），低优先级那条从此恒不胜出——但设置页管理器里
  两行并列、毫无提示，用户无从理解「明明放行了为什么
  还是被拒」。R101 补了规则的**归属**可见性，本轮补
  **生效性**可见性。

## 1. 目标与语义

- `PermissionRulesManager` 对已加载的规则列表做纯前
  端只读派生：某条规则若被同列表内另一条**更高优先
  级**规则（deny > allow > ask）覆盖，行内显示「被
  遮蔽」徽标（`data-testid="permission-rule-shadowed-<index>"`），
  title 指出覆盖它的 pattern 与优先级说明。
- 覆盖判定只认严格可证的三类（覆盖方 pattern 记为
  D、被标方记为 R）：① D 与 R 的 `tool_pattern` 等
  值；② D 为 `plugin__*` 且 R 带权威 `plugin_name`
  标注（R101）；③ D 为由 R 的 `plugin_name` 结构化
  派生的 `plugin__<name>__*`（与 R107 前端派生同口
  径，只做等值比对、不切分 R 的 pattern 猜名）。
- 保守取向（sound but incomplete）：一般 fnmatch 包
  含关系不判（如 `file_*` deny 不标注遮蔽
  `file_write` allow）；无 `plugin_name` 标注的规则
  只判等值。所示标注恒为真的遮蔽、永不误报，至多漏
  标。会话规则（R105）亦参与合并裁决、也能成为遮
  蔽源，但持久 deny 的遮蔽结论不因此失效，故本轮只
  在持久列表内派生是诚实的子集。

## 2. 边界

- 只读派生、永不落盘：不改存储、后端求值与任何写
  面；无新端点/Electron 命令（manifest 仍 274）。
- 身份边界不变：插件归属只用后端标注的权威
  `plugin_name`；风险更高的一般遮蔽（需要运行时身
  份语义）不猜。删除仍由用户逐条/按既有入口决定，
  本轮不加「清掉被遮蔽的」批量写面。
- 管理器为 i18n 文件，新增文案键
  `settings.permission.rules.shadowed(_title)`
  （zh 源 + en 镜像）。Win7 按既有口径待对齐（本
  轮无后端新代码）。

## 3. 实现要点

- `src/pages/settings/PermissionRulesManager.tsx`：
  新增导出纯函数 `findShadowedRules(rules)` 返回
  `Map<index, 覆盖方 pattern>`；行渲染按 map 显示
  徽标（与 R101 插件状态徽标同族），文案模板
  `{pattern}` 以 `.replace` 代入（宿主惯例）。
- `src/shared/lib/i18n/locales/{zh,en}/settingsAndModels.ts`：
  rules 命名空间新增两键。

## 4. 测试计划

- 纯函数：等值 allow 被 deny 遮蔽（deny 自身不
  标）；整插件通配 deny 遮蔽同插件精确 allow；
  `plugin__*` deny 遮蔽任意已标注插件 allow；ask
  被等值 allow 遮蔽；反例（精确 deny 不整行遮蔽
  通配 allow、一般 fnmatch 前缀不判、无标注时通
  配类不触发）。
- 组件：冲突列表渲染出徽标且 title 带覆盖
  pattern；无冲突列表无徽标（既有 GeneralTab 套
  件保持绿）。

## 5. 本地证据

- 前端：新增 8 例（纯函数 6：等值/整插件通配/全
  局通配/ask 优先级泛化 + 两组反例与保守性；组件
  2：徽标与 title/无冲突不渲染）；定向
  GeneralTab 既有管理器回归 29 例与相邻回归
  （permissionApi/i18n 含键一致性/PluginsTab）
  16 文件 64 例通过。
- 通用：tsc、ESLint（改动文件 0 问题）、
  architecture（管理器 321 行）、diff-check、
  diagnostics（0）全绿；无新 Electron 命令
  （`ipc:manifest:check` 仍 274——基线含他人
  #2548 增至 274，本轮不变），后端零改动。
- PR：#2557（2026-10-26 开，CI 结论以 GitHub 为准）。
