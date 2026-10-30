# 网页访问登录体验优化 P0 实施计划

> 范围：release/win7 分支（Python 3.8 / pydantic 2.5.x / Electron 21）。
> 目标：让「登录网站 → 抓取动态/登录墙站点」对用户零术语、最多两次点击；
> 登录态一次保存、静态/渲染/浏览器三通道复用。

## 1. 背景与目标

当前设置页「网络 → 网站凭据」要求用户理解 cookie/header/domain、手动粘贴
`session=abc; ...`，并暴露 4 个开发开关与运维指标（`NetworkCredentialsSection.tsx`）。
对话侧登录墙卡片只能把用户丢回设置页（`useChatMessageActions.ts:292-300`）。

P0 交付：

1. **storage_state 会话快照**：cookie + localStorage 一起加密保存；渲染通道导航前
   注入、渲染后回写。解决知网等「cookie + localStorage 双 token」站点登录态丢失。
2. **「已登录的网站」界面**：列表 + 一键添加登录 + 站点模板；技术表单/开关折叠进
   「高级与诊断」，默认不可见。
3. **站点登录任务 API**：`POST /web-access/sites/login` 后台跑 `browser_login`，
   前端轮询结果，不阻塞 HTTP。
4. **聊天内一键登录并自动续跑**：登录墙卡片点击后直接发起登录任务，成功后自动发
   一条继续请求的消息，无需用户再描述需求。
5. 文案去术语（zh/en 同步），设置搜索索引与用户手册更新。

不做（留 P1）：Electron 内置浏览器、应用内浏览器面板、扩展桥、CNKI 专用下载 playbook。

## 2. 涉及文件

### 后端

| 文件 | 动作 |
|---|---|
| `backend/tools/credential_vault.py` | 新增 storage_state 存取/合并；`CredentialResolution.origins`；list 增加 `saved_at`/`has_storage`/`origin_count` |
| `backend/tools/browser_tool.py` | `browser_login` 登录后同时捕获 localStorage；`browser_cookies export` 尽力捕获当前页 |
| `backend/tools/web_render.py` | 导航前 `Page.addScriptToEvaluateOnNewDocument` 注入 localStorage；渲染后回写 |
| `backend/tools/web_tool.py` | 档案含 origins 时自动走渲染（static 通道无法带 localStorage） |
| `backend/services/site_login_templates.py` | 新建：知网/万方/维普/IEEE/Springer 模板 |
| `backend/services/site_login_jobs.py` | 新建：进程内登录任务管理器（线程 + 轮询） |
| `backend/api/web_access_routes.py` | 新增 `/site-templates`、`/sites`、`/sites/login`、`/sites/login/{job_id}`；DELETE `/sites/{domain}` |
| `backend/tests/unit/test_credential_vault.py` | storage_state 单测 |
| `backend/tests/unit/test_web_render.py` | localStorage 注入/回写单测 |
| `backend/tests/unit/test_browser_tool.py` | 登录捕获 localStorage 单测 |
| `backend/tests/api/test_web_access_sites.py` | 新 API 契约测试 |

### 前端

| 文件 | 动作 |
|---|---|
| `src/shared/api/webAccessClient.ts` | 新建：sites/templates/login-job 请求封装（沿用 `webAccessApiUrl`） |
| `src/pages/settings/SiteSessionsSection.tsx` | 新建：已登录网站列表 + 添加登录 + 高级折叠 |
| `src/pages/settings/NetworkTab.tsx` | 用 `SiteSessionsSection` 替换 `<CredentialsSection />` |
| `src/pages/settings/NetworkCredentialsSection.tsx` | 保留为高级面板（标题/文案调整） |
| `src/pages/settings/settingsSearchIndex.ts` | `web_credentials` 条目改为「网站登录」+ 新关键词 |
| `src/pages/chat/useChatMessageActions.ts` | `login_to_site` 改为直接发起登录任务并自动续跑 |
| `src/widgets/chat/BlockedCard.tsx` | 原始 blockReason 徽章收进技术详情，不再直出枚举 |
| `src/shared/lib/i18n/locales/{zh,en}/chatAndSider.ts` | 新增 `settings.network.sites.*`、`chat.blocked.*` 文案 |
| `src/pages/settings/__tests__/SiteSessionsSection.test.tsx` | 新建 UI 测试 |
| `docs/user-manual/19-web-access.md` | 重写「网站登录」章节 |

## 3. 全局约束

