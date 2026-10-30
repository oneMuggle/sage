# Gateway 稳定性治理与国内平台适配

> 日期：2026-10-30
> 状态：实施中（M1–M4 已完成，P2 国内平台首批待排期）
> 分支：`fix/gateway-lazy-start`（基线 `origin/release/win7`，完成后同步 main）
> 参考：ChatGPT Desktop / Claude Code Remote / Cursor / 豆包·通义·Kimi 的企业 IM 集成 / hermes-agent messaging gateway

---

## 1. 背景与目标

### 1.1 用户反馈

Win7 机器上打开 Sage 设置页后，后端出现大量 ASGI 异常，应用卡死/疑似崩溃。用户判断：
`backend/api/gateway_routes.py` 的 `_platform_config()` 在配置缺失时返回 None，随后对 None 迭代抛
`TypeError`，启动初期高并发反复触发，堆积海量异常拖垮 Python 进程。

同时，现有 Telegram / Discord / Slack 三个网关在国内网络不可达，在 Win7 上也无法使用。

### 1.2 目标

1. **止血**：消除配置缺失时的 500 异常与请求风暴；
2. **默认隐藏 / 懒启动**：网关不再是设置页默认加载项，未启用时前端零请求、后端零轮询；
3. **国内可用**：提供飞书 / 钉钉 / 企业微信等国内平台适配，国际平台降级为实验分组；
4. **Win7 兼容**：Python 3.8 + Electron 21 环境下稳定运行，具备网络不可达的显式提示与退避。

### 1.3 成功指标

| 指标 | 现状 | 目标 |
|------|------|------|
| 设置页挂载后的网关请求次数 | 持续无限循环（实测 3 秒 133 轮） | 每个平台仅 1 轮（3 次请求），不重复 |
| 未配置平台的 `GET /config` | 500 + 完整 ASGI 堆栈 | 200 + `source: "none"` |
| 未配置 / 未启用时的轮询线程 | 0（已满足） | 0（保持） |
| Win7 设置页停留 10 分钟 | CPU 持续飙升、日志暴涨 | CPU 平稳、无异常堆积 |
| 国内平台可用性 | 0 | 飞书长连接 / 钉钉 Stream 可用 |

---

## 2. 诊断结论（已核查）

### 2.1 属实部分

**缺陷 A：后端对 None 迭代**

- `backend/api/gateway_routes.py:272`：`raw_ids = node.get("allowed_channel_ids")`
  在 settings 节点存在但缺少该 key 时返回 `None`；
- `:276` 只处理 `str`，未处理 `None`；
- `:283` 对 `raw_ids` 做列表推导 → `TypeError: 'NoneType' object is not iterable`。
- **Telegram 的 `get_telegram_config()` 存在同名缺陷**（`:157` / `:168`），
  并非只有 `_platform_config()` 覆盖的 Discord / Slack。

**日志证据**（`backend/logs/sage_20261020.log`）：

- 11:26:19–11:26:21 三秒内，`GET /gateway/{telegram,discord,slack}/config` 全部 500：
  telegram 55 次、discord 49 次、slack 29 次，合计 **133 次失败**；
- 每个请求产生两段堆栈（ExceptionGroup 二次展开），日志中共 **266 条 TypeError**；
- 堆栈精确指向 `gateway_routes.py:283`。

**缺陷 B：前端 GatewayCard 无限重渲染循环（真正的风暴放大器）**

`src/widgets/settings/GatewayCard.tsx`：

- `:83` `const api = gatewayApiFor(platform);` —— 每次渲染都创建**新对象**；
- `:95-112` `reload = useCallback(..., [api])` —— 因 `api` 每次都是新引用，`reload` 每次渲染都变化；
- `:114-116` `useEffect(() => { void reload(); }, [reload])` —— 每次渲染后都执行；
- `reload` 内部 `setConfig(cfg)` / `setStatus(st)` / `setBinds(...)` 写入**新对象/新数组** → 触发重渲染 → 再次执行 effect。

结果：**无论接口成功还是失败，只要 GatewayCard 挂载，就会无限循环请求**。
133 次失败 / 3 秒正是该循环的实测速率（三个平台卡片并发）。

**测试为何没拦住：**

- 后端测试只在 `allowed_chat_ids` / `allowed_channel_ids` 存在或 env token 存在时调用 config 接口，
  没有覆盖「node 为空 / 缺 key」；
- 前端测试把 `gatewayApiFor` mock 成**恒定返回同一个对象**，`api` 引用稳定，循环不会出现。

### 2.2 需要修正的判断

