# Arena 注册辅助 + 账号管理面板 + 模型观测接线 实施方案

> 日期：2026-09-19 · 分支：`feat/arena-register-assist` · worktree：`../sage-arena-assist`
> 上游 spec：`docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md`
> 关联既有实现：`arena_accounts.py`（账号池）、`arena_adapter.py`（CDP 驱动）、
> `arena_observation.py`（观测服务，start 为 stub）、`arena_routes.py`（已挂路由但服务从未初始化）、
> `temporary_mail/`（仅抽象基类）。

---

## 0. 范围与边界（先读这个）

本方案只做三件事，全部落在既有 spec §1.4 划定的边界内：

1. **TemporaryMailProvider 第一批具体实现**（mail.tm）+ provider registry。
2. **单账号注册辅助流程**：用户在 UI 手动触发；sage 自管浏览器打开 arena 注册页、
   自动填邮箱/密码表单；**人机验证一律人工完成**（检测到验证码 → 状态停在
   `awaiting_signup` 并提示用户）；验证邮件到达后把链接呈给用户、由用户点开；
   全程**单实例、无批量循环、无并发注册**。
3. **被动模型探针增强**：给 `ModelObservationService.start()` 补上真实的事件泵
   （复用 `browser_ws.py` 原语），并新增观测 REST + 面板展示。观测只读
   sage 自己打开的页面的网络事件帧，纯被动。

**明确不做**（与 2026-09-19 评审结论一致）：批量/并发注册、无头 token 铸造、
reCAPTCHA 自动出票、TLS 指纹伪装、代理轮换换 IP、429 绕限。这些是外部
「协议注册抽卡机」工具的核心机制，属于绕过 arena.ai 反滥用控制，不进 sage。

## 1. 架构

```
前端 ArenaAccounts 页 ──IPC(backendRequest)──► /api/v1/arena/*
                                                │
              ┌─────────────────────────────────┼──────────────────────────┐
              │ arena_routes.py（flag 检查）     │                          │
              │   /accounts*  → ArenaAccountService（已有，补 lifespan 装配）│
              │   /register/* → ArenaRegistrationService（新，单实例状态机） │
              │   /observations* → ModelObservationService（新接线）        │
              └─────────────────────────────────┴──────────────────────────┘
                        │                                   │
     temporary_mail/mailtm.py（httpx）              CdpEventPump（browser_ws 原语）
     ArenaAdapter 扩展（注册页填表，best-effort）    Network 事件帧 → process_event → 判定
```

## 2. 全局约束

- Win7/py38 兼容：新文件一律 `from __future__ import annotations`；类型用
  `Optional[X]`/`List[X]`；pydantic 配置沿用 v1/v2 兼容写法（`class Config`）。
- feature flag：`arena_automation.enabled` 默认 False；所有新端点沿用 `_check_enabled()`。
- 凭据：密码入池走既有 Fernet 加密；主密钥经 SecretBox（DPAPI/keychain）托管在
  preferences 新键 `arena_master_key`，不落明文。
- 日志不打印密码/邮件正文全文。
- 前端沿用 ModelCatalog 纵切模式：`entities/arena/api.ts` + `pages/ArenaAccounts.tsx`
  + `widgets/arena/`，`backendRequest` 走 `/api/v1/*`，Tailwind 主题 token，中文直书。
- 测试标记 `@pytest.mark.unit/integration`；asyncio_mode=auto。

## 3. 文件清单