- Python 3.8：禁止 PEP 604（`X | Y`）与 PEP 585（`list[str]`）运行时注解；用
  `typing.List/Optional/Dict`；pydantic 用 `Extra.forbid`（仓库已有 shim）。
- ruff：双引号（Q000）；中文注释避免 ERA001 误报（用 docstring 或 `—`）。
- 加密：一切凭据值经 `encrypt_secret/decrypt_secret`；API 永不回显值。
- 前端：函数组件 + 显式类型；不引入新依赖；文案 zh/en 成对新增。
- 测试：后端 `pytest`（sage-backend-py38 或 sage-backend），前端 `vitest`。
- 单文件 ≤800 行；新增组件优先拆分。

## 4. 数据结构

vault 每个 domain 条目新增可选字段：

```json
{
  "kind": "cookie",
  "cookies_enc": "<enc>",
  "origins_enc": "<enc>",
  "saved_at": 1737000000000,
  "updated_at": 1737000000000,
  "storage_saved_at": 1737000000000,
  "source_profile": "login-default"
}
```

`origins` 明文形态（加密前）：

```json
[{"origin": "https://kns.cnki.net", "localStorage": {"cnki_user_token": "…"}}]
```

上限：≤50 origins/domain，≤200 keys/origin，key ≤512 字符，value ≤8 KiB，
序列化总量 ≤256 KiB；超限条目丢弃并记 warning，不失败整次保存。

## 5. 实施任务

### Task 1：credential_vault storage_state

**Files**：`backend/tools/credential_vault.py`、`backend/tests/unit/test_credential_vault.py`

**Interfaces（后续任务依赖）**：

```python
def save_storage_state(domain: str, cookies: List[Dict[str, Any]],
                       origins: List[Dict[str, Any]], repo: Optional[Any] = None,
                       source_profile: str = "") -> None: ...
def load_storage_origins(domain: str, repo: Optional[Any] = None) -> List[Dict[str, Any]]: ...
def merge_storage_origins(domain: str, origins: List[Dict[str, Any]],
                          repo: Optional[Any] = None) -> bool: ...
# CredentialResolution 增加 .origins: List[Dict[str, Any]]
```

- [x] Step 1：写失败测试：`test_storage_state_roundtrip`（保存 cookie+localStorage，
      `load_storage_origins` 取回、`resolve_credential(url=...).origins` 只返回匹配
      host 的 origin）；`test_storage_state_rejects_oversize`；`test_merge_storage_origins`。
- [x] Step 2：运行 `pytest backend/tests/unit/test_credential_vault.py -k storage -q`，确认失败。
- [x] Step 3：实现 `_normalize_origin`、`_clean_origins`、`save_storage_state`、
      `load_storage_origins`、`merge_storage_origins`；`resolve_credential` 在 cookie
      ok 时附加过滤后的 origins；`list_credentials` 增加 `saved_at`/`has_storage`/`origin_count`。
- [x] Step 4：运行测试通过。
- [x] Step 5：提交 `feat(web-access): 凭据档案支持 storage_state（cookie+localStorage）`。

### Task 2：browser_login 捕获 localStorage

**Files**：`backend/tools/browser_tool.py`、`backend/tests/unit/test_browser_tool.py`

**Interfaces**：

```python
def _capture_local_storage(session: BrowserSession, target_id: str = "") -> List[Dict[str, Any]]:
    # → [{"origin": "https://kns.cnki.net", "localStorage": {k: v}}]
```

- [x] Step 1：失败测试：fake `cdp_command` 返回 `Runtime.evaluate` 结果
      `{"origin": "...", "localStorage": {...}}`，断言 `save_storage_state` 被以
      同域 cookies + origins 调用；localStorage 为空时不写 origins。
- [x] Step 2：运行确认失败。
- [x] Step 3：实现 `_capture_local_storage`；`BrowserLoginTool._export_cookies`
      增加 `target_id` 参数并在保存每域 cookie 后调用 `save_storage_state`；
      `BrowserCookiesTool` export 时尽力取第一个 page target 捕获 localStorage。
- [x] Step 4：测试通过。
- [x] Step 5：提交 `feat(web-access): 登录时保存 localStorage 会话`。

### Task 3：渲染通道注入/回写 localStorage

**Files**：`backend/tools/web_render.py`、`backend/tools/web_tool.py`、`backend/tests/unit/test_web_render.py`