| 用户判断 | 核查结果 |
|---|---|
| `_platform_config()` 配置缺失时返回 None | 不精确：函数本身在迭代时崩溃；None 来自 `node.get(...)` |
| 「启动初期」高并发触发 | 不成立：日志中异常发生在启动 8 小时后，由**设置页挂载**触发，不是后端启动 |
| 「反复触发」 | 属实，但根因是**前端渲染循环**，不是后端主动重试 |
| 「堆积海量 ASGI 异常拖垮 Python 进程」 | 部分成立：异常风暴属实；但该日志显示进程在风暴后继续运行（health 200、scheduler 正常），没有死亡证据。Win7 上更可能是渲染进程 CPU 打满 / 崩溃（已知 0xC0000005）或日志 I/O 放大，需 Win7 日志确认 |

### 2.3 Win7 上「三个网关不可用」的原因

- Telegram（api.telegram.org）、Discord（discord.com）在国内网络**不可达**；
- Slack 可访问但延迟高、国内企业使用率低；
- 网关 transport 使用 `httpx`，默认信任系统环境变量代理，但**UI 无代理配置入口**，
  用户无法为网关单独设置代理；
- Win7 的 Python 3.8 + 内嵌运行时依赖 `certifi`（requirements-py38 已声明），
  TLS 本身可用；实际故障多为超时/不可达，而非 SSL 库缺失。

---

## 3. 技术方案

### P0 止血（1–2 天）

1. **后端配置读取统一归一化**

   ```python
   def _normalize_ids(raw: object, env_value: str | None) -> list[str]:
       if isinstance(raw, str):
           raw = raw.split(",")
       if not isinstance(raw, list):
           raw = []
       return [str(c).strip() for c in raw if str(c).strip()]
   ```

   `_platform_config` 与 `get_telegram_config` 共用；env 优先逻辑保持不变。

2. **未配置是正常状态，不是 500**
   - `GET /gateway/{platform}/config`：始终 200，`source: "none"`、`enabled: false`、白名单 `[]`；
   - `GET /gateway/{platform}/status`：始终 200，`configured: false`、`running: false`；
   - `GET /gateway/{platform}/binds`：未配置返回 200 + `{binds: []}`（或保留 503，但前端静默处理）。

3. **前端循环修复**
   - `const api = useMemo(() => gatewayApiFor(platform), [platform]);`
   - `reload` 用 `useRef` 防重入（同一时刻只允许一个在途请求）；
   - `useEffect(() => { void reload(); }, [reload])` 在 `reload` 稳定后只执行一次；
   - 错误只记录一次，不在 catch 中反复触发状态更新。

4. **日志与异常处理**
   - 网关路由内部捕获已知配置异常，返回结构化 JSON，不输出完整 ASGI 堆栈；
   - 网关轮询失败使用 rate-limit 日志（例如同一错误 60 秒内只记一次）；
   - 连续失败 N 次后指数退避，并标记 `unreachable`。

5. **回归测试（先 RED 后 GREEN）**
   - 后端：3 平台 × `{无 settings 节点, 空节点, 缺 key, str 白名单, list 白名单, env token}`；
   - 前端：`GatewayCard` 挂载后 `getConfig` 只调用 1 次（用 fake timers 等待多个宏任务）；
   - 断言 config 接口在未配置时返回 200。

### P1 隐藏与懒启动（2–3 天）

1. **设置页默认隐藏**
   - 将「消息网关」从 `ToolsConnectionsTab` 的网关区块改为默认折叠（上游 #2670 设置页 IA 整理已删除 `GeneralTab`），
     放入独立「连接器 / Integrations」分组，默认折叠；
   - 折叠状态下**不挂载** `GatewayCard`（不是 CSS 隐藏），确保零请求；
   - 或增加 feature flag `app_settings.gateway.enabled`（默认 false），未启用时整组不渲染。

2. **后端懒启动**
   - 新增 `GatewaySupervisor`（`backend/gateway/supervisor.py`）：
     - 持有各平台 adapter；
     - `apply(platform, config)`：`enabled && configured` 才 `start_polling()`，否则 `stop_polling()`；
     - `status(platform)`：返回 `not_configured | disabled | unreachable | running`；
   - `PUT /gateway/{platform}/config` 直接调用 `supervisor.apply()`，
     **去掉「需重启后端」的 `restart_required`**；
   - 后端 lifespan 仅在 `gateway.enabled` 为 true 时导入并初始化 supervisor。

3. **健康探测**
   - 仅在平台被启用时做一次轻量可达性探测（如 Telegram `getMe`、Discord `/users/@me`、飞书 `tenant_access_token`）；
   - 失败标记 `unreachable`，UI 显示「当前网络无法访问该平台」，不自动重试风暴。

### P2 国内平台适配（按优先级分批）