| 路径 | 动作 | 说明 |
|---|---|---|
| `backend/config/arena_automation.py` | 改 | 加 `load_arena_automation_config()`（yaml → pydantic，fail-safe 默认关） |
| `backend/config/arena_automation.yaml` | 新 | 默认 `enabled: false` + 注释说明各字段 |
| `backend/services/temporary_mail/base.py` | 改 | 加具体方法 `wait_for_message()`（基于 `_fetch_messages`，正文正则匹配） |
| `backend/services/temporary_mail/mailtm.py` | 新 | mail.tm REST 适配（httpx.AsyncClient，domains→accounts→token→messages） |
| `backend/services/temporary_mail/registry.py` | 新 | `create_provider(name, api_key)`，未知名报 ValueError |
| `backend/services/arena_accounts.py` | 改 | 加 `get_or_create_master_key()`（SecretBox 托管，settings 白名单新键） |
| `backend/data/settings_repo.py` | 改 | KEYS 白名单加 `arena_master_key` |
| `backend/services/arena_adapter.py` | 改 | 注册辅助方法：`open_page / current_url / fill_first_input / click_submit / fill_password_fields`（best-effort，找不到选择器抛既有 SelectorNotFoundError） |
| `backend/services/arena_registration.py` | 新 | `ArenaRegistrationService`：单实例状态机 + 后台收信线程 + TTL |
| `backend/tools/browser_cdp.py` | 改 | 加 `CdpEventPump`（长连 WS 线程：attach→Network.enable→循环回吐事件帧） |
| `backend/services/arena_observation.py` | 改 | `start()/stop()` 实装（泵可注入，便于测试）；判定附时间戳 |
| `backend/api/arena_routes.py` | 改 | +`/register/*` 5 端点、+`/observations` 3 端点、+`init_registration_service()`、观测 attach/detach 单例 |
| `backend/main.py` | 改 | lifespan 装配：读 yaml → init_arena_service + init_registration_service（enabled 时）；fail-safe |
| `src/entities/arena/api.ts` | 新 | backendRequest 客户端 + 类型 |
| `src/entities/arena/index.ts` | 新 | barrel |
| `src/widgets/arena/AccountTable.tsx` | 新 | 账号表（状态徽标 + 行内隔离/启用/删除） |
| `src/widgets/arena/RegisterAssist.tsx` | 新 | 注册向导（状态时间线 + 验证码人工提示 + 验证链接 + 设密码） |
| `src/widgets/arena/ObservationFeed.tsx` | 新 | 最近模型判定列表 + 启停按钮 |
| `src/widgets/arena/index.ts` | 新 | barrel |
| `src/pages/ArenaAccounts.tsx` | 新 | 页面组装 |
| `src/App.tsx` | 改 | lazy 路由 `/arena-accounts` |
| `src/widgets/layout/Sidebar.tsx` | 改 | moreNavItems 加「Arena 账号」 |
| `src/pages/__tests__/ArenaAccounts.test.tsx` | 新 | mock api 层渲染断言 |
| 后端测试 ×5 | 新/改 | 见 §6 |

## 4. 关键设计

### 4.1 注册状态机（ArenaRegistrationService）

```
awaiting_signup ──(用户完成人机验证+提交)──► awaiting_verification
      │  captcha_present=true 时 UI 提示人工处理                │ 后台线程轮询邮箱
      ▼                                                ▼
   cancelled ◄────────────────                       verification_ready
                                                        │ POST /register/current/open-verify（用户触发）
                                                        ▼
                                                 awaiting_password
                                                        │ POST /register/current/password
                                                        ▼
                                                     completed ──► 入池(ArenaAccountService)
```

- 同一时刻**至多一个**活跃注册（含已启动浏览器与临时邮箱）；再次 start → 409。
- TTL 30 分钟，惰性过期（读状态时检查）；后台收信线程轮询间隔 5s、超时同 TTL。
- 浏览器：`launch_browser(headless=False)`（可见，用户要手动过验证码）；adapter 操作
  全部 best-effort——任何 SelectorNotFoundError 只降级为「请在浏览器中手动操作」，不失败整个流程。
- 验证链接正则取自验证邮件正文 `https://arena\.ai/\S*(callback|verify)\S+`；呈给用户，
  用户点「在浏览器中打开」才导航（Page.navigate）。永不自动点击提交人机验证。
- 完成入池前检查 `max_accounts`；密码校验沿用 arena 规则（≥8 位，四类字符）。

### 4.2 mail.tm provider

