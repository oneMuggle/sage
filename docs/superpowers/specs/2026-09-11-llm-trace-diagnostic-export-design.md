# LLM 调用诊断包导出 — Design Spec

- **Date:** 2026-09-11
- **Branch:** `feat/llm-trace-diagnostic-export` (基于 `origin/release/win7`),cherry-pick 到 `main`
- **Status:** Draft,待用户 review
- **Author:** Claude (brainstorming with user)

## 1. 背景与目标

### 1.1 问题

Sage 即将部署到**内网 Windows 7 SP1 物理机**(`release/win7` 分支产物)。该环境的可调试性极差:

- **不能装 DevTools / IDE** — 现场用户没有管理员权限也没有开发环境
- **不能远程 shell** — 内网隔离,没有 SSH / RDP 直连
- **现场用户不是技术人员** — 出错时只能通过电话/工单与支持人员沟通
- **没有任何调用上下文落地** — 当前 `backend/api/llm_proxy_routes.py` (972 行) 仅 logger 元信息,**完全不落 request body / SSE response**,前端 UI 也不显示发出去的完整 messages

直接后果:2026-09-11 用户报告 `401 本地授权凭据无效` 的 session 里,无法判断「实际把请求转发到了哪个 URL」、「prompt 内容是否正确组装」、「上游返回了什么」。支持人员只能盲猜,反复 ping-pong 增加沟通成本。

### 1.2 目标

为现场用户提供**一键导出诊断包**能力,让支持人员在拿到 zip 后能离线分析:

1. **始终在内存采集最近 50 次 LLM 调用** — 用户无感,零磁盘写入
2. **手动触发的紧凑 zip 导出** — 托盘菜单 / 设置页双入口,默认保存到 Downloads
3. **自动脱敏 secrets** — Bearer / API key / token / password / jwt 等 10 类模式全覆盖
4. **可勾选保留 prompt 原文** — 默认不保留(只保留结构),勾选后才保留
5. **Win7 兼容** — 仅 stdlib 依赖,py38 + pydantic v1 + Electron 21 全支持
6. **双层防御** — recorder.append 时脱敏一次 + export 时再脱敏一次,redactor 单元测试守住 invariant「含 password=secret123 的 payload 导出后 grep 不到 secret123」

### 1.3 非目标 (YAGNI)

- ❌ **不自动上传** — 现场用户决定怎么发(邮件/IM/工单附件),系统不接触外网
- ❌ **不做实时 trace UI / 面板** — 现场用户不会看,支持人员在收到 zip 后离线分析
- ❌ **不做 zip 加密 / 密码** — 内网工单不需要;增加复杂度
- ❌ **不持久化到磁盘 / SQLite** — 「出错时点一下」语义不需要历史;重启即清空可接受
- ❌ **不替换 `electron/logger.ts` 已有的日志系统** — 本特性互补不重叠(electron-logging 解决启动问题,本特性解决 LLM 调用问题)
- ❌ **不引入新依赖** — 仅 stdlib(`collections.deque` / `zipfile` / `re` / `json` / `datetime` / `platform` / `io`)

## 2. 用户故事

- **US-1**(现场用户): 出错时右键托盘 → 「导出诊断包…」 → 选保存路径 → 把生成的 zip 拖到 IM 给支持人员。零学习成本。
- **US-2**(现场用户): 不信任托盘,可以进「设置 → 高级 → 诊断」看「目前已采集 12 条 LLM 调用」+ 勾选是否含 prompt → 点按钮导出。
- **US-3**(支持人员): 收到 zip 后,解压看 `manifest.json` 知道是哪个版本、看 `trace.jsonl` 找到 401 那一行、看到 `upstream_url` 立刻知道「哦用户把 URL 配错了」、看到 `Authorization: Bearer ***REDACTED:bearer***` 确认请求带 token 但被上游拒。
- **US-4**(支持人员): 如果想看 prompt 原文但用户没勾选,看到 `messages[].content = ***REDACTED:prompt***` 但仍能看到 `messages[].role` 和 `tool_calls.function.name`,判断「调用结构对不对」。
- **US-5**(QA): 在测试环境 mock 上游返回 401,触发导出,断言 zip 内 `response.status=401` 且 `upstream_url` 是测试 server 地址 — E2E 守护这条路径永不回归。

## 3. 架构

### 3.1 数据流总览

