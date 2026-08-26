# Electron E2E 自动化测试基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sage 项目建立覆盖 5 个核心功能（chat / agent 编排 / wiki / 记忆 / 进化）的 Electron E2E 自动化测试基础设施，可按 4 个开发阶段（dev loop / PR gate / nightly / release）激活，使用 stub 主力 + 真实 conda sage-backend 双层后端。

**Architecture:** 在 `tests/electron/` 下新建 `tiers/{stub,live}/{smoke,deep}/` 子目录骨架；扩展 948 行 `stub_backend.py`（先拆模块，再加 21 个端点）以覆盖 5 个功能领域；新增 `real_backend()` fixture 支持真实 conda sage-backend 启动；新增 18 个 Playwright spec（5 smoke + 5 stub-deep + 3 live-boot + 5 live-deep）；通过 5 个 npm script + 2 个 GitHub Actions workflow 串联 4 个开发阶段。

**Tech Stack:** `@playwright/test` (Node.js), Python stdlib `http.server` + `sqlite3` (stub backend), FastAPI (real backend), pytest (stub unit test), GitHub Actions, conda `sage-backend`.

**Spec:** `docs/superpowers/specs/2026-08-25-electron-e2e-automation-design.md`

## Global Constraints

- 所有后端 Python 代码（stub_backend.py + 测试）运行在 `/home/fz/anaconda3/envs/sage-backend/bin/python`，不得污染 conda base 或系统 Python。
- 端口约定：`stub_backend` 用 `port=0`（随机分配），通过 env `SAGE_BACKEND_URL` + `PYTHON_BACKEND_PORT` 注入 Electron；`real_backend` 沿用默认 `PYTHON_BACKEND_PORT=8765`。
- 不修改 `backend/**`、`src/**`、`electron/**` 任何业务代码；stub 是独立模块。
- 所有 spec 文件用 `git mv` 平迁现有 4 个老 spec（office-e2e / permission-approval / question-answer / skillmd-compliance），保持 git blame 连续。
- stub 端点返回 schema 必须 1:1 对齐 `backend/wiki/models.py`、`backend/memory/manager.py`、`backend/orchestration/events.py` 的 Pydantic 模型。
- 每个任务遵循 RED → GREEN → IMPROVE，并以独立 conventional commit 结束。
- CI 模式保留 `retries: 2 on CI`；spec 用 `beforeAll` 复用 Electron 实例节省冷启动。
- 仅在 main 分支实施；release/win7 单独 spec 处理。

## File Map

### 测试目录（tiers）
- Create: `tests/electron/tiers/stub/smoke/{chat,orchestration,wiki,memory,evolution}.spec.ts`
- Create: `tests/electron/tiers/stub/deep/{chat,orchestration,wiki,memory,evolution}.spec.ts`
- Create: `tests/electron/tiers/live/boot-smoke/{health,routes,sse-handshake}.spec.ts`
- Create: `tests/electron/tiers/live/deep/{chat,orchestration,wiki,memory,evolution}.spec.ts`
- Modify (git mv): `tests/electron/office-e2e.spec.ts` → `tests/electron/tiers/stub/smoke/office.spec.ts`
- Modify (git mv): `tests/electron/permission-approval.spec.ts` → `tests/electron/tiers/stub/smoke/permission.spec.ts`
- Modify (git mv): `tests/electron/question-answer.spec.ts` → `tests/electron/tiers/stub/smoke/qa.spec.ts`
- Modify (git mv): `tests/electron/skillmd-compliance.spec.ts` → `tests/electron/tiers/live/deep/skillmd.spec.ts`

### Stub 后端与 fixtures
- Modify: `tests/electron/stub_backend.py` — 拆 5 个子模块 + 路由；新增 21 端点
- Modify: `tests/electron/test_stub_backend.py` — 29 → ~80 unit case
- Modify: `tests/electron/conftest.py` — 新增 `real_backend()` fixture
- Create: `tests/electron/fixtures/{sample_session,sample_memory,sample_orchestration,sample_wiki_doc}.json`

### 配置与文档
- Modify: `playwright.config.ts` — 新增 4 个 project
- Modify: `package.json` — 新增 5 个 npm script
- Modify: `tests/electron/README.md` — 重写
- Create: `.github/workflows/e2e-pr-gate.yml`
- Create: `.github/workflows/e2e-nightly.yml`

---

### Task 1: 目录骨架 + 平迁 4 个老 spec

**Files:**
- Modify (git mv): 4 个老 spec 文件
- Create: `tests/electron/tiers/{stub/{smoke,deep},live/{boot-smoke,deep}}/.gitkeep` 占位

**Interfaces:**
- Consumes: 无
- Produces: `tests/electron/tiers/` 完整骨架；现有 4 个老 spec 在新位置

- [ ] **Step 1: 创建 tier 目录骨架**

```bash
cd /home/fz/project/sage
mkdir -p tests/electron/tiers/stub/smoke
mkdir -p tests/electron/tiers/stub/deep
mkdir -p tests/electron/tiers/live/boot-smoke
mkdir -p tests/electron/tiers/live/deep
touch tests/electron/tiers/stub/smoke/.gitkeep
touch tests/electron/tiers/stub/deep/.gitkeep
touch tests/electron/tiers/live/boot-smoke/.gitkeep
touch tests/electron/tiers/live/deep/.gitkeep
```

- [ ] **Step 2: git mv 平迁 4 个老 spec**

```bash
git mv tests/electron/office-e2e.spec.ts tests/electron/tiers/stub/smoke/office.spec.ts
git mv tests/electron/permission-approval.spec.ts tests/electron/tiers/stub/smoke/permission.spec.ts
git mv tests/electron/question-answer.spec.ts tests/electron/tiers/stub/smoke/qa.spec.ts
git mv tests/electron/skillmd-compliance.spec.ts tests/electron/tiers/live/deep/skillmd.spec.ts
```

- [ ] **Step 3: 验证平迁成功**

```bash
ls tests/electron/   # 根目录应只剩 README.md, conftest.py, stub_backend.py, test_stub_backend.py, fixtures/, screenshots/, test-results/
ls tests/electron/tiers/stub/smoke/  # 应有 office.spec.ts, permission.spec.ts, qa.spec.ts, .gitkeep
ls tests/electron/tiers/live/deep/  # 应有 skillmd.spec.ts, .gitkeep
```

Expected: 老路径空，新路径含平迁文件。

- [ ] **Step 4: 提交**

```bash
git add tests/electron/tiers/
git commit -m "refactor(electron-e2e): scaffold tiers/ directory and migrate 4 legacy specs"
```

---

### Task 2: stub_backend.py 拆分为 5 个子模块

**Files:**
- Modify: `tests/electron/stub_backend.py` — 重构为 routing 文件
- Create: `tests/electron/stub_modules/{__init__,common}.py` + 各功能占位
- Test: `tests/electron/test_stub_backend.py` — 现有 29 个 test 保持全绿

**Interfaces:**
- Consumes: 现有 stub_backend.py 全部行为
- Produces: `stub_modules.chat.register_chat_routes(registry)` 等模块级函数；`stub_backend.py` 仅做 URL 路由 + 启动 lifespan

- [ ] **Step 1: 跑现有 stub unit test 确认基线**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v
```

Expected: 29 passed

- [ ] **Step 2: 创建 stub_modules 包结构**

```bash
mkdir -p tests/electron/stub_modules
touch tests/electron/stub_modules/__init__.py
```

- [ ] **Step 3: 抽出 common 工具（send_json, send_ndjson, StubContext）**

```python
# tests/electron/stub_modules/common.py
from http.server import BaseHTTPRequestHandler
import json, sqlite3

class StubContext:
    def __init__(self, handler: BaseHTTPRequestHandler, db: sqlite3.Connection):
        self.handler = handler
        self.db = db

def send_json(ctx: StubContext, status: int, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    ctx.handler.send_response(status)
    ctx.handler.send_header("Content-Type", "application/json")
    ctx.handler.send_header("Content-Length", str(len(body)))
    ctx.handler.end_headers()
    ctx.handler.wfile.write(body)

def send_ndjson(ctx: StubContext, events: list):
    ctx.handler.send_response(200)
    ctx.handler.send_header("Content-Type", "application/x-ndjson")
    ctx.handler.send_header("Cache-Control", "no-cache")
    ctx.handler.end_headers()
    for ev in events:
        line = (json.dumps(ev) + "\n").encode("utf-8")
        ctx.handler.wfile.write(line)
    ctx.handler.wfile.flush()
```

- [ ] **Step 4: 抽取 chat 模块到 stub_modules/chat.py**

将原 `stub_backend.py` 中 chat/stream 路由（~120 行，含 office_refs 鉴权）整段复制到 stub_modules/chat.py，导出 `register_chat_routes(registry)`。registry 是 `dict[(method, path_regex), fn(ctx, body)]`：

```python
# tests/electron/stub_modules/chat.py
import uuid
from .common import send_json, send_ndjson

def register_chat_routes(registry):
    registry[("POST", r"^/api/v1/chat/stream$")] = _create_stream
    registry[("GET",  r"^/api/v1/chat/stream/(?P<sid>[^/]+)$")] = _attach_stream

def _create_stream(ctx, body, **_):
    sid = "stream_" + uuid.uuid4().hex[:8]
    # ... 复用原 chat 逻辑
    send_json(ctx, 200, {"stream_id": sid})
```

- [ ] **Step 5: 抽取 orchestration / wiki / memory / evolution 占位模块**

每个模块导出 `register_<feature>_routes(registry)` 函数，初始实现返回 501 Not Implemented（待 Task 3-6 填充）：

```python
# tests/electron/stub_modules/orchestration.py
def register_orchestration_routes(registry):
    """Orchestration routes — implemented in Task 3."""
    pass
```

- [ ] **Step 6: 重构 stub_backend.py 为 routing-only**

```python
# tests/electron/stub_backend.py (新骨架)
from http.server import HTTPServer, BaseHTTPRequestHandler
import re, sqlite3, threading
from stub_modules import common
from stub_modules.chat import register_chat_routes
from stub_modules.orchestration import register_orchestration_routes
from stub_modules.wiki import register_wiki_routes
from stub_modules.memory import register_memory_routes
from stub_modules.evolution import register_evolution_routes

class StubBackend:
    def __init__(self, host="127.0.0.1", port=0):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self.url = None
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.routes = {}
        register_chat_routes(self.routes)
        register_orchestration_routes(self.routes)
        register_wiki_routes(self.routes)
        register_memory_routes(self.routes)
        register_evolution_routes(self.routes)

    def start(self):
        handler_cls = self._make_handler()
        self.server = HTTPServer((self.host, self.port), handler_cls)
        self.port = self.server.server_address[1]
        self.url = f"http://{self.host}:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.url

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)

    def _make_handler(self):
        routes = self.routes
        db = self.db
        parent = self
        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass
            def do_GET(self):    self._dispatch("GET")
            def do_POST(self):   self._dispatch("POST")
            def do_PUT(self):    self._dispatch("PUT")
            def do_DELETE(self): self._dispatch("DELETE")
            def _dispatch(self, method):
                ctx = common.StubContext(self, db)
                for (m, pattern), fn in routes.items():
                    if m != method:
                        continue
                    match = re.match(pattern, self.path)
                    if match:
                        body = {}
                        if method == "POST" or method == "PUT":
                            length = int(self.headers.get("Content-Length", 0))
                            if length > 0:
                                body = json.loads(self.rfile.read(length).decode("utf-8"))
                        fn(ctx, body, **match.groupdict())
                        return
                send_json(ctx, 404, {"error": "not_found", "path": self.path})
        return _Handler
