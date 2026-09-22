# MCP 会话交付物：Arena 移植 S0 验证 + P0 落地记录

- 日期：2026-09-19
- 关联文档：`docs/mcp-aren-card-port-plan.md`（实现方案 v2，下称「方案」）
- 范围：S0 可行性验证（已闭案）+ P0 wiring/keystore 全部落地与验证
- 结论：**S0 通过（含一次设计反转 D3）**；**P0 完成**——远端 arena 测试套件 102 passed，后端启动 smoke 通过，`master.key` 泄露风险已用 `.gitignore` 规则封堵。

## 0. 结论速览

| 项 | 结果 | 证据 |
| --- | --- | --- |
| S0-B Electron 隐藏窗口出 reCAPTCHA V3 token | **PASS** | `.tmp-arena-s0/result.json`（token_len=2596，二次出票 ok） |
| S0-A HTTP 指纹归因（httpx vs curl_cffi） | **闭案**：httpx 可用，curl_cffi 被本机网络环境封死 | `.tmp-arena-s0/probe2.py` / `probe3.py` 输出 |
| P0 代码落地（12 文件） | **完成** | 见 §2 清单 |
| 远端 arena 测试套件（11 个文件，含既有回归） | **102 passed**（44.8s，sage-backend py3.11.16） | §3.1 命令与输出 |
| `backend.main` 导入 + 路由/接线自检 | **PASS** | §3.2 |
| 后端真实启动 smoke（uvicorn :8799） | **PASS**：`GET /api/v1/arena/capabilities` → 200 | §3.3 |
| `master.key` / WAL 边车可被提交的泄露风险 | **已修复**（`.gitignore`） | §3.4 |

## 1. S0 可行性验证（已闭案）

### 1.1 token 窗口出票（S0-B）

- 载体：Electron 21.4.4（Chromium 106.0.5249.199 / node 16.16.0），`--no-sandbox` 隐藏窗口加载 arena 注册页。
- 结果：reCAPTCHA **Enterprise V3** token 出票成功，`token_len=2596`（head `0cAFcWeA57jRSQzb0XAT`），同窗口二次出票 2468 亦成功；含页面加载共 28.6s。
- 遗留 caveat：UA 含 `Electron/21.4.4`（参考实现用 WebView2 = 纯 Chrome UA）。**P3 必须评估 UA 覆盖**（方案 §5.9）。
- token 的 arena 侧受理验证需要真实账号，划入 P1 smoke（方案 §8）。

### 1.2 HTTP 指纹归因（S0-A）

在本机（住宅 IP）实测，2026-09-19：

| 客户端 | 变体 | 结果 |
| --- | --- | --- |
| httpx 0.26.0 | HTTP/1.1 | `/api/me` → 401 `{"message":"User not found"}`（真实 JSON，过 CF） |
| httpx 0.26.0 | HTTP/2（装 h2 4.4.1 后） | 同上 401 JSON，过 CF |
| curl_cffi 0.16.3 | impersonate chrome131/124/120/110、safari17_0、edge101、不 impersonate；强制 H1 / H2 / 默认 H3 | **全部 403 CF challenge HTML**（连 `GET /` 都拦） |

结论：被 Cloudflare 拦的是 **curl_cffi 的 TLS 指纹本身**，与协议版本、UA 无关。

### 1.3 设计反转（更新方案 D3）

- HTTP 层默认 **httpx**（本仓库已 pin，且 Win7/py38 通道可用）；curl_cffi 降级为**可选 fallback**（代理/数据中心出口场景再试），保留可插拔后端 + 运行时 `capabilities` 探测（已落地，见 §2 `arena_routes.py`）。
- 默认 UA 保持 httpx 原生（诚实、实测可过），可配置。
- 环境变化：sage-backend 环境新增 `curl_cffi 0.16.3`、`h2 4.4.1`（本次验证安装）。

## 2. P0 落地清单（文件级）