保留 `BaseGateway` 的会话绑定 / 命令分发 / 审批转发 / LLM 对话能力，只替换协议层：

| 平台 | 接入方式 | 是否需要公网 IP | 备注 |
|---|---|---|---|
| **飞书（Feishu/Lark）** | 开放平台「长连接」（WebSocket，`lark-oapi`） | **否** | 桌面端最佳方案；需企业自建应用权限 |
| **钉钉（DingTalk）** | 开放平台「Stream 模式」（WebSocket，`dingtalk-stream`） | **否** | 企业内部机器人 |
| **企业微信（WeCom）** | 群机器人 Webhook（出站） | 出站否 / 入站需回调 | 先做通知与审批出站；双向对话需中继 |
| **本地 / 局域网 Web 控制台 + PWA** | 浏览器访问 Sage Web UI | 否 | 零第三方依赖，最稳的离线方案 |
| QQ（NapCat / OneBot） | 本地 WebSocket | 否 | 实验性、非官方，可选 |

**国际平台降级**：Telegram / Discord / Slack 归入「国际平台（需外网）」实验分组，
默认隐藏，仅保留给有代理条件的用户；不做主动推广。

**参考主流应用：**

- ChatGPT Desktop / Cursor：默认不做 IM 网关，以本地应用 + 移动端远程访问为主；
- Claude Code：提供 CLI / Web / IDE 远程会话，不绑定第三方 IM；
- 豆包 / 通义 / Kimi：企业场景优先集成飞书、钉钉、企业微信；
- hermes-agent 类项目：Telegram/WhatsApp 网关面向海外网络环境。

因此 Sage 的定位应是：**本地优先 + 可选连接器**，IM 网关不是默认能力。

### Win7 / Python 3.8 适配约束

- 新增依赖必须支持 Python 3.8：`lark-oapi`、`dingtalk-stream`、`websockets<14` 需在 `sage-backend-py38` 实测；
- 不使用原生扩展依赖；HTTP 统一走 `httpx==0.26.0` + `certifi`；
- 所有网络调用显式设置 connect/read timeout；
- 长连接断线重连使用指数退避 + 抖动，禁止 0 延迟重连；
- CI 覆盖 py38（`release/win7`）与 py310（`main`）两套环境。

---

## 4. 实施步骤

- [x] M1：后端 `_normalize_ids` + 未配置返回 200（含 3 平台测试）
- [x] M2：前端 `useMemo` 稳定 `api` + 防重入 + 挂载只请求一次（含回归测试）
- [x] M3：网关分组默认折叠 / feature flag，折叠时不挂载
- [x] M4：`GatewaySupervisor` 动态启停，去掉 `restart_required`
- [ ] M5：飞书长连接 adapter
- [ ] M6：钉钉 Stream adapter
- [ ] M7：企业微信群机器人出站（通知 / 审批）
- [ ] M8：本地 / 局域网 Web 控制台 + PWA 可行性评估
- [ ] M9：py38 / Win7 适配与 CI（改动文件已过 ruff + py38 AST 检查，待 CI 双环境验证）
- [ ] M10：更新 `docs/technical/32-telegram-gateway.md` 并归档本计划

> 双分支策略：先在 `release/win7` 实施并验证，再 cherry-pick 到 `main`；
> 涉及 py38 的依赖改动不反向同步到 main 的 requirements。

---

## 5. 风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| 飞书/钉钉 SDK 在 py38 或 Win7 不兼容 | 国内平台无法交付 | M5/M6 前先做 30 分钟 spike 验证 import + 长连接 |
| 企业 IM 需要管理员开通应用权限 | 用户无法自助配置 | 提供权限清单 + 分步向导 |
| 长连接在企业代理/防火墙下被阻断 | 功能不可用 | 显示 `unreachable`，给出代理配置入口 |
| 前端循环修复遗漏其他组件 | 类似风暴复现 | 全仓搜索 `useCallback(...[api])` / 每次渲染新建对象的模式 |
| 双分支版本漂移 | Win7 与 main 行为不一致 | 先 win7 后 main，cherry-pick 时跑两套测试 |

---

## 6. 验收标准

1. 打开设置页，网关折叠时**前端零请求**；展开后每个平台仅 1 轮请求（3 次），不重复；
2. 未配置平台的 config / status / binds 均返回 200，日志无 TypeError 堆栈；
3. 未启用 / 未配置时后端无网关轮询线程、无出站请求；
4. Win7 设置页停留 10 分钟，CPU 与内存平稳，日志无异常堆积；
5. 飞书或钉钉长连接在 Win7 实机可收发消息、可完成一次远程审批；
6. `pytest`（py38 + py310）与 `vitest` 全绿，新增测试覆盖上述回归点。
