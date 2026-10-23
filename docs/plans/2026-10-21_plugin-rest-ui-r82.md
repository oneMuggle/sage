# R82：插件 REST + 设置页插件面板

> 账本：`docs/plans/plugin-evo-index.md` R82。路线图原文：插件 UI + REST
> （列表/启停/配置/权限确认/日志面板）；回滚 = 面板隐藏。

## 1. 现状盘点（带证据）

| 事项 | 现状 | 证据 |
| --- | --- | --- |
| 插件后端 | **完整但未接线**：manifest 模式 + 生命周期（install/enable/disable/uninstall/restore/update_config，SQLite 持久化）+ 能力注册表，共 1292 行 | `backend/plugins/{manifest,lifecycle,registry}.py` |
| 生产引用 | **零**：`get_lifecycle_manager` 仅被自身单测引用 | grep 仅命中 `tests/unit/test_plugin_lifecycle.py` |
| REST | 无插件路由；既有形态是 FastAPI `APIRouter` 在 `main.py` 以 `/api/v1` 前缀挂载 | `backend/api/hooks_routes.py`、`main.py:1075-1133` |
| 持久化缺口 | `PluginRecord` 不存 manifest 本体 → 装完就看不到权限/能力；也无事件日志 | `lifecycle.py` 表结构仅 10 列，无 `plugin_events` |
| 前端 | 设置页是 tab 结构（`SettingsTabKey` 联合 + tabs 数组 + 条件渲染）；数据走通用 `backendRequest` IPC 中继，新增页面**不需要改 Electron 主进程** | `src/pages/settings/{Settings.tsx,settingsSearchIndex.ts}`、`src/shared/api/backendRequest.ts` |
| 测试形态 | 后端路由测试用全 app 异步 `client` fixture（自动换 tmp DB）；前端用 vitest | `backend/tests/{conftest.py,api/test_hooks_routes.py}` |

结论：R82 不是从零造插件系统，而是把**已存在但悬空**的生命周期管理器
接上 REST 与 UI，并补上权限确认与日志两个缺失环节。插件代码的实际
加载/托管属于 R83（进程外宿主），本轮不冒充。

## 2. 设计与落点

### 2.1 后端补强（`backend/plugins/lifecycle.py`，纯增量）

- `plugins` 表新增 `manifest TEXT` 列：`_ensure_schema` 里用
  `PRAGMA table_info` 检测后 `ALTER TABLE`——旧 DB 无痛迁移，旧记录 `manifest={}`。
- 新增 `plugin_events` 表（id / plugin_name / event / detail / created_at）：
  install/enable/disable/uninstall/restore/update_config 成功后各落一条；
  事件是审计旁路，写入失败只 warning，不让主操作回滚。
- `PluginRecord` 增加 `manifest` 字段；新增 `PluginEvent` 模型与
  `list_events(plugin_name=None, limit=100)`。既有签名与单测不变。

### 2.2 REST（`backend/api/plugin_routes.py`，挂 `/api/v1/plugins`）

| 端点 | 语义 |
| --- | --- |
| `GET /plugins?status=` | 列表（含 display_name、权限汇总） |
| `GET /plugins/logs?limit=` | 全局事件（声明在 `/{name}` 之前避免吞路由） |
| `GET /plugins/{name}` | 详情（record + manifest + 按能力分组的权限） |
| `GET /plugins/{name}/permissions` | 仅返回扁平权限与能力分组 |
| `POST /plugins` | 安装 `{manifest, install_path, confirm_permissions}` |
| `POST /plugins/{name}/enable` / `/disable` / `/restore` | 状态迁移 |
| `DELETE /plugins/{name}` | 卸载（软删，与既有语义一致） |
| `PATCH /plugins/{name}/config` | `{config}` 全量替换 |
| `GET /plugins/{name}/logs?limit=` | 单插件事件 |