| 文件 | 动作 | 要点 |
| --- | --- | --- |
| `backend/utils/machine_id.py` | 新增 | `sha256(hostname\|username\|machine-guid)`，UTF-8 `errors=replace`，模块级缓存 + `reset_cache()` 测试钩子；Windows 读 `MachineGuid`，Linux 读 `/etc/machine-id`，兜底 MAC |
| `backend/services/arena_keystore.py` | 新增 | **修复方案 §1.3-A**：随机 32B secret 持久化到 `<data_dir>/master.key`（原子写 0600），Fernet key = `derive_arena_key(master_secret, machine_id())`（§7.1 PBKDF2 480k 不变）；数据目录 `$SAGE_USER_DATA_DIR/arena`，退化 `backend/data/arena` |
| `backend/config/arena_automation.py` | 重写 | 子配置 `RegistrationConfig`/`DrawConfig`/`ProxyConfig`/`TokenWindowConfig`；`load_arena_config()` 缺文件/坏 yaml/未知键一律降级默认且 `enabled=False`（绝不 fail-open）；`extra=forbid`；pydantic v1 兼容写法 |
| `backend/config/arena_automation.yaml` | 新增 | 默认全关；中文注释含加载规则与键约束说明；`miss_action: archive`（用户决策 Q3） |
| `backend/services/arena_accounts.py` | 重写 | 幂等 `ALTER TABLE` 迁移（proxy/credits/draw 8 列）+ `arena_draws` 历史表；`get_account(include_secret=False)` 默认无密、`get_secret()` 显式取密、解密失败抛 `ArenaCredentialError` 而列表照常；单查询 `list_accounts`（修 N+1）；`count_accounts()`；`reserve_account(include_secret)`/`update_binding`/`update_credits`/`record_draw`/`list_draws` |
| `backend/services/temporary_mail/base.py` | 重写 | `Mailbox` 密码/令牌可选（catch-all 供应商无注册）；`wait_for_link()` 基类默认实现（`\u0026`→`&` 归一化，参考 `reference/ArenCard/arena_core.py:300-322`） |
| `backend/services/temporary_mail/tenminmail.py` | 新增 | JWT 从 `https://10minutemail.one/zh` 页面抓取（23h），API 401 → 刷新重试一次；catch-up 域名轮换（dbwot/ygwpr/imxwe）；**邮箱流量恒直连**（不走代理，参考实测）；本地名 10 字符随机 |
| `backend/services/temporary_mail/__init__.py` | 重写 | provider 注册表：`tenminmail` 可用；`mailtm` 声明未实现（可读报错） |
| `backend/api/arena_routes.py` | 重写 | 新增 `GET /capabilities`（flags/HTTP 后端/邮箱/数据目录自检，只读不 403）与 `GET /config`（**脱敏** api_token/pool_text/mail_api_key）；`shutdown_arena_service()`；既有端点保持 403/503 门控 |
| `backend/main.py` | 3 处接线 | `_init_arena(app)`（scheduler 之后，**永不抛出**）+ `_shutdown_arena()`（`_shutdown_repl_cleanups()` 之后）+ 模块级两个 helper；`app.state.arena_accounts`/`arena_config` |
| `.gitignore` | 补规则 | `backend/data/arena/`、`.tmp-arena-s0/`（见 §3.4） |
| 测试（7 文件，下表） | 新增/修改 | 远端合计 102 passed |

测试文件：

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/unit/services/test_machine_id.py` | 公式、缓存、组件失败全吞、平台回退 |
| `backend/tests/unit/services/test_arena_keystore.py` | 创建/稳定/重建、权限、**跨重启可解密**（P0 bug 回归）、换机器不可解、目录解析顺序 |
| `backend/tests/unit/services/test_arena_accounts_migration.py` | 旧库就地迁移幂等、`arena_draws`、绑定/额度/抽卡计数、默认投影无密、错钥降级 |
| `backend/tests/unit/services/test_arena_automation_config.py` | 缺失/坏 yaml/非映射/未知键/越界全降级且关闭；合法全解析；**仓库默认 yaml 必须解析且全关** |
| `backend/tests/unit/services/test_tenminmail.py` | 全部 httpx MockTransport：JWT 抓取一次、域名轮换、`\u0026` 归一化、401 刷新重试、超时返回 None、注册表 |
| `backend/tests/unit/api/test_arena_capabilities.py` | capabilities 禁用/未初始化也 200、子 flag 联动、密钥不可读时如实上报、config 脱敏 |
| `backend/tests/unit/services/test_arena_accounts.py` | 既有用例 + `test_create_account_round_trip` 改为 `include_secret=True`（方案 R9，默认投影不再含密码） |

## 3. 验证结果

### 3.1 远端 pytest（sage-backend，py3.11.16）

命令（conda `sage-backend` 的 python，repo 根目录）：

```bash
python -m pytest -q -p no:cacheprovider --no-header \
  backend/tests/unit/services/test_arena_accounts.py \
  backend/tests/unit/services/test_arena_accounts_migration.py \
  backend/tests/unit/services/test_arena_keystore.py \
  backend/tests/unit/services/test_machine_id.py \
  backend/tests/unit/services/test_arena_automation_config.py \
  backend/tests/unit/services/test_tenminmail.py \
  backend/tests/unit/api/test_arena_routes.py \
  backend/tests/unit/api/test_arena_capabilities.py \
  backend/tests/unit/services/test_arena_adapter.py \
  backend/tests/unit/services/test_arena_observation.py \
  backend/tests/integration/test_arena_registration_flow.py
