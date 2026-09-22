# MCP 会话交付物：Arena P1 协议注册层落地与真实冒烟记录

- 日期：2026-09-19
- 关联文档：`docs/mcp-aren-card-port-plan.md`（方案 §5.4/§5.5/§5.8/§5.10/§8-P1）、`docs/mcp-arena-p0-verification.md`
- 范围：`arena_http` + `arena_protocol`（注册 + 抽卡协议）+ `arena_trace_ext` + `arena_jobs` + `arena_registration` + 注册 API + 导出；真实冒烟（注册 ×3、token 受理）
- 结论：**P1 验收达成**——单测/集成全绿（远端 arena 套件 163 passed）；真实注册 **3/3 成功**（并发 3、17 秒、零邮箱超时、额度回写）；**S0-B token 受理闭环**（Electron/21.4.4 V3 token 被 create-chat 接受）。附带两个新实测发现（§4）。

## 0. 结论速览

| 项 | 结果 | 证据 |
| --- | --- | --- |
| P1 单测/集成（远端，sage-backend py3.11.16） | **163 passed, 1 skipped**（79s） | §2.2 命令；skip 为 curl_cffi 已装时正确的跳过分支 |
| 沙箱预验证（推远端前，py3.13 最小包树） | 116 passed | 本地 verify 树 |
| 真实注册冒烟（count=3, concurrency=3） | **3/3，耗时 17s**，额度 15000×3 回写，真实池 accounts_total=3 | `.tmp-arena-p1/register_log.txt` |
| V3 token 受理（create-chat） | **成功 1 次**（`sid=01a0b7d7-…`，mint 后 2s 使用） | `.tmp-arena-p1/token_log.txt` |
| 同窗口第二次出票受理 | **被拒**（HTTP 403 recaptcha rejected）→ 拒绝率待 P3 量化 | `.tmp-arena-p1/trace_log.txt` |
| `read_run_token`（SSE → public-access-token） | **90s 未见帧**——待 P4 前置诊断（见 §4.2） | token_log.txt |

## 1. 交付清单（文件级）

| 文件 | 动作 | 要点 |
| --- | --- | --- |
| `backend/services/arena_http.py` | 新增 | D3 反转落地：**httpx 默认**（S0 实测过 CF），curl_cffi 可选后端（未装时报可读错误）；`SessionLike` 鸭子类型（get/post/patch/delete/request/stream_get/close）；代理 kwarg 跨 httpx 版本兼容（`proxy=`→`proxies=` 回退）；`arena_headers()` 无 UA（纪律 2）；`request_with_retry()` 只重试传输错误、透传 HTTP 状态（纪律 7，退避 1.5×(i+1)） |
| `backend/services/arena_protocol.py` | 新增 | 常量区（方案附录 A）；`ArenaRegisterClient`（6 步注册）；`ArenaDrawClient`（登录/create-chat/trigger-token/SSE read_run_token/rename/archive/delete/fetch_run_events/fetch_span_detail/read_usage）；`register_one()`（async，邮箱直连+每账号独立 session；set-password 偶发失败重试一次）；`gen_password`/`validate_password`；异常分层 `ArenaProtocolError`/`ArenaRateLimited(cf=)`/`ArenaCaptchaRejected`；`is_cf_challenge()` |
| `backend/services/arena_trace_ext.py` | 新增 | 纯解析：`extract_internal_names`（modelName 扫描）、`parse_tier`、`model_matches`（非法正则退化转义）、`extract_usage`（usage span 顶层字段权威 / stream span 点号路径弱证据）、`span_ids`、`parse_models`（复用 `run_trace_resolver.extract_models_from_trace`，方案附录 C #1） |
| `backend/services/arena_jobs.py` | 新增 | `JobStore`/`Job`/`JobEvent`：线程安全、`deque(maxlen=5000)` 有界、`seq` 单调、`to_ndjson()`、stop_event、snapshot——NDJSON `?after_seq=` 续传的数据源（非 EventHub，方案附录 C #2） |
| `backend/services/arena_registration.py` | 新增 | `start_job()`：manager daemon 线程 + ThreadPoolExecutor(1-5)；max_accounts 钳制/拒绝；成功→`create_account(source="registered")`+`update_credits(user_id)`；事件不含密码（`RegisterResult.to_dict()` 脱敏）；`export_accounts()`→`${data_dir}/accounts_*.txt`（`邮箱----密码----额度`，绝不写仓库树，方案 §10.2） |
| `backend/api/arena_routes.py` | 扩展 | 注册 API：`POST /registration/jobs`(202)/`GET …/jobs`/`{id}`/`{id}/results`(显式明文端点，§10.1)/`{id}/stop`/`{id}/export`(FileResponse)；通用 `GET /jobs/{id}/events?after_seq=` NDJSON 流（照 `orch_run_control.py:91` 契约）；全部 `def` 路由走线程池；子能力 403 门控 |
| `.gitignore` | 修订 | `.tmp-arena-s0/` → `.tmp-arena-*/`（P1+ 冒烟产物同样不入库） |
| 测试 ×5 | 新增 | `test_arena_http.py`（MockTransport/重试/UA 纪律/curl_cffi 分支双条件跳过）、`test_arena_trace_ext.py`、`test_arena_protocol.py`（注册 6 步脚本化、SSE 帧解析含坏帧过滤、429/CF/验证码异常、usage 权威性）、`test_arena_jobs.py`（seq 单调/线程安全）、`test_arena_registration.py`（job 生命周期/停止/钳制/导出格式/API 门控/NDJSON 续传） |