- **权限确认由后端强制**：manifest 任一 capability 声明了 permissions 且
  `confirm_permissions != true` → `409 {error: "permissions_confirmation_required", permissions: [...], by_capability: [...]}`，不落库。
  UI 只是展示层，绕过 UI 直接调 API 同样被拦。
- 错误映射：未找到 404、状态冲突/重复安装 409、manifest 非法或状态过滤非法 422。
- 全部插件端点先过既有 `forbidden_origin_response(request)` Origin 守卫，避免第三方网页 drive-by 调用。
- 每请求构造新 `PluginLifecycleManager()`（不走模块单例，避免连接跨 DB 残留）。

### 2.3 前端（设置页新 tab）

- `src/shared/api/pluginClient.ts`：类型 + `backendRequest` 封装；
  `describePermission(perm)` 把 `file:read` 这类串按界面 locale 译成人话（未知项回退原文）。
  Electron relay 对非 2xx 只抛带原始 JSON body 的普通 Error，客户端会把
  409 载荷还原为 `PluginPermissionConfirmationRequiredError`。
- `src/pages/settings/PluginsTab.tsx`：列表 + 状态徽标、启停/卸载/恢复、
  详情展开（能力与权限）、日志时间线、安装表单（manifest JSON + 路径）；
  表单会先从 manifest 预检权限；如果仍收到后端 409，则按后端权威载荷
  展开**权限确认区**，按能力列出权限的人话说明，用户勾选后才可带
  `confirm_permissions: true` 重提。
- 注册：`SettingsTabKey`、搜索索引、`settingsNavigation` 的可见 tab、
  `settingsPresentation` 的“工具与安全”分组与 `Settings.tsx` tabs/渲染分支；
  zh/en 各加 `settings.tab.plugins` 一键。面板正文按现有 locale 切换中英文，
  不新造第二套 i18n 体系。

## 3. 验收矩阵

| 主张 | 证据形式 |
| --- | --- |
| 生命周期经 REST 全程可达 | `tests/api/test_plugin_routes.py`：install→enable→disable→config→uninstall→restore 全链 + 404/409/422 |
| 权限确认不可绕过 | 同上：无 confirm 安装含权限 manifest → 409 且 `GET` 仍 404；带 confirm → 201 |
| manifest 与日志可回看 | install 后 detail 带 manifest 与分组权限；logs 顺序含 installed/enabled/... |
| 旧 DB 兼容 | 新单测：手工建旧 10 列表后构造 manager，自动补列且旧记录可读 |
| UI 可达且类型安全 | `PluginsTab` 注册进设置页；新增 16 例前端测试（client 9 + 面板 7），另跑既有 settings 搜索索引 12 例；tsc、eslint、build、architecture-check 本地绿，PR CI 再复核 |

## 4. 风险与边界

| 风险 / 边界 | 处置 |
| --- | --- |
| 「安装」被误读为「代码已能跑」 | spec/账本/UI 文案明示：R82 管理生命周期记录，代码托管在 R83 |
| `install_path` 任意字符串 | 本轮只记录不执行、不读目录；路径校验随 R83 加载器一起做 |
| 全局单例连接串扰测试 DB | 路由每请求新建 manager，避开 `get_lifecycle_manager` 单例缓存的连接 |
| 前端文案 i18n 分工 | tab 名走既有 i18n 键（zh/en 各一）；面板正文按 locale 内联切换中英文，后续若抽键不改变组件契约 |
| `backend/main.py` 基线文件增长 | 仅新增 import + router 挂载 3 行；按 architecture ratchet 协议只把该文件基线从 1272 更新到 1275 |


## 5. 本地验证记录

- 后端：manifest 既有单测 + lifecycle 既有单测 + lifecycle events 新单测 +
  plugin REST 新测试，共 59 passed；本次 Python 文件 ruff 全绿。
- 前端：pluginClient 9 例、PluginsTab 7 例、settingsSearchIndex 12 例通过；
  `npm run typecheck`、`npm run build`、定向 eslint 与 architecture-check 通过。
- 交付仍以 PR #2206 新 commit 的 GitHub CI 全绿为最终判据。