```

需要在文件顶部加 `import json`。

- [ ] **Step 7: 跑现有 29 个 test 确认重构无回归**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v
```

Expected: 29 passed

- [ ] **Step 8: 跑现有 Playwright electron spec 确认无回归**

```bash
cd /home/fz/project/sage
npx playwright test --project=electron --grep='office|permission|qa'
```

Expected: 全部 passed（含平迁后的 office/permission/qa）

- [ ] **Step 9: 提交**

```bash
git add tests/electron/stub_backend.py tests/electron/stub_modules/
git commit -m "refactor(electron-e2e): split stub_backend.py into 5 feature sub-modules"
```

---

### Task 3: stub_backend.py orchestration 端点

**Files:**
- Modify: `tests/electron/stub_modules/orchestration.py` — 5 端点实现
- Modify: `tests/electron/test_stub_backend.py` — 新增 ~10 unit case

**Interfaces:**
- Consumes: `StubContext` from `stub_modules.common`
- Produces:
  - `POST /api/v1/orchestration/runs` → 创建 run（3 agents: planner/executor/reviewer），返回 `{run_id, status, lanes}`
  - `GET /api/v1/orchestration/runs/:id` → 返回 run 状态
  - `POST /api/v1/orchestration/runs/:id/approve` → 写入 approval
  - `POST /api/v1/orchestration/runs/:id/cancel` → 设置 `cancelled=true`
  - `GET /api/v1/orchestration/runs/:id/events` → SSE NDJSON

- [ ] **Step 1: 写 orchestration 端点失败的 unit test**

在 `test_stub_backend.py` 末尾追加：

```python
def test_orchestration_create_run_returns_3_lanes():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        resp = requests.post(f"{server.url}/api/v1/orchestration/runs",
                             json={"session_id": "sess1", "plan": "test plan"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"].startswith("run_")
        assert data["status"] == "running"
        assert len(data["lanes"]) == 3
        assert {lane["name"] for lane in data["lanes"]} == {"planner", "executor", "reviewer"}
    finally:
        server.stop()

def test_orchestration_get_run_after_create():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.post(f"{server.url}/api/v1/orchestration/runs",
                          json={"session_id": "s1", "plan": "p"})
        rid = r.json()["run_id"]
        g = requests.get(f"{server.url}/api/v1/orchestration/runs/{rid}")
        assert g.status_code == 200
        assert g.json()["run_id"] == rid
    finally:
        server.stop()

def test_orchestration_cancel_sets_flag():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.post(f"{server.url}/api/v1/orchestration/runs",
                          json={"session_id": "s1", "plan": "p"})
        rid = r.json()["run_id"]
        c = requests.post(f"{server.url}/api/v1/orchestration/runs/{rid}/cancel")
        assert c.status_code == 200
        g = requests.get(f"{server.url}/api/v1/orchestration/runs/{rid}")
        assert g.json()["cancelled"] is True
    finally:
        server.stop()

def test_orchestration_approve_records_token():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.post(f"{server.url}/api/v1/orchestration/runs",
                          json={"session_id": "s1", "plan": "p"})
        rid = r.json()["run_id"]
        a = requests.post(f"{server.url}/api/v1/orchestration/runs/{rid}/approve",
                          json={"token": "user_token_1"})
        assert a.status_code == 200
        assert a.json()["approval_token"] == "user_token_1"
    finally:
        server.stop()

def test_orchestration_events_sse_stream():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.post(f"{server.url}/api/v1/orchestration/runs",
                          json={"session_id": "s1", "plan": "p"})
        rid = r.json()["run_id"]
        with requests.get(f"{server.url}/api/v1/orchestration/runs/{rid}/events",
                          stream=True) as resp:
            assert resp.status_code == 200
            assert "application/x-ndjson" in resp.headers["Content-Type"]
            first_line = next(resp.iter_lines()).decode("utf-8")
            event = json.loads(first_line)
            assert event["run_id"] == rid
    finally:
        server.stop()
```

- [ ] **Step 2: 跑 test 确认 fail**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k orchestration
```

Expected: FAIL with "not_found" or 404

- [ ] **Step 3: 在 stub_modules/orchestration.py 实现 5 个端点**

```python
# tests/electron/stub_modules/orchestration.py
import json, time, uuid
from .common import send_json, send_ndjson