```

结果：**102 passed**（44.77s，28 warnings——均为既有 pydantic v1 风格弃用告警，与本改动无关的照旧，`arena_routes.py` 的 `.dict()` 已做 v1/v2 双兼容）。首轮唯一失败是 `test_master_key_file_is_owner_only` 在 Windows 上断言 POSIX 0600，已改为平台分支断言（Windows chmod 仅映射只读位，真实防护是文件位于用户目录 + 后续 DPAPI，方案风险表有跟踪）。全量 `backend/tests/unit` 回归另跑一轮，结果记录于 `.tmp-arena-s0/unit_all.txt`。

沙箱预验证（推送到远端前，py3.13 + fastapi 0.141 + cryptography 50.0.1 组装最小包树）：55 passed——用于提前拦截语法/逻辑错误，最终以远端为准。

### 3.2 导入与接线自检

`python -c "import backend.main ..."`：

- `import ok`
- `arena router mounted: True`（`/api/v1/arena/capabilities` 在 `app.routes` 中）
- `has _init_arena: True has _shutdown_arena: True`

### 3.3 启动 smoke（真实 uvicorn）

`SAGE_LOCAL_AUTH_TOKEN=smoke-arena-p0 PYTHON_BACKEND_PORT=8799 python -m backend.main`：

- 启动日志：`arena master key created at backend\data\arena\master.key` → `[sage-startup] t=13.7s arena complete` → `arena 账号池已初始化: enabled=False registration=False draw=False db=backend\data\arena\arena.sqlite`（feature 默认关，不影响启动）。
- `curl -H "Authorization: Bearer …" GET :8799/api/v1/arena/capabilities` → **200**（约 8s 后就绪），关键字段：

```json
{"initialized":true,"enabled":false,
 "flags":{"registration":false,"draw":false,"proxy":false,"token_window":false},
 "http":{"default_backend":"httpx","httpx_version":"0.26.0",
         "curl_cffi":{"installed":true,"version":"0.16.3"}},
 "mail":{"configured":"tenminmail","available":["tenminmail"],"declared":["mailtm","tenminmail"]},
 "token_window":{"available":false,"ready":false},
 "data":{"master_key_exists":true,"credentials_readable":true,"accounts_total":0}}
```

- 数据落盘：`backend/data/arena/{master.key, arena.sqlite, -shm, -wal}`，关停干净（进程 kill 后无残留占用）。

### 3.4 安全修复：`.gitignore`

smoke 后发现 `backend/data/arena/master.key`（Fernet 主密钥）、`arena.sqlite-wal/-shm` 均不在忽略规则内（`backend/data/*.sqlite` 只覆盖主库文件），`git status` 可见、可被误提交。已补：

```gitignore
backend/data/arena/
.tmp-arena-s0/
```

并用 `git check-ignore` 逐一复核四个路径全部 IGNORED。**若曾在无规则窗口期提交过 master.key，须视为泄露并轮换**（本仓库未提交过，无此问题）。

## 4. 已知限制与后续

- **P1**：`arena_http`（httpx 默认/可插拔）+ `arena_protocol`；单次真实注册 smoke；**token 受理验证**（S0 唯一未闭环项）。
- **P2**：抽卡引擎（create-chat/SSE/usage/内部名解析、门闸、429 阶梯、`miss_action=archive`）。
- **P3**：Electron token 窗口产品化 + **UA 覆盖评估**（Electron/21.4.4 UA 风险）。
- 风险 R5 语义已落地：换机器/丢 `master.key` → 解密抛 `ArenaCredentialError`，`capabilities.data.credentials_readable=false`，账号列表仍可用（UI 可解释）。
- `datetime.utcnow` 弃用告警来自既有 `Mailbox` dataclass 默认工厂，留待 P1 顺手清理。

## 5. 运维备注（踩坑记录）

- IDE 终端默认 `ELECTRON_RUN_AS_NODE=1`，跑 electron.exe 前必须 `unset`（S0 spike 首跑因此失败）。
- 仓库根 `package.json` `"type":"module"`，Electron 主进程脚本必须 `.cjs`。
- MCP 隧道为 Cloudflare 临时域名，URL 会过期；本次会话中途更换过一次（`env.sh` 已更新为当前 URL）。
- `run_command` 曾出现终端不返回导致后续命令排队的卡死，重启 ShunCode 桥接后恢复；探测脚本一律落盘到 `.tmp-arena-s0/` 再用 `read_files` 取回，不依赖命令回显。
- Windows 控制台中文输出按 GBK 落盘，读取时需转码（本次 smoke 日志即 GBK）。