- [x] Step 1：失败测试：
      `test_render_injects_local_storage_before_navigate`（断言
      `Page.addScriptToEvaluateOnNewDocument` 在 `Page.navigate` 之前）；
      `test_render_writeback_local_storage`（evaluate 返回新 token → merge 被调用）。
- [x] Step 2：运行确认失败。
- [x] Step 3：实现：
      - `render_page` 解析 `resolution.origins` → `credential_origins`；
      - `_inject_local_storage(session, target_id, origins)`：先 `Page.enable`，
        再对每个 origin 调 `Page.addScriptToEvaluateOnNewDocument`，脚本内按
        `location.origin === o.origin` 时 `localStorage.setItem`（try/catch）；
      - 渲染后 `_capture_local_storage` 并 `merge_storage_origins`；
      - `web_tool.execute`：`resolution.origins` 非空且 render="auto" → 设
        `render="always"`，并在结果 note 说明「该站点需要浏览器会话」。
- [x] Step 4：测试通过。
- [x] Step 5：提交 `feat(web-access): 渲染通道注入并回写 localStorage`。

### Task 4：站点模板 + 登录任务 + sites API

**Files**：
- 新建 `backend/services/site_login_templates.py`
- 新建 `backend/services/site_login_jobs.py`
- 修改 `backend/api/web_access_routes.py`
- 新建 `backend/tests/api/test_web_access_sites.py`

**Interfaces**：

```python
# site_login_templates.py
SITE_LOGIN_TEMPLATES: List[Dict[str, Any]]  # id/display_name/domains/login_url/login_hint
def match_site_template(hostname: str) -> Optional[Dict[str, Any]]: ...

# site_login_jobs.py
class SiteLoginJobs:
    def start(self, url: str) -> str: ...          # job_id
    def get(self, job_id: str) -> Optional[Dict[str, Any]]: ...
site_login_jobs = SiteLoginJobs()

# routes
GET  /api/v1/web-access/site-templates
GET  /api/v1/web-access/sites
POST /api/v1/web-access/sites/login       {"url": "https://..."} → {"job_id": "..."}
GET  /api/v1/web-access/sites/login/{job_id}
DELETE /api/v1/web-access/sites/{domain}
```

sites 返回项：

```json
{"domain": ".cnki.net", "display_name": "知网 CNKI", "login_url": "https://kns.cnki.net/",
 "status": "logged_in", "expires_in_seconds": 3600, "has_local_storage": true,
 "origin_count": 1, "saved_at": 1737000000, "source_profile": "login-default"}
```

状态规则：`expired` 字段为真 → `expired`；否则 `logged_in`。

- [x] Step 1：契约测试（monkeypatch `list_credentials`/`delete_credential`/`match_site_template`/
      `site_login_jobs.start`）：sites 列表形态与展示名、DELETE 404/成功、
      login 非法 scheme 422、login 返回 job_id、job 查询返回 running/success、
      Origin 守卫 403。
- [x] Step 2：运行失败。
- [x] Step 3：实现模板、JobManager（daemon 线程、最多 20 条、10 分钟 TTL、
      `check_host` 门禁、`BrowserLoginTool().execute(url=..., timeout_seconds=300)`，
      content 中 `saved_domains` 记录）、路由。
- [x] Step 4：测试通过。
- [x] Step 5：提交 `feat(web-access): 站点模板与后台登录任务 API`。

### Task 5：前端「已登录的网站」界面

**Files**：
- 新建 `src/shared/api/webAccessClient.ts`
- 新建 `src/pages/settings/SiteSessionsSection.tsx`
- 修改 `NetworkTab.tsx`、`NetworkCredentialsSection.tsx`（标题改「高级：手动导入与诊断」）、
  `settingsSearchIndex.ts`
- 新建 `src/pages/settings/__tests__/SiteSessionsSection.test.tsx`

**行为**：
- 空状态：「当 Sage 访问需要登录的网站时，会在这里提示你登录。」
- 列表项：favicon 占位图标 + 展示名 + 域名 + 状态徽章（已登录/已过期）
  + 「重新登录」「断开」。
- 添加区：URL 输入 + 模板下拉（可选）+「登录网站」按钮；点击后 POST login，
  每 2s 轮询 job，展示「等待你在浏览器中完成登录…」，成功刷新列表。
- 高级 `<details>`：内嵌现有 `CredentialsSection`。

- [x] Step 1：UI 测试（mock fetch）：空状态、列表渲染、点击登录发起 POST 并轮询
      到 success 后重新 GET、删除确认、高级折叠默认收起。