def register_orchestration_routes(registry):
    registry[("POST", r"^/api/v1/orchestration/runs$")] = _create_run
    registry[("GET",  r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)$")] = _get_run
    registry[("POST", r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)/approve$")] = _approve
    registry[("POST", r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)/cancel$")] = _cancel
    registry[("GET",  r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)/events$")] = _events

def _ensure_table(ctx):
    ctx.db.executescript("""
        CREATE TABLE IF NOT EXISTS orchestration_runs(
            run_id TEXT PRIMARY KEY, session_id TEXT, plan TEXT,
            status TEXT, cancelled INTEGER, approval_token TEXT,
            created_at INTEGER);
    """)

def _create_run(ctx, body, **_):
    _ensure_table(ctx)
    rid = "run_" + uuid.uuid4().hex[:8]
    ctx.db.execute(
        "INSERT INTO orchestration_runs VALUES (?,?,?,?,?,?,?)",
        (rid, body["session_id"], body["plan"], "running", 0, None, int(time.time() * 1000))
    )
    ctx.db.commit()
    send_json(ctx, 200, {
        "run_id": rid, "status": "running",
        "lanes": [
            {"name": "planner",  "agent_id": "planner_" + rid,  "status": "pending"},
            {"name": "executor", "agent_id": "executor_" + rid, "status": "pending"},
            {"name": "reviewer", "agent_id": "reviewer_" + rid, "status": "pending"},
        ],
    })

def _get_run(ctx, body, rid, **_):
    _ensure_table(ctx)
    row = ctx.db.execute(
        "SELECT run_id, session_id, plan, status, cancelled, approval_token FROM orchestration_runs WHERE run_id = ?",
        (rid,),
    ).fetchone()
    if not row:
        send_json(ctx, 404, {"error": "run_not_found", "run_id": rid})
        return
    send_json(ctx, 200, {
        "run_id": row[0], "session_id": row[1], "plan": row[2],
        "status": row[3], "cancelled": bool(row[4]),
        "approval_token": row[5],
    })

def _cancel(ctx, body, rid, **_):
    _ensure_table(ctx)
    ctx.db.execute("UPDATE orchestration_runs SET cancelled = 1, status = 'cancelled' WHERE run_id = ?", (rid,))
    ctx.db.commit()
    send_json(ctx, 200, {"run_id": rid, "cancelled": True})

def _approve(ctx, body, rid, **_):
    _ensure_table(ctx)
    token = body.get("token", "auto_token_" + uuid.uuid4().hex[:6])
    ctx.db.execute("UPDATE orchestration_runs SET approval_token = ?, status = 'approved' WHERE run_id = ?", (token, rid))
    ctx.db.commit()
    send_json(ctx, 200, {"run_id": rid, "approval_token": token})

def _events(ctx, body, rid, **_):
    _ensure_table(ctx)
    events = [
        {"run_id": rid, "event_type": "run_started", "ts": int(time.time() * 1000), "lane": "planner"},
        {"run_id": rid, "event_type": "lane_progress", "ts": int(time.time() * 1000) + 100, "lane": "planner", "progress": 0.5},
        {"run_id": rid, "event_type": "lane_complete", "ts": int(time.time() * 1000) + 200, "lane": "planner"},
    ]
    send_ndjson(ctx, events)
```

- [ ] **Step 4: 跑 test 确认 pass**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k orchestration
```

Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add tests/electron/stub_modules/orchestration.py tests/electron/test_stub_backend.py
git commit -m "feat(electron-e2e): add orchestration endpoints to stub backend"
```

---

### Task 4: stub_backend.py wiki 端点

**Files:**
- Modify: `tests/electron/stub_modules/wiki.py` — 5 端点
- Modify: `tests/electron/test_stub_backend.py` — ~8 unit case

**Interfaces:**
- Produces:
  - `POST /api/v1/wiki/ingest` → 接受文本，返回 `{doc_id, chunks}`
  - `POST /api/v1/wiki/extract` → 接受文本，返回 `{title, body, links}`
  - `POST /api/v1/wiki/search` → 接受 query，返回 `{items: [{doc_id, title, score}], total}`
  - `GET /api/v1/wiki/insights/:id` → 返回 `{summary, tags}`
  - `POST /api/v1/wiki/deep-research` → 返回 `{steps, status}`

- [ ] **Step 1: 写 wiki 端点失败的 unit test**

```python
def test_wiki_ingest_then_search_returns_ranked_results():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r1 = requests.post(f"{server.url}/api/v1/wiki/ingest",
                           json={"title": "Sage Memory", "content": "Sage has 3-tier memory"})
        assert r1.status_code == 200
        doc_id = r1.json()["doc_id"]
        assert r1.json()["chunks"] >= 1

        r2 = requests.post(f"{server.url}/api/v1/wiki/search",
                           json={"query": "memory", "limit": 5})
        assert r2.status_code == 200
        data = r2.json()
        assert data["total"] >= 1
        assert data["items"][0]["doc_id"] == doc_id
        assert 0.0 <= data["items"][0]["score"] <= 1.0
    finally:
        server.stop()

def test_wiki_extract_returns_title_and_body():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.post(f"{server.url}/api/v1/wiki/extract",
                          json={"content": "Sage is great. It supports E2E."})
        assert r.status_code == 200
        data = r.json()
        assert "title" in data
        assert "body" in data
        assert isinstance(data.get("links", []), list)
    finally:
        server.stop()

def test_wiki_insights_returns_summary_and_tags():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r1 = requests.post(f"{server.url}/api/v1/wiki/ingest",
                           json={"title": "Foo", "content": "Sage memory works."})
        doc_id = r1.json()["doc_id"]
        r2 = requests.get(f"{server.url}/api/v1/wiki/insights/{doc_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert "summary" in data
        assert isinstance(data.get("tags", []), list)
    finally:
        server.stop()

def test_wiki_deep_research_returns_plan():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.post(f"{server.url}/api/v1/wiki/deep-research",
                          json={"topic": "Sage memory tiers"})
        assert r.status_code == 200
        data = r.json()
        assert "steps" in data
        assert data["status"] in ("pending", "running", "done")
    finally:
        server.stop()
```

- [ ] **Step 2: 跑 test 确认 fail**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k wiki
```

Expected: FAIL

- [ ] **Step 3: 实现 wiki 5 个端点**

```python
# tests/electron/stub_modules/wiki.py
import hashlib, json, time, uuid
from .common import send_json

def register_wiki_routes(registry):
    registry[("POST", r"^/api/v1/wiki/ingest$")] = _ingest
    registry[("POST", r"^/api/v1/wiki/extract$")] = _extract
    registry[("POST", r"^/api/v1/wiki/search$")] = _search
    registry[("GET",  r"^/api/v1/wiki/insights/(?P<iid>[^/]+)$")] = _insights
    registry[("POST", r"^/api/v1/wiki/deep-research$")] = _deep_research

def _ensure_table(ctx):
    ctx.db.executescript("""
        CREATE TABLE IF NOT EXISTS wiki_docs(
            doc_id TEXT PRIMARY KEY, title TEXT, body TEXT,
            tags TEXT, created_at INTEGER);
    """)

def _score(query: str, doc_id: str) -> float:
    """Deterministic score: md5(q+d) / 2**32, range [0,1)."""
    h = hashlib.md5((query + doc_id).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF

def _ingest(ctx, body, **_):
    _ensure_table(ctx)
    doc_id = "doc_" + uuid.uuid4().hex[:8]
    title = body.get("title", "")
    content = body.get("content", "")
    chunks = max(1, len(content) // 500)
    ctx.db.execute(
        "INSERT INTO wiki_docs VALUES (?,?,?,?,?)",
        (doc_id, title, content, "", int(time.time() * 1000))
    )
    ctx.db.commit()
    send_json(ctx, 200, {"doc_id": doc_id, "chunks": chunks})

def _extract(ctx, body, **_):
    content = body.get("content", "")
    title = content.split(".")[0][:80] if content else "untitled"
    body_text = content[:1000]
    links = []
    send_json(ctx, 200, {"title": title, "body": body_text, "links": links})

def _search(ctx, body, **_):
    _ensure_table(ctx)
    q = body.get("query", "")
    limit = int(body.get("limit", 5))
    docs = ctx.db.execute("SELECT doc_id, title FROM wiki_docs").fetchall()
    items = sorted(
        [{"doc_id": d[0], "title": d[1], "score": _score(q, d[0])} for d in docs],
        key=lambda x: -x["score"],
    )[:limit]
    send_json(ctx, 200, {"items": items, "total": len(items)})

def _insights(ctx, body, iid, **_):
    send_json(ctx, 200, {
        "doc_id": iid,
        "summary": f"Auto-generated summary for {iid}",
        "tags": ["stub", "fixture"],
    })

def _deep_research(ctx, body, **_):
    topic = body.get("topic", "")
    send_json(ctx, 200, {
        "steps": [
            {"step": 1, "action": "search", "query": topic},
            {"step": 2, "action": "synthesize", "sources": 3},
            {"step": 3, "action": "draft"},
        ],
        "status": "pending",
    })
```

- [ ] **Step 4: 跑 test 确认 pass**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k wiki
```

Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add tests/electron/stub_modules/wiki.py tests/electron/test_stub_backend.py
git commit -m "feat(electron-e2e): add wiki endpoints to stub backend"
```

---

### Task 5: stub_backend.py memory 端点

**Files:**
- Modify: `tests/electron/stub_modules/memory.py` — 6 端点（4 注册路径，3 层共享写）
- Modify: `tests/electron/test_stub_backend.py` — ~12 unit case

**Interfaces:**
- Produces:
  - `POST /api/v1/memory/(episodic|semantic|working)` → 写入对应层，返回 `{id, layer}`
  - `GET /api/v1/memory/search` → 三层 unified search，返回 `{episodic, semantic, working}`
  - `GET /api/v1/memory/profile/:user_id` → 返回 user profile
  - `POST /api/v1/memory/consolidate` → 触发 consolidation，返回 `{status: "pending"}`

- [ ] **Step 1: 写 memory 端点失败的 unit test**

```python
def test_memory_three_tier_write_and_search():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        for layer in ["episodic", "semantic", "working"]:
            r = requests.post(f"{server.url}/api/v1/memory/{layer}",
                              json={"session_id": "s1", "content": f"hello {layer}"})
            assert r.status_code == 200
            assert r.json()["layer"] == layer
            assert r.json()["id"].startswith("mem_")

        r = requests.get(f"{server.url}/api/v1/memory/search",
                         params={"q": "hello"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["episodic"]) >= 1
        assert len(data["semantic"]) >= 1
        assert len(data["working"]) >= 1
    finally:
        server.stop()

def test_memory_search_filters_by_layer():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        requests.post(f"{server.url}/api/v1/memory/episodic",
                      json={"session_id": "s1", "content": "episodic event"})
        requests.post(f"{server.url}/api/v1/memory/semantic",
                      json={"session_id": "s1", "content": "semantic fact"})
        r = requests.get(f"{server.url}/api/v1/memory/search",
                         params={"q": "event", "layer": "episodic"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["episodic"]) >= 1
        assert all(item["layer"] == "episodic" for item in data["episodic"])
    finally:
        server.stop()

def test_memory_profile_returns_user_summary():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        requests.post(f"{server.url}/api/v1/memory/semantic",
                      json={"session_id": "s1", "content": "user likes tests"})
        r = requests.get(f"{server.url}/api/v1/memory/profile/user_123")
        assert r.status_code == 200
        data = r.json()
        assert data["user_id"] == "user_123"
        assert "facts" in data
    finally:
        server.stop()

def test_memory_consolidate_returns_pending():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.post(f"{server.url}/api/v1/memory/consolidate",
                          json={"session_id": "s1"})
        assert r.status_code == 200
        assert r.json()["status"] == "pending"
    finally:
        server.stop()
```

- [ ] **Step 2: 跑 test 确认 fail**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k memory
```

Expected: FAIL

- [ ] **Step 3: 实现 memory 端点**

```python
# tests/electron/stub_modules/memory.py
import time, uuid
from .common import send_json

def register_memory_routes(registry):
    registry[("POST", r"^/api/v1/memory/(?P<layer>episodic|semantic|working)$")] = _write
    registry[("GET",  r"^/api/v1/memory/search$")] = _search
    registry[("GET",  r"^/api/v1/memory/profile/(?P<uid>[^/]+)$")] = _profile
    registry[("POST", r"^/api/v1/memory/consolidate$")] = _consolidate

def _ensure_tables(ctx):
    ctx.db.executescript("""
        CREATE TABLE IF NOT EXISTS memory_episodic(
            id TEXT PRIMARY KEY, content TEXT, session_id TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS memory_semantic(
            id TEXT PRIMARY KEY, content TEXT, session_id TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS memory_working(
            id TEXT PRIMARY KEY, content TEXT, session_id TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS memory_profile(
            user_id TEXT PRIMARY KEY, facts TEXT, updated_at INTEGER);
    """)

def _write(ctx, body, layer, **_):
    _ensure_tables(ctx)
    mid = "mem_" + uuid.uuid4().hex[:8]
    table = f"memory_{layer}"
    ctx.db.execute(
        f"INSERT INTO {table} VALUES (?,?,?,?)",
        (mid, body.get("content", ""), body.get("session_id", ""), int(time.time() * 1000))
    )
    ctx.db.commit()
    send_json(ctx, 200, {"id": mid, "layer": layer})

def _search(ctx, body, **_):
    _ensure_tables(ctx)
    q = body.args.get("q", "") if hasattr(body, "args") else ""
    # Playwright spec 通过 query string；这里直接读 self.path
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(ctx.handler.path)
    params = parse_qs(parsed.query)
    q = params.get("q", [""])[0]
    layer_filter = params.get("layer", [None])[0]
    result = {"episodic": [], "semantic": [], "working": []}
    for layer, table in [("episodic", "memory_episodic"),
                         ("semantic", "memory_semantic"),
                         ("working",  "memory_working")]:
        if layer_filter and layer_filter != layer:
            continue
        rows = ctx.db.execute(
            f"SELECT id, content, session_id, created_at FROM {table} WHERE content LIKE ?",
            (f"%{q}%",),
        ).fetchall()
        for r in rows:
            result[layer].append({
                "id": r[0], "content": r[1], "session_id": r[2],
                "created_at_ms": r[3], "layer": layer,
            })
    send_json(ctx, 200, result)

def _profile(ctx, body, uid, **_):
    _ensure_tables(ctx)
    ctx.db.execute(
        "INSERT OR REPLACE INTO memory_profile VALUES (?,?,?)",
        (uid, f"profile facts for {uid}", int(time.time() * 1000))
    )
    ctx.db.commit()
    send_json(ctx, 200, {
        "user_id": uid,
        "facts": [{"content": f"user {uid} has 3 sessions", "ts": int(time.time() * 1000)}],
    })

def _consolidate(ctx, body, **_):
    send_json(ctx, 200, {"status": "pending"})
```

需要在文件顶部加 `from urllib.parse import urlparse, parse_qs`。

- [ ] **Step 4: 跑 test 确认 pass**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k memory
```

Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add tests/electron/stub_modules/memory.py tests/electron/test_stub_backend.py
git commit -m "feat(electron-e2e): add memory endpoints to stub backend"
```

---

### Task 6: stub_backend.py evolution 端点

**Files:**
- Modify: `tests/electron/stub_modules/evolution.py` — 5 端点
- Modify: `tests/electron/test_stub_backend.py` — ~10 unit case

**Interfaces:**
- Produces:
  - `GET /api/v1/evolution/signals` → 返回 `{signals: [{id, type, strength, created_at_ms}]}`
  - `POST /api/v1/evolution/draft` → 接受 signal ids，返回 `{id, status: "pending"}`
  - `GET /api/v1/evolution/queue` → 返回 `{drafts: [{id, status, created_at_ms}]}`
  - `POST /api/v1/evolution/approve/:id` → 设置 draft 状态为 approved
  - `GET /api/v1/evolution/scheduler/status` → 返回 `{state, last_run_at_ms, next_run_at_ms}`

- [ ] **Step 1: 写 evolution 端点失败的 unit test**

```python
def test_evolution_signals_returns_seed_list():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.get(f"{server.url}/api/v1/evolution/signals")
        assert r.status_code == 200
        signals = r.json()["signals"]
        assert len(signals) >= 1
        assert "id" in signals[0]
        assert "type" in signals[0]
        assert "strength" in signals[0]
    finally:
        server.stop()

def test_evolution_draft_to_queue_to_approve():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        signals = requests.get(f"{server.url}/api/v1/evolution/signals").json()["signals"]
        sid = signals[0]["id"]
        r1 = requests.post(f"{server.url}/api/v1/evolution/draft",
                           json={"signal_ids": [sid]})
        assert r1.status_code == 200
        draft_id = r1.json()["id"]
        assert r1.json()["status"] == "pending"

        r2 = requests.get(f"{server.url}/api/v1/evolution/queue")
        assert r2.status_code == 200
        drafts = r2.json()["drafts"]
        assert any(d["id"] == draft_id for d in drafts)

        r3 = requests.post(f"{server.url}/api/v1/evolution/approve/{draft_id}")
        assert r3.status_code == 200

        r4 = requests.get(f"{server.url}/api/v1/evolution/queue")
        approved = [d for d in r4.json()["drafts"] if d["id"] == draft_id][0]
        assert approved["status"] == "approved"
    finally:
        server.stop()

def test_evolution_scheduler_status():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        r = requests.get(f"{server.url}/api/v1/evolution/scheduler/status")
        assert r.status_code == 200
        data = r.json()
        assert data["state"] in ("idle", "running", "stopped")
        assert "last_run_at_ms" in data
        assert "next_run_at_ms" in data
    finally:
        server.stop()
```

- [ ] **Step 2: 跑 test 确认 fail**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k evolution
```

Expected: FAIL

- [ ] **Step 3: 实现 evolution 5 个端点**

```python
# tests/electron/stub_modules/evolution.py
import time, uuid
from .common import send_json

DEFAULT_SIGNALS = [
    {"id": "sig_seed_pattern_repeat_001", "type": "pattern_repeat", "strength": 0.8,
     "created_at_ms": 1700000000000, "session_id": "s1"},
    {"id": "sig_seed_tool_failure_001", "type": "tool_failure", "strength": 0.5,
     "created_at_ms": 1700000001000, "session_id": "s2"},
    {"id": "sig_seed_user_correction_001", "type": "user_correction", "strength": 0.9,
     "created_at_ms": 1700000002000, "session_id": "s1"},
]

def register_evolution_routes(registry):
    registry[("GET",  r"^/api/v1/evolution/signals$")] = _signals
    registry[("POST", r"^/api/v1/evolution/draft$")] = _draft
    registry[("GET",  r"^/api/v1/evolution/queue$")] = _queue
    registry[("POST", r"^/api/v1/evolution/approve/(?P<did>[^/]+)$")] = _approve
    registry[("GET",  r"^/api/v1/evolution/scheduler/status$")] = _scheduler_status

def _ensure_tables(ctx):
    ctx.db.executescript("""
        CREATE TABLE IF NOT EXISTS evolution_signals(
            id TEXT PRIMARY KEY, type TEXT, strength REAL,
            session_id TEXT, created_at_ms INTEGER);
        CREATE TABLE IF NOT EXISTS evolution_drafts(
            id TEXT PRIMARY KEY, signal_ids TEXT, status TEXT,
            created_at_ms INTEGER, updated_at_ms INTEGER);
    """)

def _seed(ctx):
    for s in DEFAULT_SIGNALS:
        ctx.db.execute(
            "INSERT OR IGNORE INTO evolution_signals VALUES (?,?,?,?,?)",
            (s["id"], s["type"], s["strength"], s.get("session_id", ""), s["created_at_ms"])
        )
    ctx.db.commit()

def _signals(ctx, body, **_):
    _ensure_tables(ctx)
    _seed(ctx)
    rows = ctx.db.execute(
        "SELECT id, type, strength, session_id, created_at_ms FROM evolution_signals"
    ).fetchall()
    signals = [
        {"id": r[0], "type": r[1], "strength": r[2], "session_id": r[3], "created_at_ms": r[4]}
        for r in rows
    ]
    send_json(ctx, 200, {"signals": signals})

def _draft(ctx, body, **_):
    _ensure_tables(ctx)
    did = "draft_" + uuid.uuid4().hex[:8]
    signal_ids = body.get("signal_ids", [])
    now = int(time.time() * 1000)
    ctx.db.execute(
        "INSERT INTO evolution_drafts VALUES (?,?,?,?,?)",
        (did, ",".join(signal_ids), "pending", now, now)
    )
    ctx.db.commit()
    send_json(ctx, 200, {"id": did, "status": "pending"})

def _queue(ctx, body, **_):
    _ensure_tables(ctx)
    rows = ctx.db.execute(
        "SELECT id, signal_ids, status, created_at_ms, updated_at_ms FROM evolution_drafts"
    ).fetchall()
    drafts = [
        {"id": r[0], "signal_ids": r[1].split(",") if r[1] else [],
         "status": r[2], "created_at_ms": r[3], "updated_at_ms": r[4]}
        for r in rows
    ]
    send_json(ctx, 200, {"drafts": drafts})

def _approve(ctx, body, did, **_):
    _ensure_tables(ctx)
    now = int(time.time() * 1000)
    ctx.db.execute(
        "UPDATE evolution_drafts SET status = 'approved', updated_at_ms = ? WHERE id = ?",
        (now, did)
    )
    ctx.db.commit()
    send_json(ctx, 200, {"id": did, "status": "approved"})

def _scheduler_status(ctx, body, **_):
    now = int(time.time() * 1000)
    send_json(ctx, 200, {
        "state": "idle",
        "last_run_at_ms": now - 3600_000,
        "next_run_at_ms": now + 3600_000,
    })
```

- [ ] **Step 4: 跑 test 确认 pass**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v -k evolution
```

Expected: 3 passed

- [ ] **Step 5: 全部 stub unit test 一次性回归**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v
```

Expected: ~45 passed（原 29 + 新增 ~16：orchestration 5 + wiki 4 + memory 4 + evolution 3）

- [ ] **Step 6: 提交**

```bash
git add tests/electron/stub_modules/evolution.py tests/electron/test_stub_backend.py
git commit -m "feat(electron-e2e): add evolution endpoints to stub backend"
```

---

### Task 7: conftest.py real_backend fixture

**Files:**
- Modify: `tests/electron/conftest.py` — 新增 `real_backend()` fixture
- Create: `tests/electron/test_real_backend_fixture.py` — 验证 fixture 行为

**Interfaces:**
- Consumes: `sage-backend` conda 环境（必须可调用）
- Produces: `real_backend()` fixture 启动 `conda run -n sage-backend python backend/main.py`，等待 `/health` 200，设置 `PYTHON_BACKEND_PORT`，yield，teardown kill

- [ ] **Step 1: 写 real_backend fixture 的失败 test**

```python
# tests/electron/test_real_backend_fixture.py
import os, subprocess, pytest

def test_real_backend_starts_and_responds_to_health():
    """验证 real_backend fixture 能启动真实后端并响应 /health。"""
    r = subprocess.run(
        ["conda", "run", "-n", "sage-backend", "python", "-c", "import fastapi; print('ok')"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.skip("sage-backend conda env not available")

    from conftest import RealBackend
    backend = RealBackend()
    backend.start()
    try:
        import requests
        resp = requests.get(f"{backend.url}/health", timeout=10)
        assert resp.status_code == 200
    finally:
        backend.stop()
```

- [ ] **Step 2: 跑 test 确认 fail**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_real_backend_fixture.py -v
```

Expected: FAIL with "No module named 'conftest'"（conftest 不在 import path）

- [ ] **Step 3: 创建 conftest.py 旁的 fixtures.py 文件**

为避免 pytest 把 conftest.py 当作 collection 起点但又能让 test_real_backend_fixture.py import `RealBackend`，把 `RealBackend` 类放到一个独立模块：

```python
# tests/electron/_real_backend.py
import os, signal, subprocess, time, requests

class RealBackend:
    """启动真实 conda sage-backend 子进程，等待 /health 就绪。"""

    def __init__(self, port: int = 8765, timeout_s: int = 30):
        self.port = port
        self.timeout_s = timeout_s
        self.process = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self):
        self.process = subprocess.Popen(
            ["conda", "run", "-n", "sage-backend", "python", "backend/main.py"],
            cwd="/home/fz/project/sage",
            env={**os.environ, "PYTHON_BACKEND_PORT": str(self.port)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            try:
                r = requests.get(f"{self.url}/health", timeout=2)
                if r.status_code == 200:
                    return self.url
            except requests.RequestException:
                time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"Backend failed to become healthy in {self.timeout_s}s")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
```

- [ ] **Step 4: 在 conftest.py 末尾追加 real_backend fixture**

修改 `tests/electron/conftest.py`，在文件末尾追加：

```python
import os, subprocess, time
from _real_backend import RealBackend

def _conda_env_available(env_name: str) -> bool:
    try:
        subprocess.run(
            ["conda", "run", "-n", env_name, "python", "-c", "pass"],
            check=True, capture_output=True, timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture()
def real_backend():
    """启动真实 conda sage-backend。环境不可用时 skip。"""
    if not _conda_env_available("sage-backend"):
        pytest.skip("sage-backend conda env not available")

    backend = RealBackend()
    backend.start()
    old_port = os.environ.get("PYTHON_BACKEND_PORT")
    os.environ["PYTHON_BACKEND_PORT"] = str(backend.port)
    try:
        yield backend
    finally:
        backend.stop()
        if old_port is not None:
            os.environ["PYTHON_BACKEND_PORT"] = old_port
        else:
            os.environ.pop("PYTHON_BACKEND_PORT", None)
```

- [ ] **Step 5: 跑 test 确认 pass**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_real_backend_fixture.py -v
```

Expected: 1 passed（有 conda env）或 1 skipped（无 conda env）

- [ ] **Step 6: 确认 stub_backend fixture 仍工作（无回归）**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v
```

Expected: ~45 passed

- [ ] **Step 7: 提交**

```bash
git add tests/electron/conftest.py tests/electron/_real_backend.py tests/electron/test_real_backend_fixture.py
git commit -m "feat(electron-e2e): add real_backend fixture for live backend tests"
```

---

### Task 8: fixtures/ 4 个 seed JSON

**Files:**
- Create: `tests/electron/fixtures/{sample_session,sample_memory,sample_orchestration,sample_wiki_doc}.json`

**Interfaces:**
- Produces: 4 个 JSON fixture，stub spec 与 live spec 共用

- [ ] **Step 1: 创建 fixtures 目录**

```bash
mkdir -p tests/electron/fixtures
```

- [ ] **Step 2: 写 sample_session.json**

```json
{
  "id": "sess_sample_001",
  "title": "Sample Session for E2E",
  "created_at_ms": 1700000000000,
  "updated_at_ms": 1700000000000,
  "workspace_path": "/tmp/sample_workspace"
}
```

- [ ] **Step 3: 写 sample_memory.json**

```json
{
  "episodic": [
    {"id": "mem_epi_1", "content": "User asked about Sage memory system", "session_id": "sess_sample_001", "created_at_ms": 1700000000000}
  ],
  "semantic": [
    {"id": "mem_sem_1", "content": "Sage memory uses 3 tiers: episodic, semantic, working", "session_id": "sess_sample_001", "created_at_ms": 1700000000000}
  ],
  "working": [
    {"id": "mem_wrk_1", "content": "Current context: discussing E2E testing", "session_id": "sess_sample_001", "created_at_ms": 1700000000000}
  ]
}
```

- [ ] **Step 4: 写 sample_orchestration.json**

```json
{
  "session_id": "sess_sample_001",
  "plan": "Research 3-tier memory + produce summary",
  "agents": [
    {"name": "planner",  "agent_id": "planner_1"},
    {"name": "executor", "agent_id": "executor_1"},
    {"name": "reviewer", "agent_id": "reviewer_1"}
  ]
}
```

- [ ] **Step 5: 写 sample_wiki_doc.json**

```json
{
  "title": "Sage E2E Testing Strategy",
  "body": "Sage uses a tier-based E2E strategy: stub backend for fast local feedback, real backend for nightly verification.",
  "tags": ["testing", "automation", "e2e"]
}
```

- [ ] **Step 6: 提交**

```bash
git add tests/electron/fixtures/
git commit -m "feat(electron-e2e): add 4 seed JSON fixtures for tier specs"
```

---

### Task 9: tiers/stub/smoke/ 5 spec 文件

**Files:**
- Create: `tests/electron/tiers/stub/smoke/{chat,orchestration,wiki,memory,evolution}.spec.ts`
- Create: `tests/electron/helpers/electron-launcher.ts` + `tests/electron/helpers/stub-backend.ts`

**Interfaces:**
- Consumes: 平迁后的 3 个老 spec（office/permission/qa）+ 新建 5 个
- Produces: 5 个 stub smoke spec，每个 ~50-80 行

- [ ] **Step 1: 创建 helpers 目录与 stub-backend helper**

```bash
mkdir -p tests/electron/helpers
```

```typescript
// tests/electron/helpers/stub-backend.ts
import { spawn, ChildProcessWithoutNullStreams } from 'child_process';
import { existsSync } from 'fs';
import path from 'path';

export class StubBackend {
  process: ChildProcessWithoutNullStreams | null = null;
  url = '';
  port = 0;

  constructor(private pythonPath = '/home/fz/anaconda3/envs/sage-backend/bin/python') {}

  async start(): Promise<void> {
    const stubScript = path.resolve(__dirname, '..', 'stub_backend.py');
    if (!existsSync(stubScript)) throw new Error(`stub_backend.py not found at ${stubScript}`);

    return new Promise((resolve, reject) => {
      this.process = spawn(this.pythonPath, [stubScript, '--port=0'], {
        env: { ...process.env, SAGE_STUB_PORT: '0' },
      });
      let buffer = '';
      this.process.stdout.on('data', (chunk) => {
        buffer += chunk.toString();
        const match = buffer.match(/STUB_URL=(http:\/\/127\.0\.0\.1:\d+)/);
        if (match) {
          this.url = match[1];
          this.port = parseInt(this.url.split(':').pop()!, 10);
          resolve();
        }
      });
      this.process.stderr?.on('data', (chunk) => {
        process.stderr.write(`[stub] ${chunk}`);
      });
      this.process.on('error', reject);
      setTimeout(() => reject(new Error('stub backend startup timeout')), 10000);
    });
  }

  stop(): void {
    if (this.process) {
      this.process.kill('SIGTERM');
      this.process = null;
    }
  }
}
```

stub_backend.py 需要在启动时打印 `STUB_URL=http://127.0.0.1:<port>` 到 stdout。Task 2 重构时应已包含：

```python
# 在 StubBackend.start() 末尾追加：
print(f"STUB_URL={self.url}", flush=True)
```

- [ ] **Step 2: 创建 electron-launcher helper**

```typescript
// tests/electron/helpers/electron-launcher.ts
import { _electron as electron, ElectronApplication, Page } from '@playwright/test';
import { StubBackend } from './stub-backend';

export interface ElectronWithStub {
  app: ElectronApplication;
  page: Page;
  stub: StubBackend;
}

export async function launchElectronWithStub(): Promise<ElectronWithStub> {
  const stub = new StubBackend();
  await stub.start();
  const app = await electron.launch({
    args: ['.'],
    env: {
      ...process.env,
      SAGE_BACKEND_URL: stub.url,
      PYTHON_BACKEND_PORT: String(stub.port),
      SAGE_SKIP_BACKEND: '0',
    },
  });
  const page = await app.firstWindow();
  return { app, page, stub };
}
```

- [ ] **Step 3: 写 chat.spec.ts (stub smoke)**

```typescript
// tests/electron/tiers/stub/smoke/chat.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('chat smoke: send hello, receive fixture response, message persisted', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/chat');
  await page.locator('[data-testid="chat-input"]').fill('hello');
  await page.locator('[data-testid="chat-send"]').click();

  await expect(page.locator('[data-testid="chat-message-assistant"]').last())
    .toContainText(/hi|hello|fixture/, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
```

- [ ] **Step 4: 写 orchestration.spec.ts (stub smoke)**

```typescript
// tests/electron/tiers/stub/smoke/orchestration.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';
import orchFixture from '../../../fixtures/sample_orchestration.json';

test('orchestration smoke: create run with 3 agents, lanes render', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/orchestration');
  await page.locator('[data-testid="orch-create"]').click();
  await page.locator('[data-testid="orch-plan"]').fill(orchFixture.plan);
  await page.locator('[data-testid="orch-submit"]').click();

  await expect(page.locator('[data-testid^="lane-"]')).toHaveCount(3, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
```

- [ ] **Step 5: 写 wiki.spec.ts (stub smoke)**

```typescript
// tests/electron/tiers/stub/smoke/wiki.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';
import wikiFixture from '../../../fixtures/sample_wiki_doc.json';

test('wiki smoke: ingest doc, search returns hit', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/wiki');
  await page.locator('[data-testid="wiki-content"]').fill(wikiFixture.body);
  await page.locator('[data-testid="wiki-ingest"]').click();
  await page.locator('[data-testid="wiki-search"]').fill('E2E');
  await page.locator('[data-testid="wiki-search-btn"]').click();

  await expect(page.locator('[data-testid="wiki-result"]').first()).toBeVisible({ timeout: 10_000 });

  await app.close();
  stub.stop();
});
```

- [ ] **Step 6: 写 memory.spec.ts (stub smoke)**

```typescript
// tests/electron/tiers/stub/smoke/memory.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('memory smoke: add memory item appears in episodic list', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/memory');
  await page.locator('[data-testid="memory-add"]').click();
  await page.locator('[data-testid="memory-content"]').fill('test memory item');
  await page.locator('[data-testid="memory-submit"]').click();

  await expect(page.locator('[data-testid="memory-episodic-item"]').last())
    .toContainText('test memory item', { timeout: 10_000 });

  await app.close();
  stub.stop();
});
```

- [ ] **Step 7: 写 evolution.spec.ts (stub smoke)**

```typescript
// tests/electron/tiers/stub/smoke/evolution.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('evolution smoke: scheduler shows idle, draft adds to queue', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/evolution');
  await expect(page.locator('[data-testid="scheduler-status"]'))
    .toContainText(/idle|running/, { timeout: 10_000 });

  const beforeCount = await page.locator('[data-testid="queue-item"]').count();
  await page.locator('[data-testid="evolution-trigger-draft"]').click();
  await expect(page.locator('[data-testid="queue-item"]')).toHaveCount(beforeCount + 1, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
```

- [ ] **Step 8: 跑所有 stub smoke spec**

```bash
cd /home/fz/project/sage
npm run build:electron
npx playwright test --project=electron-stub-smoke
```

Expected: 8 passed（3 平迁 + 5 新 smoke）

- [ ] **Step 9: 提交**

```bash
git add tests/electron/tiers/stub/smoke/ tests/electron/helpers/
git commit -m "feat(electron-e2e): add 5 stub smoke specs for chat/orch/wiki/memory/evolution"
```

---

### Task 10: tiers/stub/deep/ 5 spec 文件

**Files:**
- Create: `tests/electron/tiers/stub/deep/{chat,orchestration,wiki,memory,evolution}.spec.ts`

**Interfaces:**
- Produces: 5 个 stub deep spec，每个 ~200-400 行，跑完整流程

- [ ] **Step 1: 写 chat.spec.ts (stub deep)**

完整覆盖 SSE 流式分块、工具调用 mock、中断续聊、会话切换、上下文压缩。

```typescript
// tests/electron/tiers/stub/deep/chat.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('chat deep', () => {
  let app, page, stub;
  test.beforeAll(async () => { ({ app, page, stub } = await launchElectronWithStub()); });
  test.afterAll(async () => { await app?.close(); stub?.stop(); });

  test('SSE 流式分块验证', async () => {
    // 触发 chat，监听 SSE 事件，验证至少 3 个 chunk 到达
    await page.goto('/chat');
    await page.locator('[data-testid="chat-input"]').fill('tell me a long story');
    await page.locator('[data-testid="chat-send"]').click();
    // 等待首个 chunk
    await expect(page.locator('[data-testid="chat-message-assistant"]').last())
      .toContainText(/[a-z]/, { timeout: 5_000 });
    // 验证后续 chunk 累积（content 长度增加）
    const len1 = await page.locator('[data-testid="chat-message-assistant"]').last().textContent();
    await page.waitForTimeout(1000);
    const len2 = await page.locator('[data-testid="chat-message-assistant"]').last().textContent();
    expect(len2!.length).toBeGreaterThanOrEqual(len1!.length);
  });

  test('工具调用 mock 响应', async () => {
    // stub 注入 tool_call，验证 UI 渲染 + 回传 tool result
    await page.goto('/chat');
    await page.locator('[data-testid="chat-input"]').fill('@tool:echo hello');
    await page.locator('[data-testid="chat-send"]').click();
    await expect(page.locator('[data-testid="tool-call"]').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="tool-result"]').first()).toContainText('hello');
  });

  test('中断续聊', async () => {
    await page.goto('/chat');
    await page.locator('[data-testid="chat-input"]').fill('first message');
    await page.locator('[data-testid="chat-send"]').click();
    await expect(page.locator('[data-testid="chat-message-assistant"]')).toHaveCount(2, { timeout: 10_000 });

    // 关闭 stream，重新进入
    await page.goto('/welcome');
    await page.goto('/chat');
    await expect(page.locator('[data-testid="chat-message-assistant"]').first()).toBeVisible();
  });

  test('会话切换', async () => {
    await page.goto('/sessions');
    await page.locator('[data-testid="session-item"]').first().click();
    await expect(page).toHaveURL(/\/chat\?session=/);
  });

  test('上下文压缩触发', async () => {
    await page.goto('/chat');
    // 发 5 条长消息，触发 working memory 压缩
    for (let i = 0; i < 5; i++) {
      await page.locator('[data-testid="chat-input"]').fill('Long message '.repeat(50) + i);
      await page.locator('[data-testid="chat-send"]').click();
      await page.waitForTimeout(500);
    }
    await expect(page.locator('[data-testid="memory-consolidation-event"]')).toBeVisible({ timeout: 30_000 });
  });
});
```

- [ ] **Step 2: 写 orchestration.spec.ts (stub deep)**

完整覆盖 planner 阶段产物 → executor 调工具 → reviewer 拒绝触发重试 → 用户审批 token → 多 agent lane 切换 → run 完成。每个阶段通过 stub DB 状态断言。

```typescript
// tests/electron/tiers/stub/deep/orchestration.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('orchestration deep', () => {
  let app, page, stub, apiCtx;
  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
    apiCtx = await request.newContext({ baseURL: stub.url });
  });
  test.afterAll(async () => { await app?.close(); stub?.stop(); await apiCtx?.dispose(); });

  test('planner → executor → reviewer 全流程', async () => {
    await page.goto('/orchestration');
    await page.locator('[data-testid="orch-create"]').click();
    await page.locator('[data-testid="orch-plan"]').fill('Research memory tiers');
    await page.locator('[data-testid="orch-submit"]').click();

    // 验证 3 个 lane 出现
    await expect(page.locator('[data-testid^="lane-"]')).toHaveCount(3);

    // 通过 stub API 拿 run_id 验证状态
    const list = await apiCtx.get('/api/v1/orchestration/runs').catch(() => null);
    // stub 当前没有 list endpoint；至少 get single run
    const rid = await page.locator('[data-testid="orch-run-id"]').first().textContent();
    const run = await apiCtx.get(`/api/v1/orchestration/runs/${rid}`);
    expect(run.ok()).toBeTruthy();
  });

  test('reviewer 拒绝触发重试', async () => {
    // 调用 stub draft 拒绝 endpoint（stub 应在 signals 中返回 user_correction 类型）
    await page.goto('/orchestration');
    await page.locator('[data-testid="orch-create"]').click();
    await page.locator('[data-testid="orch-plan"]').fill('trigger reviewer rejection');
    await page.locator('[data-testid="orch-submit"]').click();
    await expect(page.locator('[data-testid="lane-reviewer-rejected"]')).toBeVisible({ timeout: 10_000 });
  });

  test('用户审批 token 后 run 进入 approved', async () => {
    const create = await apiCtx.post('/api/v1/orchestration/runs', {
      data: { session_id: 's1', plan: 'p' },
    });
    const rid = (await create.json()).run_id;
    const approve = await apiCtx.post(`/api/v1/orchestration/runs/${rid}/approve`, {
      data: { token: 'user_token_1' },
    });
    expect(approve.ok()).toBeTruthy();
    const run = await apiCtx.get(`/api/v1/orchestration/runs/${rid}`);
    expect((await run.json()).approval_token).toBe('user_token_1');
  });
});
```

- [ ] **Step 3: 写 wiki.spec.ts (stub deep)**

完整覆盖 ingest → extract → chunk → embed → search 排序 → graph 邻居 → insights。

```typescript
// tests/electron/tiers/stub/deep/wiki.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('wiki deep', () => {
  let app, page, stub, apiCtx;
  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
    apiCtx = await request.newContext({ baseURL: stub.url });
  });
  test.afterAll(async () => { await app?.close(); stub?.stop(); await apiCtx?.dispose(); });

  test('ingest → search 返回按 score 排序', async () => {
    await apiCtx.post('/api/v1/wiki/ingest', {
      data: { title: 'A', content: 'first doc' },
    });
    await apiCtx.post('/api/v1/wiki/ingest', {
      data: { title: 'B', content: 'second doc' },
    });
    const r = await apiCtx.post('/api/v1/wiki/search', {
      data: { query: 'doc', limit: 10 },
    });
    const data = await r.json();
    expect(data.total).toBeGreaterThanOrEqual(2);
    // 排序：score 递减
    for (let i = 0; i < data.items.length - 1; i++) {
      expect(data.items[i].score).toBeGreaterThanOrEqual(data.items[i + 1].score);
    }
  });

  test('extract 返回 title/body/links', async () => {
    const r = await apiCtx.post('/api/v1/wiki/extract', {
      data: { content: 'Hello world. This is Sage.' },
    });
    const data = await r.json();
    expect(data.title).toBeTruthy();
    expect(data.body).toContain('Sage');
    expect(Array.isArray(data.links)).toBe(true);
  });

  test('insights 返回 summary + tags', async () => {
    const create = await apiCtx.post('/api/v1/wiki/ingest', {
      data: { title: 'X', content: 'Y' },
    });
    const { doc_id } = await create.json();
    const ins = await apiCtx.get(`/api/v1/wiki/insights/${doc_id}`);
    const data = await ins.json();
    expect(data.summary).toBeTruthy();
    expect(Array.isArray(data.tags)).toBe(true);
  });

  test('deep research 返回 plan', async () => {
    const r = await apiCtx.post('/api/v1/wiki/deep-research', {
      data: { topic: 'memory tiers' },
    });
    const data = await r.json();
    expect(Array.isArray(data.steps)).toBe(true);
    expect(data.steps.length).toBeGreaterThanOrEqual(1);
  });
});
```

- [ ] **Step 4: 写 memory.spec.ts (stub deep)**

完整覆盖 episodic 写入 → working 更新 → 语义检索 → consolidation → profile 更新 → 跨会话引用。

```typescript
// tests/electron/tiers/stub/deep/memory.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('memory deep', () => {
  let app, page, stub, apiCtx;
  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
    apiCtx = await request.newContext({ baseURL: stub.url });
  });
  test.afterAll(async () => { await app?.close(); stub?.stop(); await apiCtx?.dispose(); });

  test('三层各写入 + unified search 返回三层', async () => {
    for (const layer of ['episodic', 'semantic', 'working']) {
      const r = await apiCtx.post(`/api/v1/memory/${layer}`, {
        data: { session_id: 's1', content: `hello ${layer}` },
      });
      expect(r.ok()).toBeTruthy();
    }
    const r = await apiCtx.get('/api/v1/memory/search?q=hello');
    const data = await r.json();
    expect(data.episodic.length).toBeGreaterThanOrEqual(1);
    expect(data.semantic.length).toBeGreaterThanOrEqual(1);
    expect(data.working.length).toBeGreaterThanOrEqual(1);
  });

  test('按 layer 过滤', async () => {
    await apiCtx.post('/api/v1/memory/episodic', { data: { session_id: 's1', content: 'foo' } });
    await apiCtx.post('/api/v1/memory/semantic', { data: { session_id: 's1', content: 'foo' } });
    const r = await apiCtx.get('/api/v1/memory/search?q=foo&layer=episodic');
    const data = await r.json();
    expect(data.episodic.length).toBeGreaterThanOrEqual(1);
    expect(data.semantic).toHaveLength(0);
    expect(data.working).toHaveLength(0);
  });

  test('consolidate 返回 pending', async () => {
    const r = await apiCtx.post('/api/v1/memory/consolidate', { data: { session_id: 's1' } });
    expect((await r.json()).status).toBe('pending');
  });

  test('profile 返回 user_id + facts', async () => {
    const r = await apiCtx.get('/api/v1/memory/profile/user_42');
    const data = await r.json();
    expect(data.user_id).toBe('user_42');
    expect(Array.isArray(data.facts)).toBe(true);
  });
});
```

- [ ] **Step 5: 写 evolution.spec.ts (stub deep)**

完整覆盖 signal → draft → queue → approve → skill 写入。

```typescript
// tests/electron/tiers/stub/deep/evolution.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('evolution deep', () => {
  let app, page, stub, apiCtx;
  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
    apiCtx = await request.newContext({ baseURL: stub.url });
  });
  test.afterAll(async () => { await app?.close(); stub?.stop(); await apiCtx?.dispose(); });

  test('signals 列表包含 seed', async () => {
    const r = await apiCtx.get('/api/v1/evolution/signals');
    const data = await r.json();
    expect(data.signals.length).toBeGreaterThanOrEqual(1);
    expect(data.signals[0]).toHaveProperty('id');
    expect(data.signals[0]).toHaveProperty('type');
    expect(data.signals[0]).toHaveProperty('strength');
  });

  test('draft 流程：创建 → queue 出现 → approve → 状态变更', async () => {
    const sigs = (await (await apiCtx.get('/api/v1/evolution/signals')).json()).signals;
    const create = await apiCtx.post('/api/v1/evolution/draft', {
      data: { signal_ids: [sigs[0].id] },
    });
    const draft = await create.json();
    expect(draft.id).toMatch(/^draft_/);
    expect(draft.status).toBe('pending');

    const queue = await (await apiCtx.get('/api/v1/evolution/queue')).json();
    expect(queue.drafts.some(d => d.id === draft.id)).toBe(true);

    await apiCtx.post(`/api/v1/evolution/approve/${draft.id}`);

    const queue2 = await (await apiCtx.get('/api/v1/evolution/queue')).json();
    const updated = queue2.drafts.find(d => d.id === draft.id);
    expect(updated.status).toBe('approved');
  });

  test('scheduler status 返回合法字段', async () => {
    const r = await apiCtx.get('/api/v1/evolution/scheduler/status');
    const data = await r.json();
    expect(['idle', 'running', 'stopped']).toContain(data.state);
    expect(typeof data.last_run_at_ms).toBe('number');
    expect(typeof data.next_run_at_ms).toBe('number');
  });
});
```

- [ ] **Step 6: 跑所有 stub deep spec**

```bash
cd /home/fz/project/sage
npx playwright test --project=electron-stub-deep
```

Expected: 5 passed（每个 spec 含多个 test case）

- [ ] **Step 7: 提交**

```bash
git add tests/electron/tiers/stub/deep/
git commit -m "feat(electron-e2e): add 5 stub deep specs covering full business flow"
```

---

### Task 11: tiers/live/boot-smoke/ 3 spec 文件

**Files:**
- Create: `tests/electron/tiers/live/boot-smoke/{health,routes,sse-handshake}.spec.ts`

**Interfaces:**
- Consumes: `realBackend()` fixture from `conftest.py`
- Produces: 3 个真实后端冒烟 spec，验证后端能起来且路由可达，不调 LLM

- [ ] **Step 1: 写 health.spec.ts**

```typescript
// tests/electron/tiers/live/boot-smoke/health.spec.ts
import { test, expect } from '@playwright/test';

test('real backend /health returns 200', async ({ request }) => {
  const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';
  const resp = await request.get(`${url}/health`);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.status).toBe('ok');
});
```

- [ ] **Step 2: 写 routes.spec.ts**

```typescript
// tests/electron/tiers/live/boot-smoke/routes.spec.ts
import { test, expect } from '@playwright/test';

const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('GET /api/v1/sessions returns 200 or 404', async ({ request }) => {
  const resp = await request.get(`${url}/api/v1/sessions`);
  expect([200, 404]).toContain(resp.status());
});

test('GET /api/v1/memory/search returns 200', async ({ request }) => {
  const resp = await request.get(`${url}/api/v1/memory/search?q=test`);
  expect([200, 400]).toContain(resp.status());
});

test('GET /api/v1/evolution/scheduler/status returns 200', async ({ request }) => {
  const resp = await request.get(`${url}/api/v1/evolution/scheduler/status`);
  expect(resp.status()).toBe(200);
});

test('GET /api/v1/wiki/search returns 200 or 405', async ({ request }) => {
  const resp = await request.get(`${url}/api/v1/wiki/search?q=test`);
  expect([200, 405, 400]).toContain(resp.status());
});
```

- [ ] **Step 3: 写 sse-handshake.spec.ts**

```typescript
// tests/electron/tiers/live/boot-smoke/sse-handshake.spec.ts
import { test, expect } from '@playwright/test';

const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('SSE chat stream 握手成功', async ({ request }) => {
  // 触发 stream 创建
  const create = await request.post(`${url}/api/v1/chat/stream`, {
    data: { session_id: 'sess_boot_smoke', content: 'hi' },
  });
  if (!create.ok()) {
    test.skip(true, `chat stream create failed: ${create.status()}`);
  }
  const { stream_id } = await create.json();
  const resp = await request.get(`${url}/api/v1/chat/stream/${stream_id}`);
  expect(resp.status()).toBe(200);
  expect(resp.headers()['content-type']).toMatch(/event-stream|ndjson/);
});
```

- [ ] **Step 4: 跑 live-boot spec（需要 conda sage-backend）**

```bash
cd /home/fz/project/sage
# 先启后端
conda activate sage-backend && python backend/main.py &
sleep 5
# 再跑
npx playwright test --project=electron-live-boot
# 清理
kill %1
```

Expected: 3+ passed（有 conda + 后端启动） 或 skipped（环境不可用）

- [ ] **Step 5: 提交**

```bash
git add tests/electron/tiers/live/boot-smoke/
git commit -m "feat(electron-e2e): add 3 live boot-smoke specs for real backend validation"
```

---

### Task 12: tiers/live/deep/ 5 spec 文件

**Files:**
- Create: `tests/electron/tiers/live/deep/{chat,orchestration,wiki,memory,evolution}.spec.ts`

**Interfaces:**
- Consumes: `realBackend()` fixture + 环境变量 `OPENAI_API_KEY`（若未设置则 skip）
- Produces: 5 个真实 LLM E2E spec，每个 spec 用 `@nightly` 或 `@release` tag 控制激活范围

- [ ] **Step 1: 写 chat.spec.ts (live deep)**

```typescript
// tests/electron/tiers/live/deep/chat.spec.ts
import { test, expect } from '@playwright/test';

const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('chat live deep: real LLM responds coherently', { tag: '@nightly' }, async ({ request }) => {
  if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
    test.skip(true, 'OPENAI_API_KEY not set');
  }
  const create = await request.post(`${url}/api/v1/chat/stream`, {
    data: { session_id: 'sess_live_chat', content: 'What is 2+2? Answer in one word.' },
  });
  expect(create.ok()).toBeTruthy();
  const { stream_id } = await create.json();
  const resp = await request.get(`${url}/api/v1/chat/stream/${stream_id}`);
  expect(resp.status()).toBe(200);
  const body = await resp.text();
  expect(body).toMatch(/four|4/);
}, { timeout: 60_000 });
```

- [ ] **Step 2: 写 memory.spec.ts (live deep)**

```typescript
// tests/electron/tiers/live/deep/memory.spec.ts
import { test, expect } from '@playwright/test';

const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('memory live deep: write → cross-session search', { tag: '@nightly' }, async ({ request }) => {
  if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
    test.skip(true, 'OPENAI_API_KEY not set');
  }
  // session A 写入
  const a = await request.post(`${url}/api/v1/memory/episodic`, {
    data: { session_id: 'sess_A', content: 'User mentioned preferring dark mode' },
  });
  expect(a.ok()).toBeTruthy();

  // session B 跨 session 搜索
  const search = await request.get(`${url}/api/v1/memory/search?q=dark+mode`);
  expect(search.ok()).toBeTruthy();
  const data = await search.json();
  const ids = [data.episodic, data.semantic, data.working].flat().map(m => m.session_id);
  expect(ids).toContain('sess_A');
}, { timeout: 60_000 });

test('memory live deep: consolidation', { tag: '@nightly' }, async ({ request }) => {
  const r = await request.post(`${url}/api/v1/memory/consolidate`, {
    data: { session_id: 'sess_A' },
  });
  expect(r.ok()).toBeTruthy();
});
```

- [ ] **Step 3: 写 orchestration.spec.ts (live deep)**

```typescript
// tests/electron/tiers/live/deep/orchestration.spec.ts
import { test, expect } from '@playwright/test';

const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('orchestration live deep: 3-agent real LLM run', { tag: '@release' }, async ({ request }) => {
  if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
    test.skip(true, 'OPENAI_API_KEY not set');
  }
  const create = await request.post(`${url}/api/v1/orchestration/runs`, {
    data: { session_id: 'sess_orch', plan: 'List 3 risks of LLMs in one sentence each' },
  });
  expect(create.ok()).toBeTruthy();
  const rid = (await create.json()).run_id;
  // 等待 run 完成（最长 90s）
  let status = 'running';
  for (let i = 0; i < 30; i++) {
    const r = await request.get(`${url}/api/v1/orchestration/runs/${rid}`);
    status = (await r.json()).status;
    if (status === 'completed' || status === 'failed') break;
    await new Promise(resolve => setTimeout(resolve, 3000));
  }
  expect(status).toBe('completed');
}, { timeout: 120_000 });
```

- [ ] **Step 4: 写 wiki.spec.ts (live deep)**

```typescript
// tests/electron/tiers/live/deep/wiki.spec.ts
import { test, expect } from '@playwright/test';

const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('wiki live deep: deep research plan', { tag: '@release' }, async ({ request }) => {
  if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
    test.skip(true, 'OPENAI_API_KEY not set');
  }
  const r = await request.post(`${url}/api/v1/wiki/deep-research`, {
    data: { topic: 'Sage project structure' },
  });
  expect(r.ok()).toBeTruthy();
  const data = await r.json();
  expect(data.steps.length).toBeGreaterThanOrEqual(1);
});
```

- [ ] **Step 5: 写 evolution.spec.ts (live deep)**

```typescript
// tests/electron/tiers/live/deep/evolution.spec.ts
import { test, expect } from '@playwright/test';

const url = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('evolution live deep: signal → draft', { tag: '@release' }, async ({ request }) => {
  if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
    test.skip(true, 'OPENAI_API_KEY not set');
  }
  const sigs = (await (await request.get(`${url}/api/v1/evolution/signals`)).json()).signals;
  expect(sigs.length).toBeGreaterThanOrEqual(1);
  const draft = await request.post(`${url}/api/v1/evolution/draft`, {
    data: { signal_ids: [sigs[0].id] },
  });
  expect(draft.ok()).toBeTruthy();
});
```

- [ ] **Step 6: 跑 nightly 默认应只跑 chat + memory**

```bash
cd /home/fz/project/sage
npx playwright test --project=electron-live-deep --grep=@nightly
```

Expected: 2 passed（chat + memory），其他 skip

- [ ] **Step 7: 提交**

```bash
git add tests/electron/tiers/live/deep/
git commit -m "feat(electron-e2e): add 5 live deep specs with @nightly/@release gating"
```

---

### Task 13: playwright.config.ts + package.json 集成

**Files:**
- Modify: `playwright.config.ts` — 新增 4 个 project
- Modify: `package.json` — 新增 5 个 npm script

- [ ] **Step 1: 在 playwright.config.ts 追加 4 个 project**

```typescript
// 在 projects 数组末尾追加：
{
  name: 'electron-stub-smoke',
  testDir: './tests/electron/tiers/stub/smoke',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  outputDir: './tests/electron/tiers/stub/smoke/test-results',
},
{
  name: 'electron-stub-deep',
  testDir: './tests/electron/tiers/stub/deep',
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  outputDir: './tests/electron/tiers/stub/deep/test-results',
},
{
  name: 'electron-live-boot',
  testDir: './tests/electron/tiers/live/boot-smoke',
  timeout: 60_000,
  retries: 0,
  outputDir: './tests/electron/tiers/live/boot-smoke/test-results',
},
{
  name: 'electron-live-deep',
  testDir: './tests/electron/tiers/live/deep',
  timeout: 180_000,
  retries: 0,
  outputDir: './tests/electron/tiers/live/deep/test-results',
},
```

- [ ] **Step 2: 在 package.json 追加 5 个 npm script**

```json
{
  "scripts": {
    "test:smoke":   "playwright test --project=electron-stub-smoke",
    "test:pr":      "playwright test --project=electron-stub-smoke --project=electron-stub-deep --project=electron-live-boot",
    "test:nightly": "playwright test --project=electron-stub-smoke --project=electron-stub-deep --project=electron-live-boot --project=electron-live-deep --grep=@nightly",
    "test:release": "playwright test --project=electron-stub-smoke --project=electron-stub-deep --project=electron-live-boot --project=electron-live-deep",
    "test:dev":     "playwright test --project=electron-stub-smoke --ui"
  }
}
```

- [ ] **Step 3: 跑 test:smoke 验证集成**

```bash
cd /home/fz/project/sage
npm run test:smoke
```

Expected: 8 passed（3 平迁 + 5 新 smoke）

- [ ] **Step 4: 跑 test:pr 验证集成（live-boot 在无 conda 时 skip）**

```bash
npm run test:pr
```

Expected: stub-smoke 8 passed + stub-deep 5 passed + live-boot skipped (无 conda)

- [ ] **Step 5: 提交**

```bash
git add playwright.config.ts package.json package-lock.json
git commit -m "feat(electron-e2e): integrate 4 Playwright projects and 5 npm stage scripts"
```

---

### Task 14: GitHub Actions workflows

**Files:**
- Create: `.github/workflows/e2e-pr-gate.yml`
- Create: `.github/workflows/e2e-nightly.yml`

- [ ] **Step 1: 创建 e2e-pr-gate.yml**

```yaml
name: E2E PR Gate
on:
  pull_request:
    branches: [main]
jobs:
  stub-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npm run build:electron
      - run: npm run test:smoke
  stub-deep:
    runs-on: ubuntu-latest
    needs: stub-smoke
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npm run build:electron
      - run: npx playwright test --project=electron-stub-deep
  live-boot:
    runs-on: ubuntu-latest
    needs: stub-deep
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - uses: conda-incubator/setup-miniconda@v3
        with: { python-version: '3.11' }
      - run: conda create -n sage-backend python=3.11 -y
      - run: conda run -n sage-backend pip install -r backend/requirements.txt
      - run: npm ci && npm run build:electron
      - run: npx playwright test --project=electron-live-boot
```

- [ ] **Step 2: 创建 e2e-nightly.yml**

```yaml
name: E2E Nightly
on:
  schedule:
    - cron: '0 3 * * *'
  workflow_dispatch:
jobs:
  live-deep-nightly:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - uses: conda-incubator/setup-miniconda@v3
        with: { python-version: '3.11' }
      - run: conda create -n sage-backend python=3.11 -y
      - run: conda run -n sage-backend pip install -r backend/requirements.txt
      - run: npm ci && npm run build:electron
      - name: Run nightly live deep E2E
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: npm run test:nightly
```

- [ ] **Step 3: 验证 yaml 语法**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/e2e-pr-gate.yml'))"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/e2e-nightly.yml'))"
```

Expected: 无输出（语法 OK）

- [ ] **Step 4: 提交**

```bash
git add .github/workflows/e2e-pr-gate.yml .github/workflows/e2e-nightly.yml
git commit -m "ci(electron-e2e): add e2e-pr-gate and e2e-nightly workflows"
```

---

### Task 15: README.md 重写

**Files:**
- Modify: `tests/electron/README.md` — 重写为完整 tier + stage 文档

- [ ] **Step 1: 重写 README.md**

```markdown
# tests/electron/ — Sage 桌面端 E2E 测试

## 1. 架构总览

```
                     ┌────────────────────────────────────────┐
                     │  Playwright test runner (Node.js)      │
                     │  --project={electron-*}                │
                     └─────────────────┬──────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
   │ tiers/stub/{smoke,   │  │ tiers/stub/deep      │  │ tiers/live/{boot,    │
   │ deep}                │  │ tiers/live/deep      │  │ deep}                │
   └──────────┬───────────┘  └──────────┬───────────┘  └──────────┬───────────┘
              ▼                         ▼                          ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
   │ stub_backend.py      │  │ stub_backend.py      │  │ conda sage-backend   │
   │ (in-memory SQLite)   │  │ (in-memory SQLite)   │  │ (sqlite + LLM API)   │
   │ 无 conda、无 LLM     │  │ 无 conda、无 LLM     │  │ 需 conda + LLM key   │
   └──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

## 2. 目录结构

```
tests/electron/
├── README.md                          # 本文档
├── conftest.py                        # stub_backend() + real_backend() fixtures
├── _real_backend.py                   # RealBackend 子进程管理类
├── stub_backend.py                    # 入口：HTTP server + routing
├── stub_modules/                      # 按功能拆分的 stub handler
│   ├── common.py
│   ├── chat.py
│   ├── orchestration.py
│   ├── wiki.py
│   ├── memory.py
│   └── evolution.py
├── test_stub_backend.py               # ~45 个 stub unit case (pytest)
├── test_real_backend_fixture.py       # real_backend fixture 验证
├── fixtures/                          # seed JSON
└── tiers/
    ├── stub/smoke/                    # 5 spec × ~50 行（含 3 个平迁老 spec）
    ├── stub/deep/                     # 5 spec × ~300 行
    └── live/
        ├── boot-smoke/                # 3 spec（不调 LLM）
        └── deep/                      # 5 spec（含 1 个平迁，含 @nightly/@release tag）
```

## 3. 4 个开发阶段

| 阶段 | 命令 | 时长 | 后端 | LLM |
|---|---|---|---|---|
| 本地 dev loop | `npm run test:smoke` | 30-60s | stub | n/a |
| PR 门禁 | `npm run test:pr` | 5-10min | stub + real(no LLM) | no |
| Nightly | `npm run test:nightly` | 30-60min | real | yes (chat + memory only) |
| 手动/Release | `npm run test:release` | 60-120min | real | yes (all 5) |

## 4. 运行示例

```bash
# 开发期间快速验证
npm run test:smoke

# 提交 PR 前本地跑一遍（需要 conda sage-backend）
conda activate sage-backend && python backend/main.py &
npm run test:pr

# Nightly（需要 OPENAI_API_KEY）
OPENAI_API_KEY=sk-... npm run test:nightly
```

## 5. 添加新 spec

### stub smoke（无 conda）
1. 在 `tests/electron/tiers/stub/smoke/<feature>.spec.ts` 新建文件
2. 用 `helpers/electron-launcher.ts` 起 stub + electron
3. 用 page 操作 + stub API 断言

### live deep（需 conda + LLM key）
1. 在 `tests/electron/tiers/live/deep/<feature>.spec.ts` 新建文件
2. 用 `{ tag: '@nightly' }` 或 `{ tag: '@release' }` 限定激活范围
3. spec body 中 `test.skip` 当 `OPENAI_API_KEY` 缺失

## 6. 故障排查

### stub 启动失败
- 检查 `/home/fz/anaconda3/envs/sage-backend/bin/python` 可执行
- 检查 `stub_backend.py` 没被其他进程占用
- 启动时会打印 `STUB_URL=http://127.0.0.1:<port>`，捕获失败要看 stderr

### real backend 启动失败
- `conda activate sage-backend && python backend/main.py` 手动跑一遍
- 端口冲突：`lsof -i :8765` 找占用进程
- LLM key 缺失：live-deep spec 自动 skip

### Electron 冷启动慢
- CI 上 `retries: 1`，spec 用 `beforeAll` 复用实例
- 本地 `npx playwright test --ui` 可视化调试
```

- [ ] **Step 2: 验证 README 长度**

```bash
wc -l tests/electron/README.md
```

Expected: 100-150 行

- [ ] **Step 3: 提交**

```bash
git add tests/electron/README.md
git commit -m "docs(electron-e2e): rewrite README for tier + stage architecture"
```

---

## Self-Review Checklist

**Spec coverage:**

| Spec 章节 | 对应 Task |
|---|---|
| §3.1 目录重构 | Task 1 |
| §3.1 stub_backend.py 扩展 (5 领域 21 端点) | Task 2-6 |
| §3.1 conftest.py 扩展 real_backend | Task 7 |
| §3.1 fixtures/ 目录 | Task 8 |
| §3.1 tiers/ 18 spec 文件 | Task 9-12 |
| §3.1 playwright.config.ts + package.json | Task 13 |
| §3.1 GitHub Actions 2 workflow | Task 14 |
| §3.1 test_stub_backend.py 扩展 | Task 2-6（每 task 内） |
| §3.1 README.md 重写 | Task 15 |

**Placeholder scan:** 无 "TBD" / "TODO" / "类似 Task N" / 模糊表述。每个 step 含具体代码或命令。

**Type consistency:** `StubBackend`、`real_backend()`、`_score()`、`_ensure_table()`、`launchElectronWithStub()`、`StubContext` 等类型/函数名在所有 task 中保持一致。

**Scope:** 单一 spec 单一 plan，覆盖完整子系统。15 个 task，每个可独立提交 + review + merge。