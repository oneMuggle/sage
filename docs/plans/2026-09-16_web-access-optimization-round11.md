# 网页访问能力优化 Round 11：AU3 自动刷新回路 + AU 系列收尾（2026-09-16）

- **上游文档**：Round 5 §2.4 AU3 提案；Round 10（AU5 已交付，本方案在其上）；Round 15（vault 加固）
- **范围**：main 与 release/win7 双分支（后端 only，零新依赖，py3.8 纪律）
- **方法**：基于 Round 10 合并后 main 的 browser_cdp / browser_tool / credential_vault / web_render / web_tool / download_tool 勘察

## 0. 结论速览

AU5 打通三通道后，登录态剩余最大缺口是 **AU3：登录失效后没有自动刷新回路**——带凭据请求被踢到登录页只报 `login_required` 等用户重新手动导出。本方案让"持久 profile 还活着"的档案自愈：cookie 档案记录来源 profile（AU6），登录墙触发时用该 profile 静默重导一次并重放请求。同时收尾两件小事：AU7 渲染分支登录墙检测（AU5 注入后渲染页也可能被踢登录）、X4 DPAPI 降级可观测（scheme=none 时凭据明文落库但用户无感知）。

| 项 | 内容 | 批次 |
| --- | --- | --- |
| AU6 | `BrowserSession.profile_name` 字段；export 档案记录 `source_profile`；list 展示 | 批次 1 |
| AU3 | `auto_refresh_credentials` 开关 + web_render 静默重导 + web_fetch/download 重放 | 批次 2 |
| AU7 | 渲染分支登录墙检测（注入后密码框页 → `login_required`） | 批次 3 |
| X4 | scheme=none 存凭据时告警（note + logger + list 标记） | 批次 3 |
| T | 单测 + CHANGELOG + 文档回填 | 批次 3 |

## 1. 现状勘察

- `BrowserSession`（browser_cdp.py:120）只有 `persistent: bool`，**不记 profile_name**——export 无法知道 cookie 来自哪个持久 profile。
- `BrowserCookiesTool.export`（browser_tool.py:776-815）`save_credential(domain, cookies)` 只存 cookie 本体。
- `login_required` 路径（web_tool.py `_detect_login_wall`、download_tool 同款）直接失败返回，无重试回路。
- AU5 后渲染分支带凭据，但渲染最终页若仍是登录墙（密码框页）会被当普通正文返回——静态通道有 `_detect_login_wall`，渲染通道没有。
- `secret_box.encrypt_secret` scheme=none 时原样返回（诚实降级）；`save_credential` 不感知，用户看不到"这条凭据是明文落库的"。
- AB6（连接复用）仍未做（`with build_client(` 每 hop 新建）——本轮不做，保持轮次聚焦（记录到 Round 12 候选）。

## 2. 方案设计

### 批次 1：AU6 来源 profile 记录

- `BrowserSession` 增加 `profile_name: str = ""`；`launch_browser` 持久会话填充（临时会话留空）。
- `browser_cookies export`：持久会话导出时 vault 条目写 `source_profile`（可选字段，旧档案无此键照常工作）；结果 note 附 `source_profile=…`。
- `list_credentials` 展示 `source_profile`。

### 批次 2：AU3 自动刷新回路

- 配置：`web_access_config.auto_refresh_credentials`（默认 **关**；开启才自愈）。
- `web_render.refresh_credentials(url, profile_name, repo)`：launch_browser(persistent=True, profile_name=…) 独立保留 id `refresh-pool`（会话表不与用户实例冲突）→ 导航原 URL → `wait_page_ready` → 页面非登录页（`looks_like_login_html` 为 False）→ `Storage.getCookies` 按域 `merge_cdp_cookies` → 关闭。返回 (ok, refreshed_names)。
- 触发点：web_tool `_detect_login_wall` 命中后、download_tool 同路径——若档案带 `source_profile` 且开关开 → 调刷新 → 成功则重放原请求一次（重放仍登录墙则报 `login_required`，note 附 `credential_auto_refreshed` 失败原因）。
- 刷新会话 60s 超时兜底；失败静默回退为原 `login_required` 报错（不改变既有失败语义）。

### 批次 3：AU7 + X4 + 测试 + 文档

- AU7：AU5 注入路径渲染完成后，`looks_like_login_html(final_html)` 且渲染正文 < 500 字 → 报 `login_required`（提示重导或开启 AU3），不再把登录页当正文。
- X4：`save_credential` / `save_header_credential` / AU5 回写落库在 scheme=none 时 logger.warning 一次；`list_credentials` 条目加 `encrypted: false`；`browser_cookies export` / `set_header` 结果 note 明示。
- 测试：session 字段传递、export 记录 source_profile、AU3 触发/开关关/刷新失败回退/重放成功、AU7 判定、X4 标记。
- CHANGELOG + 方案文档状态回填。

## 3. 双分支

改动全部在 Round 10 后同源文件内（browser_cdp / browser_tool / credential_vault / web_render / web_tool / download_tool + 三个测试文件 + CHANGELOG + 新计划文档），cherry-pick 预期零冲突（CHANGELOG 按既有套路手工合入 win7 [Unreleased]）。py3.8 纪律不变。

## 4. 未纳入（记录）

- AB6 连接复用、AB3 TLS 指纹（main only）→ Round 12 候选。
- 凭据管理 UI / 截图视觉回传 / humanize browser 工具名 → 前端系列另行立项。
- win7 Chrome 109 老化监控 → doctor/诊断系列。