- [x] Step 2：运行失败。
- [x] Step 3：实现 client + 组件 + 接入 NetworkTab + 搜索索引。
- [x] Step 4：`npm run test -- SiteSessionsSection` 通过；`NetworkTab.test.tsx` 仍绿。
- [x] Step 5：提交 `feat(settings): 「已登录的网站」登录管理界面`。

### Task 6：聊天内一键登录并自动续跑

**Files**：`src/pages/chat/useChatMessageActions.ts`、`src/widgets/chat/BlockedCard.tsx`、
i18n、`src/widgets/chat/__tests__/BlockedCard.test.tsx`（若存在则扩展）

- [x] Step 1：测试：BlockedCard 不再显示原始枚举文本，渲染人话原因；
      点击 login_to_site 动作后调用 `startSiteLogin`（mock client）并在成功后
      发送继续消息。
- [x] Step 2：运行失败。
- [x] Step 3：实现：`login_to_site` → `startSiteLogin(url)` + 轮询；
      成功后 `sendMessage(t('chat.blocked.login.continue', {url}))`；
      失败 toast；BlockedCard 徽章改为翻译文案，原始值放 `title`/details。
- [x] Step 4：测试通过。
- [x] Step 5：提交 `feat(chat): 登录墙一键登录并自动继续任务`。

### Task 7：文案、文档、i18n

- [x] 新增 zh/en 文案（sites.*、advanced.*、blocked.login.*），删除/改写
      「website credentials」直译；检查 `TranslationKey` 类型通过。
- [x] 更新 `docs/user-manual/19-web-access.md`：新流程三段（添加网站/对话触发/高级导入）。
- [x] `npm run typecheck`（或 `npx tsc -p tsconfig.json --noEmit`）+ `npm run lint`。
- [x] 提交 `docs(user-manual): 网站登录流程说明`。

### Task 8：验证与交付

- [x] 后端：`/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_credential_vault.py backend/tests/unit/test_web_render.py backend/tests/unit/test_browser_tool.py backend/tests/api/test_web_access_routes.py backend/tests/api/test_web_access_sites.py -q`
- [x] 后端 ruff + py38 hazard scan（若仓库有脚本）。
- [x] 前端：`npm run test -- SiteSessionsSection NetworkTab BlockedCard` + `npx tsc --noEmit`。
- [ ] git push + PR（目标 release/win7），概述改动与测试计划（待办：推送后执行）。

## 6. 风险与边界

- **静态通道限制**：localStorage 只能由浏览器执行，静态 `web_fetch` 无法携带；
  已用「有 origins 时强制渲染」兜底，静态结果可能仍缺 token（明确 note）。
- **登录任务为进程内状态**：重启丢失；P0 可接受，P1 与内置浏览器一起持久化。
- **站点模板 URL 可能变化**：模板只是默认值，用户可手输 URL；失败不阻塞。
- **安全**：密码/验证码永不经聊天或设置页；API 只返回脱敏字段；登录任务受
  `NetworkPolicy.check_host` 门禁与 Origin 守卫；手动导入仍保留在高级区。
- **权限豁免（安全审查 H1）**：`POST /web-access/sites/login` 的后台 runner 直接
  调用 `BrowserLoginTool`，不经 `PermissionEngine` 逐次审批。P0 判定可接受：入口
  仅由用户在设置页/聊天卡片主动点击触发，且 REST 端受本地 bearer token + Origin
  守卫；已在工具内补 `check_host` 二次校验。P1 应改为经工具执行器/审批流。
- **数据最小化（安全审查 M1-M3）**：登录导出只保留归属目标站（含登录页域）的
  cookie；localStorage 回写校验 origin 归属并按 50 origins / 256 KiB 上限重新裁剪。
- **登录 URL**：拒绝内嵌 userinfo（`https://user:pass@host`），避免凭据回显。
- **知网**：P0 只保证「登录态跨通道复用 + 一键登录」，不承诺反爬/滑块/PDF 下载
  全自动（P1 playbook 负责）。

## 7. 验收

- 设置页默认看不到 cookie/header 表单与开发开关；「已登录的网站」可完成
  「输入网址 → 登录 → 列表出现已登录」。
- `browser_login` 后 `resolve_credential` 返回 origins；渲染通道导航前注入并可回写。
- 聊天登录墙卡片点击后无需跳转设置页，登录成功自动继续原请求。
- 现有凭据接口/高级表单不回归；后端 5 个测试文件、前端 3 个测试文件全绿。