- `create_mailbox()`：GET /domains 取域名 → 随机 12 位本地 part + 随机密码 →
  POST /accounts → POST /token 存 JWT → `Mailbox(provider_token=jwt)`。
- `_fetch_messages()`：GET /messages（列表）→ 逐条 GET /messages/{id} 水合 `body`。
- `destroy_mailbox()`：GET /me 拿 account id → DELETE /accounts/{id}，尽力而为不抛。
- 构造函数接受 `transport`（httpx.MockTransport）供测试注入。

### 4.3 CdpEventPump

- 长连 `ws_connect(127.0.0.1, port, ws_path)` → `Target.attachToTarget(flatten)` →
  `Network.enable` → 线程循环 `ws_recv_text`（1s 超时轮询 stop 标志）→
  每帧 `json.loads` 回调 `on_event(frame)`（id 帧跳过）。
- `stop()`：置标志 + `ws_close`；线程 daemon。断线自动退出并在 service 里记状态。
- `ModelObservationService.start(pump_factory=None)`：默认 `CdpEventPump`，
  测试注入 fake；verdicts 追加 `observed_at`。

### 4.4 观测 REST

- `POST /api/v1/arena/observations/attach {browser_id?}`：`get_browser_manager().require()`
  → 新建 ModelObservationService（worker 用 `config.probe_backend`）→ start；重复 attach 先 detach 旧的。
- `GET /api/v1/arena/observations?limit=20`：recent verdicts + attached 状态。
- `POST /api/v1/arena/observations/detach`。

### 4.5 lifespan 装配（main.py）

```python
arena_cfg = load_arena_automation_config()   # fail-safe 默认关
if arena_cfg.enabled:
    data_dir = SAGE_USER_DATA_DIR or backend/data
    init_arena_service(db_path=..., encryption_key=get_or_create_master_key(), config=arena_cfg)
    init_registration_service(config=arena_cfg)
```
修掉「路由挂了但服务永不初始化」的既有缺口；不 enabled 时端点按既有约定 403。

## 5. 边界与降级行为

| 情形 | 行为 |
|---|---|
| 浏览器未装/启动失败 | start 返回 502，注册标记 failed，邮箱销毁 |
| 注册页选择器失配 | 降级提示手动操作，流程不中断 |
| 检测到 captcha iframe | 状态保持 awaiting_signup + `captcha_present=true`，UI 明示人工 |
| 邮箱服务不可用 | start 返回 502，error 带原因 |
| TTL 到期 | expired，浏览器关闭，邮箱销毁 |
| 入池超 max_accounts | completed 失败转 failed，error 提示，账号不入池 |

## 6. 测试计划

| 文件 | 覆盖 |
|---|---|
| `tests/unit/services/temporary_mail/test_mailtm.py` | MockTransport：建箱/收信水合/销毁/401 重试 |
| `tests/unit/services/test_arena_registration.py` | 状态机全迁移、captcha 暂停、TTL、单实例、max_accounts、密码校验、取消清理 |
| `tests/unit/api/test_arena_routes.py`（改） | register 5 端点（fake service 注入）、observations 3 端点（fake 观测）、403 路径 |
| `tests/unit/services/test_arena_observation.py`（改） | start/stop 泵注入、verdict 时间戳 |
| `tests/unit/config/test_arena_automation_config.py` | yaml 解析/缺文件/坏 yaml fail-safe |
| `src/pages/__tests__/ArenaAccounts.test.tsx` | 表格渲染、注册向导状态切换、观测启停按钮 |

## 7. 提交切分

1. `feat(arena): mail.tm 临时邮箱 provider + registry`
2. `feat(arena): 单账号注册辅助服务与 REST（人工验证码，单实例）`
3. `feat(arena): 模型观测事件泵实装 + 观测 REST`
4. `feat(arena): lifespan 装配 arena 服务（修服务未初始化缺口）`
5. `feat(ui): Arena 账号管理面板（账号池 + 注册向导 + 观测流）`
6. `test(arena): 后端单测与前端组件测试`