## 2. 验证

### 2.1 单测纪律事故与修复

沙箱预跑曾暴露一个测试设计 bug：`test_register_one_mail_timeout_is_error_not_crash` 未注入 `session_factory`，导致 `register_one` 走了**真实 arena.ai 请求**（违反方案 §9「单测不得真连网」）。已修复为强制注入 MockTransport，并顺带获得一个真实观测（见 §4.3）。

### 2.2 远端测试

```bash
python -m pytest -q -p no:cacheprovider --no-header \
  backend/tests/unit/services/test_arena_{accounts,accounts_migration,keystore,http,trace_ext,protocol,jobs,registration}.py \
  backend/tests/unit/services/test_{machine_id,arena_automation_config,tenminmail,arena_adapter,arena_observation}.py \
  backend/tests/unit/api/test_arena_{routes,capabilities}.py \
  backend/tests/integration/test_arena_registration_flow.py
```

**163 passed, 1 skipped**（79s）。skip = `test_curl_cffi_missing_raises_readable_error`（远端装有 curl_cffi，该错误分支不可达，属预期）；构造分支测试在远端实际执行。P0 的 102 项全部包含在内，无回退。

全量 `backend/tests/unit` 回归仍在后台跑（直写 `.tmp-arena-s0/unit_all.txt`，含 `--durations=15`），结果出来后补录（此前一次运行被 Ctrl+C 中断且管道缓冲吞了输出，已改为直重定向）。

## 3. 真实冒烟（用户已批准的批量注册范围，住宅 IP）

### 3.1 注册（`.tmp-arena-p1/smoke_register.py`，走完整 job 链路）

- 参数：count=3, concurrency=3, mail_timeout=120s，真实 `ArenaAccountService`（`backend/data/arena/`，master.key 派生密钥——与后端 App 同池）。
- 结果：**3/3 成功，job 总耗时 17s**（04:03:06→04:03:23），邮箱 4~6s 到达（dbwot.com），额度 15000×3，user_id 回写，`accounts_total=3`。
- 事件流（27 条）含 log/register_result/progress/done，事件内无密码；导出格式在单测中验证。
- 与参考实测对齐：参考记录「单账号 15~30s、并发 3~5、瓶颈是邮件」，本机邮箱到达显著更快。

### 3.2 token 受理（mint.cjs → smoke_token.py）