```
┌────────────────────────────────────────────────────────────────────┐
│ Frontend (Electron renderer)                                       │
│  - 托盘菜单「导出诊断包…」                                         │
│  - 设置页「诊断」卡片(含 preview)                                  │
│       │                                                            │
│       │ IPC: diagnostic:export / diagnostic:preview                │
│       ▼                                                            │
│ Electron main process                                              │
│  - dialog.showMessageBox (confirm includePrompts?)                 │
│  - dialog.showSaveDialog (默认 Downloads / 默认文件名)             │
│  - 调 backend POST /api/v1/diagnostic/export                       │
│  - 拿到 zip bytes → fs.writeFile → shell.showItemInFolder          │
│                                                                    │
│       │ HTTP (受 LocalAuthMiddleware 保护)                         │
│       ▼                                                            │
│ Backend (FastAPI)                                                  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ llm_proxy_routes.py                                          │  │
│  │   - _read_request_body() → tee 一份 → recorder.append(req)   │  │
│  │   - 上游响应 aiter_raw → tee 一份 → recorder.append(resp)    │  │
│  │   - 出口协议不变,纯旁路                                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│       │                                                            │
│       ▼                                                            │
│  backend/services/llm_trace/                                       │
│    recorder.py    (singleton, deque maxlen=50)                     │
│    tee.py         (aiter_raw tee 协程)                             │
│    redactor.py    (10 类 secrets pattern + JSON 递归)              │
│    exporter.py    (zip 组装:manifest/system/config/trace/README)   │
│       │                                                            │
│       ▼                                                            │
│  backend/api/diagnostic_routes.py                                   │
│    GET  /api/v1/diagnostic/preview                                 │
│    POST /api/v1/diagnostic/export?include_prompts=&include_hostname=│
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 recorder 始终在内存 — 零磁盘写入

- `LlmTraceRecorder` 是 backend 进程级单例(`backend/services/llm_trace/recorder.py`)
- `deque(maxlen=50)` 持有最近 50 条 `TraceRecord` 对象
- `recorder.append(record)` 是 CPython GIL 下原子操作,无锁
- 进程重启 → deque 清空(可接受,语义是「出问题时点一下」)
- **永不** 写本地日志文件 — 不污染用户机器

### 3.3 tee 在哪一层

只改一个文件:`backend/api/llm_proxy_routes.py`,在两个点 tee:

| 位置 | 当前行为 | 改动 |
|---|---|---|
| `_read_request_body(request)` | 读 bytes 给 httpx | 多 tee 一份到 `recorder.record_request(trace_id, method, url, headers, body)` |
| `_read_response_body_limited` / streaming | 读 upstream response body 给 caller | 流式路径用 `aiter_raw` tee;非流式路径 body 直接 copy |

**不改动**:`llm_client.py` / `chat/executors.py` / `agents/*` — 全部零接触。

## 4. 实现细节

### 4.1 模块清单

**新增**:
```
backend/services/llm_trace/
├── __init__.py
├── recorder.py          # LlmTraceRecorder singleton
├── tee.py               # tee_stream() 协程
├── redactor.py          # 10 类脱敏
├── exporter.py          # zip 组装
└── tests/
    ├── test_recorder.py
    ├── test_tee.py
    ├── test_redactor.py
    └── test_exporter.py

backend/api/diagnostic_routes.py
backend/tests/test_diagnostic_export_integration.py
backend/tests/e2e/test_diagnostic_401_journey.py

electron/main.ts (新增 IPC handler + tray menu item,合并到现有修改)
electron/preload.ts (暴露 window.sage.diagnostic.*)
src/features/diagnostic/
├── DiagnosticCard.tsx
├── ExportButton.tsx
├── useDiagnosticPreview.ts
└── __tests__/
```

**修改**:
```
backend/api/llm_proxy_routes.py    # 在 _read_request_body + streaming response 处 tee
backend/main.py                    # include_router(diagnostic_router)
electron/main.ts                   # tray menu + IPC handler
electron/preload.ts                # 暴露 IPC
src/pages/Settings.tsx             # 挂载 DiagnosticCard
```

### 4.2 数据契约 — trace 条目

`trace.jsonl` 每行一个 JSON 对象:

```json
{
  "trace_id": "uuid4",
  "ts": "2026-09-11T16:48:48.520Z",
  "endpoint": "/api/v1/chat/completions",
  "upstream_url": "https://internal-llm.company.com/v1/chat/completions",
  "upstream_method": "POST",
  "request": {
    "headers": {"Content-Type": "application/json", "Authorization": "Bearer ***REDACTED:bearer***"},
    "body_bytes": 1234,
    "body_json": {"model": "internal-llama3", "messages": [{"role": "user", "content": "..."}]},
    "body_parse_error": null
  },
  "response": {
    "status": 401,
    "headers": {"Content-Type": "application/json"},
    "streamed": false,
    "body_bytes": 56,
    "body_text": "{\"error\": {\"message\": \"Invalid API key\"}}",
    "body_truncated": false,
    "body_encoding": "utf-8",
    "error": "Invalid API key"
  },
  "duration_ms": 234,
  "error_class": "upstream_401"
}
```

### 4.3 zip 内部文件清单

```
diagnostic-<app_version>-<yyyymmdd-hhmmss>.zip
├── manifest.json     # schema 版本 / redactor 版本 / trace 条目数 / 生成时间
├── system.json       # os / python / electron / app version / hostname (按选项)
├── config.yaml       # config.yaml 快照(已脱敏)
├── trace.jsonl       # 最多 50 条,按时间倒序
└── README.txt        # 给支持人员看的人读说明:如何解压、字段含义
```

### 4.4 体积与截断策略

| 维度 | 限额 | 超限行为 |
|---|---|---|
| 单条 body 字节 | 512 KB | 追加 `<truncated: 512KB>` 标记,`body_truncated=true` |
| 单条 trace 总大小 | 1 MB | 只保留 headers + status + error_class,body 整段丢弃,标 truncated |
| 整个 zip | ≤5 MB | 50 条都满仍在预算内 |
| 导出条数 | 上限 50 | 不可配置 |
| 非 UTF-8 / gzip body | — | base64 存为 `body_b64`,`body_encoding="base64"` |

### 4.5 脱敏规则

| 模式名 | 匹配 | 替换 |
|---|---|---|
| bearer_header | `Authorization: Bearer <token>` | `Bearer ***REDACTED:bearer***` |
| api_key_query | URL 中 `api_key=` / `apikey=` / `key=` | `***REDACTED:api_key***` |
| openai_style_key | `sk-…`、`sk_live_…`、`gsk_…` | `***REDACTED:openai_key***` |
| jwt_token | `eyJ…eyJ….<sig>` | `***REDACTED:jwt***` |
| basic_auth_value | `Basic ` 开头 | `Basic ***REDACTED:basic***` |
| cookie_header | `Cookie:` / `Set-Cookie:` | `***REDACTED:cookie***` |
| password_field | JSON key `password` / `passwd` / `pwd` | `***REDACTED:password***` |
| token_field | JSON key `token` / `access_token` / `refresh_token` / `id_token` | `***REDACTED:token***` |
| api_key_field | JSON key `api_key` / `apikey` / `api-key` | `***REDACTED:api_key***` |
| secret_field | JSON key `secret` / `client_secret` | `***REDACTED:secret***` |

**Prompt 处理**(与用户的「自动脱敏 + 勾选保留 prompt」选择对齐):

- 默认(`include_prompts=false`):所有 `messages[].content` → `***REDACTED:prompt***`(保留 `role` / `tool_calls.function.name` / 长度)
- 勾选后(`include_prompts=true`):保留原文,但仍走 secrets 脱敏(prompt 内若含 token 也不外泄)

**双层防御**:recorder.append 时已脱敏一次 + export 时再脱敏一次,redactor 单元测试守住 invariant。

### 4.6 IPC 接口

| Channel | 方向 | 参数 | 返回 |
|---|---|---|---|
| `diagnostic:export` | preload → main | `{ includePrompts: bool, includeHostname: bool }` | `{ ok: true, path }` 或 `{ ok: false, code, error }` |
| `diagnostic:preview` | preload → main | `{}` | `{ count, oldestTs, newestTs, sampleUrls, version }` |

**错误码取值**:`dialog_cancelled` / `recorder_empty` / `backend_unreachable` / `zip_generation_failed` / `write_failed`。

### 4.7 后端 HTTP 端点

```
GET  /api/v1/diagnostic/preview
POST /api/v1/diagnostic/export?include_prompts=true&include_hostname=false
```

- 两者都受 `LocalAuthMiddleware` 保护(沿用 `SAGE_LOCAL_AUTH_TOKEN`,**不**为诊断接口开洞)
- export 端点**不**先在 backend 写文件再让 main 读 — 直接 `StreamingResponse(zip_bytes)` 让 Electron 拿到 buffer
- 避免 backend 临时文件清理问题(Win7 临时目录权限坑)

### 4.8 Electron 主进程流程

托盘菜单点击:
```
[1] dialog.showMessageBox confirm「将导出 12 条最近调用,是否包含原始 prompt?」
        │
        ▼
[2] 用户答是/否 → includePrompts 参数
        │
        ▼
[3] 调用 IPC → 后端 /api/v1/diagnostic/export
        │
        ▼
[4] 拿到 zip bytes → dialog.showSaveDialog(默认路径 Downloads,默认文件名 sage-diagnostic-<ver>-<ts>.zip)
        │
        ▼
[5] 用户选路径 → fs.writeFile → shell.showItemInFolder 自动打开资源管理器
        │
        ▼
[6] 成功 toast 显示路径
```

### 4.9 设置页入口(辅助,非主要入口)

```
┌─ 诊断                                              ┐
│  最近采集到的 LLM 调用:12 条                        │
│  时间范围:2026-09-11 14:00 – 16:48                  │
│  上游端点样本:internal-llm.company.com / 10.0.x.x   │
│                                                     │
│  ☐ 包含原始 prompt 内容(可能含业务敏感信息)         │
│  ☐ 包含本机主机名                                   │
│                                                     │
│  [导出诊断包…]                                      │
│                                                     │
│  说明:导出文件用于问题排查,不会自动上传。           │
│  即使默认脱敏,请人工 review 后再外发。              │
└─
```

位置:**设置 → 高级 → 诊断**(二级菜单)。

### 4.10 Py3.8 + Pydantic v1 双兼容

- 类型注解仅 `Optional[str]` / `Union[X, Y]`,**不用** PEP 604/585
- 模型序列化用 `.dict()`,**不用** `.model_dump()`(v1 兼容)
- `scripts/check_py38_compat.py` AST 扫描新代码必须 0 违规
- CI 中 py38 + pydantic v1 job 跑测试

## 5. 错误处理矩阵

| 场景 | 失败点 | 用户可见行为 | 后端动作 |
|---|---|---|---|
| save dialog 取消 | 用户点 Cancel | (静默,无 toast) | 返 `dialog_cancelled`,不弹错 |
| ring buffer 空 | deque 0 条 | 「尚未记录任何调用。可仅导出系统信息,是否继续?」 | 二次确认后允许导出空 trace.jsonl + system + config |
| 后端不可达 | 5xx / 超时 | 「无法连接 Sage 后端,请确认应用已启动」 | 提示「试着重启 Sage」 |
| zip 生成失败 | redactor 崩溃 / jsonl 损坏 | 「诊断包生成失败:{msg}。请附 backend/logs/sage_*.log 联系支持」 | 把 trace_id 写到日志便于 grep |
| 写文件失败 | fs.writeFile ENOENT/EACCES/ENOSPC | 「无法写入文件。请检查目标路径权限和磁盘空间」 | 提示重选路径(再开 save dialog) |
| 单条 body 超 1MB | 截断路径 | (不抛错) | 标 truncated,导出继续 |
| antivirus 拦截 zip | Win7 + 杀软启发式 | 写文件失败 → 走 `write_failed` 分支 | 同上 |

## 6. 测试策略

### 6.1 单元测试(强制,新文件在 `backend/services/llm_trace/tests/`)

| 文件 | 关键用例 |
|---|---|
| test_recorder.py | • ring buffer 上限 50,第 51 条挤掉第 1 条 • 并发 100 次 append 不丢(GIL 原子性) • append/get 时间有序 |
| test_tee.py | • aiter_raw tee 输出与原流字节相同 • 异常向上传播(不被 tee 吞) • EndOfStream 下游继续 |
| test_redactor.py | • 10 个 pattern 各 ≥3 个用例(正/负/边界) • JSON 递归:嵌套 dict、list 内 dict、unicode key • 非 string value(int/bool/null)不处理 • **不变性**:含 `password=secret123` 的输入,导出后 grep 不到 secret123 |
| test_exporter.py | • zip 内 5 个文件全部存在且顺序符合 §4.3 • manifest.json 字段完整 • 单条 body 超 512KB 走截断标 • 整 zip ≤5MB(50 条极端) • 0 条 trace 时仍能生成(只有 system + config) |

**覆盖率目标 ≥85%**(高于项目默认 80%,redactor 是安全关键路径)

### 6.2 集成测试

`backend/tests/test_diagnostic_export_integration.py`:

1. **Happy path** — mock httpx 上游返 200 + 简单 JSON body → `POST /export` → 解 zip 校验
2. **关键回归用例**(针对 2026-09-11 401 bug):
   - mock 上游返 401 + `{"error":{"message":"Invalid API key"}}`
   - 故意带坏 token 触发
   - 校验 zip 内 trace 条目:`response.status==401`、`upstream_url` 保留(正是诊断必需)、`Authorization: Bearer ***REDACTED:bearer***`
3. **Preview endpoint** — `GET /preview` 返 count 与 ts 范围正确
4. **认证缺失** — 缺 Authorization → 401(沿用 LocalAuthMiddleware,不破洞)

### 6.3 E2E(hermetic)

`backend/tests/e2e/test_diagnostic_401_journey.py`:

```
[1] 启动本地 aiohttp test server 模拟上游,返 401
[2] 启动 FastAPI backend(uvicorn fixture),LLM_BASE_URL 指 [1]
[3] 调 /api/v1/chat/completions 发一条消息
[4] 后端代理 401 透传
[5] 调 /api/v1/diagnostic/export → 解 zip
[6] 断言 zip 内 trace.jsonl 第一行:
    - upstream_url 含 test server 地址
    - response.status == 401
    - request.headers["Authorization"] 被脱敏
[7] 清理
```

加到 `scripts/e2e_journey.sh` 现有套件。

### 6.4 前端测试

| 文件 | 关键用例 |
|---|---|
| src/features/diagnostic/__tests__/ExportButton.test.tsx | 勾选状态序列化到 IPC 参数 • 3 种 code 各自显示对应文案 • 取消 save dialog 不报错 |
| src/features/diagnostic/__tests__/DiagnosticCard.test.tsx | preview 加载/成功/失败三种渲染 |
| electron/__tests__/diagnostic-ipc.test.ts | IPC handler 透传参数 • dialog_cancelled 短路 • 写盘失败抛 write_failed |

### 6.5 Win7 兼容测试

- `scripts/check_py38_compat.py` AST 扫描新代码 0 违规
- CI 中 py38 + pydantic v1 job 跑 `test_redactor.py` + `test_recorder.py` + `test_exporter.py` 全套
- 类型注解仅 `Optional[str]` / `Union[X, Y]`

### 6.6 手动验证清单(Win7 真机)

- [ ] 安装 `.exe` 到 Win7 SP1 x64
- [ ] 启动应用
- [ ] 触发一次 LLM 调用(正常 + 故意配错 URL 两种)
- [ ] 右键托盘 → 「导出诊断包…」
- [ ] confirm 对话框 → save dialog → 选 Downloads → 成功 toast
- [ ] 资源管理器自动打开 zip 所在目录
- [ ] 解压 zip,看 `manifest.json` / `system.json` / `trace.jsonl`
- [ ] 故意配错 URL 那一行:`response.status==401`、`upstream_url` 可见、prompt 被替换为 `***REDACTED:prompt***`
- [ ] 设置页 → 高级 → 诊断 卡片显示 count + 时间范围 + 上游端点样本
- [ ] 勾选「含 prompt」后再导一次,验证 messages[].content 保留原文

## 7. 分支同步

**符合项目「双分支长期共存」策略**(.claude/CLAUDE.md):

**Phase 1** — 在 `feat/llm-trace-diagnostic-export` 分支开发,目标 `release/win7`:
1. PR → release/win7,等 CI 全绿(Backend py38 + Electron build + Electron smoke)
2. 合并到 release/win7
3. 打 alpha 标签(沿用 `v0.4.9-alpha.N-win7` 体系)

**Phase 2** — Cherry-pick 到 `main`:
1. 单 commit cherry-pick,commit message 加 `(cherry picked from release/win7 commit <SHA>)`(`<SHA>` 由 `git cherry-pick -x` 自动填入)
2. 跑 ci.yml 的 Python 3.10 job + electron build job
3. 不需要 lockstep 版本号调整(本特性是新增,不与现有标签耦合)

**禁止**(项目级 CLAUDE.md 红线):
- ❌ 不在 main 上修改 `backend/requirements.txt` 后再 cherry-pick 到 win7(本特性无新依赖,但保持警惕)
- ❌ 不合并两个分支
- ❌ 不删除 release/win7

## 8. 风险

| 风险 | 缓解 |
|---|---|
| redactor 有 bug 导致 secrets 泄露 | 双层防御(recorder + export)+ 不变性单元测试 + security-reviewer agent 检阅 |
| ring buffer 内存压力 | 上限 50 × <1MB ≈ ≤5MB,远低于 Electron 已有内存占用 |
| 用户误传未脱敏 zip 给外部 | README.txt + 设置页免责声明「人工 review 后再外发」 |
| Win7 杀软拦截 zip | 默认文件名用 `sage-diagnostic-` 前缀,不显眼;失败走 write_failed 让用户换路径 |
| SSE 流式响应拼接耗时 | aiter_raw tee 是 byte-level,50 条 × 数十 KB 总耗时 <1s,可接受 |
| 后端未重启时用户升级了版本 | recorder 是内存态,无 schema 兼容问题;manifest.json 标 schema 版本给支持人员看 |
| py38 AST 扫描漏过 | CI 必跑(已确立 `scripts/check_py38_compat.py` 集成模式,见 PR #509) |
| Win7 self-hosted runner 不可用 | 6.6 手动验证清单 + 内部已有 Win7 真机测试人员 |

## 9. 实施里程碑(供 writing-plans 参考)

1. **M1** — `backend/services/llm_trace/recorder.py` + `tee.py` + 单元测试 + `llm_proxy_routes.py` 双点 tee 接线
2. **M2** — `backend/services/llm_trace/redactor.py` + 10 类模式 + 不变性单元测试 + 双层脱敏接线
3. **M3** — `backend/services/llm_trace/exporter.py` + 体积截断 + 单元测试
4. **M4** — `backend/api/diagnostic_routes.py` + `backend/main.py` include + 集成测试(含 401 回归用例)
5. **M5** — `electron/main.ts` IPC handler + tray menu item + `electron/preload.ts` + 单元测试
6. **M6** — `src/features/diagnostic/` 卡片 + 按钮 + 设置页挂载 + 单元测试
7. **M7** — E2E `test_diagnostic_401_journey.py` + 加到 `scripts/e2e_journey.sh`
8. **M8** — 文档:`docs/technical/NN-llm-trace-diagnostic.md` + 用户手册 + Win7 真机验证清单
9. **M9** — PR → release/win7 → CI 绿 → 合并 → 打 alpha tag
10. **M10** — Cherry-pick → main → CI 绿 → 合并

## 10. 验收标准

- [ ] `npm run typecheck:electron` 通过
- [ ] `npm run typecheck` 通过(前端 TS)
- [ ] `npm run lint` 通过
- [ ] `npm run test:run` 通过(redactor 覆盖率 ≥85%,其他 ≥80%)
- [ ] Backend pytest 全套通过,py38 job 全绿
- [ ] `scripts/check_py38_compat.py` 新代码 0 违规
- [ ] E2E `test_diagnostic_401_journey.py` 通过
- [ ] `electron:dev` 模式下,触发 LLM 调用 → 托盘导出 → 解 zip 看到 trace 正确
- [ ] `electron:build` 产物能跑(macOS / Linux dev 验证)
- [ ] Win7 真机:故意配错 URL → 导出 → 解压看到 `response.status==401` 且 `upstream_url` 正确
- [ ] cherry-pick 到 main 后,ci.yml py3.10 job + electron build job 全绿
- [ ] 不变性测试:含 `password=secret123` 的 payload → 导出后 `grep -c 'secret123'` 结果为 0

## 11. 开放问题(留待 implementation 阶段处理,不影响 spec 批准)

1. **设置页位置**:当前定「设置 → 高级 → 诊断」二级菜单。如果用户实测觉得不便,可平铺到首页或单独 tab。
2. **tray 菜单的 confirm 对话框**:当前用 Electron `dialog.showMessageBox` 模态弹窗。是否需要更精细的「三选项:导出不含 prompt / 含 prompt / 取消」,留待实现时确认。
3. **`includeHostname` 默认值**:当前为 false。若支持人员反馈「需要 hostname 才能去重同一台机器的多次报告」,可改 default。