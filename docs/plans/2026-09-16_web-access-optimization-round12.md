# 网页访问能力优化 Round 12：凭据管理 UI + humanize 工具名（2026-09-16）

- **上游文档**：Round 5 §2.5 / Round 10-11（AU 系列后端已收尾）；本次分析报告"凭据管理 UI 缺失是最高用户感知缺口"
- **范围**：main 与 release/win7 双分支（后端小路由 + 前端 settings 区块 + humanize）
- **方法**：基于 Round 11 合并后 main 的 api 路由约定 / settingsClient / NetworkTab / mediaApi 勘察

## 0. 结论速览

AU 系列后端能力（cookie 桥 / 三通道互通 / 自动刷新）已完备，但用户**看不见也管不了**自己的凭据：存了哪些站、何时过期、是否明文落库，全部只能在对话里让 agent 调工具查看。本方案给设置→网络加"网站凭据"区块（列表 / 删除 / 来源 profile / 加密标记），并把 `web_access_config` 的两个开关（render_persistent、auto_refresh_credentials）搬进 UI；顺带补齐 humanize.ts 的 browser 工具显示名（时间线/审批弹窗不再显示生工具名）。

| 项 | 内容 | 批次 |
| --- | --- | --- |
| C1 | 后端 REST：credentials list/delete + web_access_config get/put + main.py 注册 | 批次 1 |
| C2 | 前端：NetworkTab"网站凭据"区块（列表/删除/两开关）+ settingsClient 类型 | 批次 2 |
| C3 | humanize.ts browser 工具显示名 | 批次 2 |
| T | API 契约测试 + vitest + CHANGELOG | 批次 2 |

## 1. 设计

### 批次 1：后端路由（backend/api/web_access_routes.py，新文件）

- `GET /api/v1/web-access/credentials` → `{"credentials": list_credentials()}`（复用既有脱敏口径，无值回显）
- `DELETE /api/v1/web-access/credentials/{domain}` → `delete_credential(domain)`；无档案 404
- `GET /api/v1/web-access/config` → 解析 `web_access_config`（缺省 `{}`）
- `PUT /api/v1/web-access/config` → body 仅接受 `render_persistent` / `auto_refresh_credentials` 两个 bool 键（未知键 422），与现有值合并后经 SettingsRepository 白名单写回
- `main.py` 注册 router；与既有 permission_routes 同款 ASGITransport 契约测试

安全口径：本地回环专用后端（与 /wiki/clip 等同面）；list 不回显任何 cookie 值；删除是不可逆操作，前端二次确认。

### 批次 2：前端

- `settingsClient`：`web_access_config` 已在 PreferenceKey 白名单（Round 1），直接 getPreference/setPreference
- `NetworkTab.tsx` 新增"网站凭据"区块：
  - 列表：domain / kind（cookie|header）/ cookie_names 或 header_names / 最短剩余时效 / `encrypted` / `source_profile`
  - 删除按钮（confirm 后 DELETE，成功后刷新列表）
  - 两个开关：JS 渲染用持久 profile（render_persistent）、登录态自动刷新（auto_refresh_credentials）
  - REST 基址复用 `resolveMediaUrl` 的 dev/prod 解析思路（提为共享 helper 或本地同款实现）
- `humanize.ts`：新增 browser_launch/browser_navigate/browser_snapshot/browser_interact/browser_screenshot/browser_cookies/browser_downloads/browser_close 显示名（中文文案走既有 i18n-less verb 模式，英文动词）；vitest 用例

## 2. 双分支

- 后端新文件 + main.py 两行：cherry-pick 零冲突
- 前端 src/：win7 分支同样维护前端（历史 PR 前端改动均双分支同步），零预期冲突
- CHANGELOG 按既有套路手工合入

## 3. 未纳入（记录）

- AB6 连接复用 / AB3 TLS 指纹（后端性能系列，Round 13 候选）
- 截图视觉回传（多模态端点约束，独立评估）
- win7 Chrome 109 老化监控（doctor 系列）