- mint：ready 18.2s（含页面加载），出票 19.4s，`token_len=2489`，UA 含 `Electron/21.4.4`。
- 使用：mint 后 **2s** 内登录 + create-chat → **200，`sid=01a0b7d7-190b-7bd2-97f9-def0ee67e8df`**。
- **S0-B 闭环：Electron 21 隐藏窗口出的 reCAPTCHA Enterprise V3 token 被 arena create-chat 接受。** 协议抽卡路径成立（方案 §8 S0 验收①）。
- 处置：会话按默认 miss_action 归档成功（archive=true）。

### 3.3 第二次出票（smoke_trace.py，诊断 read_run_token 用）

- 新 token（len=2617，同 partition 常驻窗口二次出票）→ create-chat **HTTP 403，响应体含 recaptcha** → `ArenaCaptchaRejected`。
- 解读：**单窗口连续出票存在拒绝样本**。参考项目同样记录过 reCAPTCHA 拒绝（被拒→等 10s 换新 token、全局拒绝计数→熔断）。接受率需 P3 验收项（连续出票 20 次）量化；UA 覆盖评估（Electron/21.4.4 UA）仍是 P3 必做项。
- 该次无会话产生（create-chat 即失败），无需处置。

## 4. 新实测发现（影响后续阶段）

1. **create-chat token 接受率非 100%**：成功 1 / 拒绝 1（样本 2，无法给率）。P3 的 token 窗口必须实现参考的拒绝对策（换 token 重试、拒绝计数、熔断 + 建议换出口 IP）；P4 引擎已预留 `ArenaCaptchaRejected` 语义。
2. **`read_run_token` 90s 未见 public-access-token 帧**（第一次成功会话上）。两个候选原因：a) 移植时加严——参考实现不过滤 claims，我按方案 §5.5 加了 `validate_jwt_claims` 过滤，真实帧的 claims 可能不过检；b) 订阅时机/帧格式差异。**P4 前置**：用成功会话采集真实 `/out` 帧存 fixture（方案 §9 本就要求 `out-stream.sse`），必要时放宽过滤（与参考对齐：抓到 header 即返回）。
3. **magic-link 54s 限速 = 数据中心 IP 现象**：沙盒（云 IP）连打 sign-up+magic-link 收到 `{"error":"For security purposes, you can only request this after 54 seconds."}`；用户住宅 IP 并发 3 全部即时通过。后续若在服务器/代理环境部署需注意。
4. 单测不连网红线靠 review 兜底：`register_one` 默认参数会构造真实 session，测试必须显式注入 `session_factory`（已在测试中加注释说明）。

## 5. 冒烟产物（均已 gitignore，含敏感信息，不入库）

| 路径 | 内容 |
| --- | --- |
| `.tmp-arena-p1/register_log.txt` | 注册 job 事件流（无密码） |
| `.tmp-arena-p1/register_results.json` | 3 账号邮箱/密码/额度（后续 P4 冒烟用；用毕可删） |
| `.tmp-arena-p1/token_log.txt` / `trace_log.txt` | token 受理成功 / 拒绝两份原始日志 |
| `.tmp-arena-p1/mint*.txt` | Electron 出票日志 |
| `.tmp-arena-p1/token.json` | 完整 token（**已删除**，2 分钟生命周期) |

真实账号池状态：`backend/data/arena/arena.sqlite` 含 3 个 `source="registered"` 账号（各 15000 额度），`capabilities.data.accounts_total=3`。

## 6. 后续

- **P2 代理子系统**（`arena_proxy_relay` + `arena_proxies` + rebind + `/proxies/*` API）。
- **P3 token 窗口**：出票拒绝对策 + 接受率量化（20 连发）+ UA 覆盖评估。
- **P4 抽卡引擎**：前置解决 §4.2 read_run_token 帧格式；门闸/429 阶梯/换 IP/熔断。
- 全量 unit 回归结果补录本文档（后台运行中）。
