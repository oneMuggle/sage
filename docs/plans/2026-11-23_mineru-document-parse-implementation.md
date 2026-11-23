# MinerU 文档解析子系统实施计划（轨道 A：M1–M7）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sage 增加可插拔的文档解析子系统（本地引擎 + 内网 MinerU 引擎），并把聊天附件 PDF 升级为「本地先出文本 + 后台 MinerU 高质量补全」双阶段。

**Architecture:** 六边形分层。纯契约（`ParseRequest/ParseResult/ParseEngine/MineruSettings`）落在 `backend/domain/document_parse.py`；编排服务 `DocumentParseService`（路由/熔断/缓存编排）落在 `backend/application/document_parse.py`，只依赖 Protocol + 注入；MinerU HTTP 客户端与本地引擎落在 `backend/adapters/out/document_parse/`；配置加载、SQLite 缓存、后台队列、工厂装配落在 `backend/services/document_parse/`（services 层不受 import-linter 约束）。工具与 API 层只做薄封装。

**Tech Stack:** Python 3.10（main）/ 3.8（release/win7 兼容写法）、FastAPI、httpx 0.26.0（已钉版本，零新增依赖）、sqlite3、PyMuPDF（惰性导入）、React + TypeScript + Vitest。

**Spec:** `docs/plans/2026-11-23_mineru-document-parse-subsystem.md`

## Global Constraints

- 后端 Python 一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python`；worktree 内**禁止**把包装进共享 `sage-backend`。
- 禁止在 main 上改 `backend/requirements-py38.txt`，禁止在 release/win7 上改 `backend/requirements.txt`；本计划**不新增任何依赖**（httpx 已在两份 requirements 中钉为 `0.26.0`）。
- py38 兼容：不用 PEP 604 运行时注解（`X | None` 只能出现在字符串注解/`from __future__ import annotations`），不用 `asyncio.to_thread`，不用泛型下标（`list[str]`）做运行时表达式；元组 isinstance 需 `# noqa: UP038`。
- MinerU API key 只允许来自 `.env.local`/环境变量/设置页，**绝不**写入日志、错误消息或聊天；状态接口只回 `hasApiKey: bool`。
- MinerU 服务端在未配置 `--api-key` 时**未开鉴权**（离线包 systemd 未传该参数）——`apiKey` 留空即合法配置，仅在服务端要求鉴权时才需要。
- `architecture-policy.json` `maxFileLines: 800`；已登记文件长高须同步 `architecture-baseline.json`。
- 每个任务结束必须 commit；提交前跑 `ruff check`（双引号 Q000、中文注释 ERA001 规避）。
- 文档/spec 漂移清单见 spec §11；本计划在 Task 11 收口。

### 与 spec 的已确认偏差（实现时以此为准）

1. 新增 `backend/adapters/out/document_parse/mineru_engine.py`（spec §3.1 未列）：把「MinerU 输出 → ParseResult + MediaStore 落盘」放在适配器，保持 application 层零适配器依赖。
2. 新增 `backend/services/document_parse/factory.py`（spec §3.1 未列）：装配只依赖 adapters+application+services，放在 services 层最内聚。
3. 新增 `backend/services/attachment_extract.py`（spec §3.1 未列）：把聊天附件的纯提取函数移出 `backend/api`，供 LocalEngine 复用，避免 adapters→api 的向上依赖。
4. `ParseDocumentTool.risk = RiskClass.EXTERNAL`（spec §4.7 写 READ）：`backend/domain/risk.py:41` 定义 EXTERNAL 为「副作用发生在机器之外（网络等）— 最严门禁」，文档内容会离机上传到内网服务器，符合该定义。
5. `ParseResult` 增加 `assets: Dict[str, str]`（archive 图片名 → MediaStore api_url），用于 spec §4.5 的 `images_dir` 列。
6. 本地引擎对 PDF 只产文本（`structured=None`）；`structured` 仅 MinerU 提供，避免二次解析。

### 文件结构（锁定）

```
backend/domain/document_parse.py                        契约 + MineruSettings
backend/application/document_parse.py                   编排/路由/熔断/缓存 Protocol
backend/adapters/out/document_parse/__init__.py
backend/adapters/out/document_parse/mineru_models.py    响应模型 + ZIP 解包
backend/adapters/out/document_parse/mineru_errors.py    错误类型
backend/adapters/out/document_parse/mineru_client.py    4 步异步协议客户端
backend/adapters/out/document_parse/local_engine.py     本地引擎
backend/adapters/out/document_parse/mineru_engine.py    MinerU 引擎适配
backend/adapters/out/document_parse/quality.py          质量信号 + 打分
backend/services/attachment_extract.py                  纯文本提取（从 api 迁出）
backend/services/document_parse/__init__.py
backend/services/document_parse/config.py               MinerU 配置加载
backend/services/document_parse/cache.py                SQLite 解析缓存
backend/services/document_parse/queue.py                MinerU 后台队列
backend/services/document_parse/factory.py              装配/单例
backend/tools/parse_document_tool.py                    parse_document 工具
backend/api/mineru_routes.py                            GET /api/v1/mineru/status
src/shared/api/mineruApi.ts                             前端状态 API
src/pages/settings/MineruServiceCard.tsx                设置卡片
docs/technical/160-mineru-document-parse.md             技术文档
```

---

### Task 1: 领域契约 + MinerU 响应模型与错误类型

**Files:**
- Create: `backend/domain/document_parse.py`
- Create: `backend/adapters/out/document_parse/__init__.py`
- Create: `backend/adapters/out/document_parse/mineru_errors.py`
- Create: `backend/adapters/out/document_parse/mineru_models.py`
- Test: `backend/tests/unit/test_document_parse_domain.py`

**Interfaces:**
- Produces: `ParseRequest(filename, content_bytes, engine_hint="auto", output_format="markdown", page_range=None, tier=None, timeout_seconds=None, source_path=None, media_id=None)`；`.extension`、`.content_hash()`。
- Produces: `ParseResult(text, engine_used, structured=None, tier_used=None, quality_score=1.0, duration_ms=0, cached=False, warnings=[], media_url=None, assets={})`；`.with_warning(str)`。
- Produces: `EngineHealth(available, detail="", server_tiers=None, server_version=None)`；`ParseEngine` Protocol（`name`、`async parse`、`async health`）。
- Produces: `MineruSettings(enabled=False, base_url="", api_key="", default_tier="standard", timeout_seconds=300.0, max_upload_mb=25, use_in_chat_attachment=True, min_quality_threshold=0.85)`；`.configured`。
- Produces: `MineruError(code, message, param=None, status_code=None)` 及子类 `MineruConfigError/MineruAuthError/MineruUnavailableError/MineruTimeoutError/MineruRemoteError`。
- Produces: `build_create_body(...)`、`MineruOutput`、`TaskSnapshot/TaskFile/UploadTarget`、`parse_task_snapshot(payload)`、`unpack_result_payload(payload, output_formats, status)`。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_document_parse_domain.py
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from backend.adapters.out.document_parse.mineru_errors import MineruRemoteError
from backend.adapters.out.document_parse.mineru_models import (
    build_create_body,
    parse_task_snapshot,
    unpack_result_payload,
)
from backend.domain.document_parse import MineruSettings, ParseRequest, ParseResult


def test_parse_request_extension_and_hash() -> None:
    req = ParseRequest(filename="论文.PDF", content_bytes=b"abc")
    assert req.extension == "pdf"
    assert req.content_hash() == hashlib.sha256(b"abc").hexdigest()


def test_with_warning_is_immutable() -> None:
    base = ParseResult(text="t", engine_used="local")
    bumped = base.with_warning("mineru_failed:timeout")
    assert base.warnings == []
    assert bumped.warnings == ["mineru_failed:timeout"]


def test_mineru_settings_configured_flag() -> None:
    assert MineruSettings().configured is False
    assert MineruSettings(base_url="http://10.0.0.8:8000").configured is True


def test_build_create_body_shape() -> None:
    body = build_create_body(
        filename="a.pdf",
        content=b"xyz",
        page_range="1-3",
        output_formats=["default"],
        tier="standard",
        ocr_mode=None,
    )
    assert body["files"][0]["file_name"] == "a.pdf"
    assert body["files"][0]["bytes"] == 3
    assert body["files"][0]["sha256sum"] == hashlib.sha256(b"xyz").hexdigest()
    assert body["files"][0]["page_range"] == "1-3"
    assert body["output_formats"] == ["default"]
    assert body["tier"] == "standard"
    assert "ocr_mode" not in body


def test_parse_task_snapshot_requires_identity() -> None:
    with pytest.raises(MineruRemoteError) as exc:
        parse_task_snapshot({"task_id": "", "status": "pending", "files": []})
    assert exc.value.code == "invalid_response"


def test_unpack_default_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("markdown.md", "# hi")
        zf.writestr("middle_json.json", json.dumps({"pages": []}))
        zf.writestr("images/a.png", b"png")
    out = unpack_result_payload(buf.getvalue(), ["default"], "completed")
    assert out.markdown == "# hi"
    assert out.structured == {"pages": []}
    assert out.images == {"images/a.png": b"png"}
    assert out.file_bytes is None


def test_unpack_bare_docx() -> None:
    out = unpack_result_payload(b"PKdocx", ["docx"], "completed")
    assert out.file_bytes == b"PKdocx"
    assert out.file_ext == "docx"
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_domain.py -q`
Expected: `ModuleNotFoundError: No module named 'backend.domain.document_parse'`

- [x] **Step 3: 写实现**

`backend/domain/document_parse.py`：

```python
"""文档解析领域契约：纯数据 + Protocol，不依赖任何适配器。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

ENGINE_AUTO = "auto"
ENGINE_LOCAL = "local"
ENGINE_MINERU = "mineru"
ENGINE_CHOICES = (ENGINE_AUTO, ENGINE_LOCAL, ENGINE_MINERU)

OUTPUT_MARKDOWN = "markdown"
OUTPUT_STRUCTURED = "structured"
OUTPUT_DOCX = "docx"
OUTPUT_HTML = "html"
OUTPUT_CHOICES = (OUTPUT_MARKDOWN, OUTPUT_STRUCTURED, OUTPUT_DOCX, OUTPUT_HTML)

DEFAULT_MIN_QUALITY = 0.85
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_UPLOAD_MB = 25
DEFAULT_TIER = "standard"


@dataclass(frozen=True)
class MineruSettings:
    """MinerU 服务端配置（已解密；api_key 只允许停留在内存）。"""

    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    default_tier: str = DEFAULT_TIER
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB
    use_in_chat_attachment: bool = True
    min_quality_threshold: float = DEFAULT_MIN_QUALITY

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip())


@dataclass(frozen=True)
class ParseRequest:
    filename: str
    content_bytes: bytes
    engine_hint: str = ENGINE_AUTO
    output_format: str = OUTPUT_MARKDOWN
    page_range: Optional[str] = None
    tier: Optional[str] = None
    timeout_seconds: Optional[float] = None
    source_path: Optional[str] = None
    media_id: Optional[str] = None

    @property
    def extension(self) -> str:
        name = self.filename or ""
        if "." not in name:
            return ""
        return name.rsplit(".", 1)[-1].lower()

    def content_hash(self) -> str:
        return hashlib.sha256(self.content_bytes).hexdigest()


@dataclass(frozen=True)
class ParseResult:
    text: str
    engine_used: str
    structured: Optional[Dict[str, Any]] = None
    tier_used: Optional[str] = None
    quality_score: float = 1.0
    duration_ms: int = 0
    cached: bool = False
    warnings: List[str] = field(default_factory=list)
    media_url: Optional[str] = None
    assets: Dict[str, str] = field(default_factory=dict)

    def with_warning(self, warning: str) -> "ParseResult":
        return ParseResult(
            text=self.text,
            engine_used=self.engine_used,
            structured=self.structured,
            tier_used=self.tier_used,
            quality_score=self.quality_score,
            duration_ms=self.duration_ms,
            cached=self.cached,
            warnings=[*self.warnings, warning],
            media_url=self.media_url,
            assets=dict(self.assets),
        )


@dataclass(frozen=True)
class EngineHealth:
    available: bool
    detail: str = ""
    server_tiers: Optional[List[str]] = None
    server_version: Optional[str] = None


class ParseEngine(Protocol):
    name: str

    async def parse(self, request: ParseRequest) -> ParseResult: ...

    async def health(self) -> EngineHealth: ...
```

`backend/adapters/out/document_parse/__init__.py`：

```python
"""文档解析出站适配器（MinerU HTTP 客户端、本地引擎、质量打分）。"""
```

`backend/adapters/out/document_parse/mineru_errors.py`：

```python
"""MinerU 客户端错误类型（code 语义对齐服务端 error.code）。"""

from __future__ import annotations

from typing import Optional


class MineruError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        param: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.param = param
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


class MineruConfigError(MineruError):
    """本机配置缺失/被禁用（不发起网络请求）。"""


class MineruAuthError(MineruError):
    """服务端要求鉴权，但 key 缺失或无效。"""


class MineruUnavailableError(MineruError):
    """传输层不可达（DNS/连接/读超时等）。"""


class MineruTimeoutError(MineruError):
    """任务级墙钟超时（已尝试 cancel）。"""


class MineruRemoteError(MineruError):
    """服务端返回的 4xx/5xx 或任务失败。"""
```

`backend/adapters/out/document_parse/mineru_models.py`：

```python
"""MinerU v1 Tasks 响应模型、请求体与结果包解包（纯函数）。"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .mineru_errors import MineruRemoteError

TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "canceled"})
FILE_STATUSES = frozenset(
    {"waiting-file", "pending", "running", "completed", "failed", "canceled"}
)
_MAX_ZIP_MEMBERS = 5000


@dataclass(frozen=True)
class UploadTarget:
    url: str
    headers: Dict[str, str]


@dataclass(frozen=True)
class TaskFile:
    file_id: Optional[str]
    file_name: str
    status: str
    size: Optional[int]
    upload: Optional[UploadTarget]
    result_url: Optional[str]


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    status: str
    files: List[TaskFile]
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class MineruOutput:
    markdown: str = ""
    structured: Optional[Dict[str, Any]] = None
    images: Dict[str, bytes] = field(default_factory=dict)
    file_bytes: Optional[bytes] = None
    file_ext: Optional[str] = None
    status: str = "completed"


def build_create_body(
    *,
    filename: str,
    content: bytes,
    page_range: Optional[str],
    output_formats: Sequence[str],
    tier: Optional[str],
    ocr_mode: Optional[str],
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "file_name": filename,
        "bytes": len(content),
        "sha256sum": hashlib.sha256(content).hexdigest(),
    }
    if page_range:
        item["page_range"] = page_range
    body: Dict[str, Any] = {"files": [item], "output_formats": list(output_formats)}
    if tier:
        body["tier"] = tier
    if ocr_mode:
        body["ocr_mode"] = ocr_mode
    return body


def _upload_target(raw: Any, file_status: str) -> Optional[UploadTarget]:
    if raw is None:
        return None
    if not isinstance(raw, dict) or file_status != "waiting-file":
        raise MineruRemoteError("invalid_response", "invalid task upload descriptor")
    url = raw.get("url")
    headers = raw.get("headers") or {}
    if not isinstance(url, str) or not url:
        raise MineruRemoteError("invalid_response", "upload.url missing")
    if not isinstance(headers, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
    ):
        raise MineruRemoteError("invalid_response", "upload.headers must be a string mapping")
    return UploadTarget(url=url, headers=dict(headers))


def parse_task_snapshot(payload: Any) -> TaskSnapshot:
    if not isinstance(payload, dict):
        raise MineruRemoteError("invalid_response", "response must be a JSON object")
    task_id = payload.get("task_id")
    status = payload.get("status")
    files = payload.get("files")
    if (
        not isinstance(task_id, str)
        or not task_id
        or not isinstance(status, str)
        or status not in FILE_STATUSES | TERMINAL_STATUSES
        or not isinstance(files, list)
        or len(files) != 1
        or not isinstance(files[0], dict)
    ):
        raise MineruRemoteError("invalid_response", "inconsistent Tasks response")
    item = files[0]
    file_status = item.get("status")
    if not isinstance(file_status, str) or file_status not in FILE_STATUSES:
        raise MineruRemoteError("invalid_response", "invalid task file state")
    name = item.get("file_name")
    if not isinstance(name, str) or not name:
        raise MineruRemoteError("invalid_response", "task file_name missing")
    task_file = TaskFile(
        file_id=item.get("file_id") if isinstance(item.get("file_id"), str) else None,
        file_name=name,
        status=file_status,
        size=item.get("bytes") if isinstance(item.get("bytes"), int) else None,
        upload=_upload_target(item.get("upload"), file_status),
        result_url=item.get("result_url")
        if isinstance(item.get("result_url"), str)
        else None,
    )
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    return TaskSnapshot(
        task_id=task_id,
        status=status,
        files=[task_file],
        error_code=error.get("code") if isinstance(error.get("code"), str) else None,
        error_message=error.get("message")
        if isinstance(error.get("message"), str)
        else None,
    )


def unpack_result_payload(
    payload: bytes,
    output_formats: Sequence[str],
    status: str,
) -> MineruOutput:
    formats = list(output_formats)
    if formats in (["docx"], ["html"]):
        return MineruOutput(file_bytes=payload, file_ext=formats[0], status=status)
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise MineruRemoteError("invalid_zip_output", "result is not a valid ZIP") from exc
    with archive:
        names = archive.namelist()
        if len(names) > _MAX_ZIP_MEMBERS:
            raise MineruRemoteError("invalid_zip_output", "result ZIP has too many members")
        name_set = set(names)
        markdown = (
            archive.read("markdown.md").decode("utf-8", "replace")
            if "markdown.md" in name_set
            else ""
        )
        structured: Optional[Dict[str, Any]] = None
        for candidate in ("middle_json.json", "layout.json"):
            if candidate not in name_set:
                continue
            try:
                loaded = json.loads(archive.read(candidate))
            except json.JSONDecodeError as exc:
                raise MineruRemoteError(
                    "invalid_middle_json_output", "middle_json is not valid JSON"
                ) from exc
            if isinstance(loaded, dict):
                structured = loaded
            break
        images = {
            name: archive.read(name)
            for name in sorted(name_set)
            if name.startswith("images/") and not name.endswith("/")
        }
    return MineruOutput(
        markdown=markdown,
        structured=structured,
        images=images,
        status=status,
    )
```

- [x] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_domain.py -q`
Expected: 7 passed

- [x] **Step 5: ruff + commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/domain/document_parse.py backend/adapters/out/document_parse backend/tests/unit/test_document_parse_domain.py
git add backend/domain/document_parse.py backend/adapters/out/document_parse backend/tests/unit/test_document_parse_domain.py
git commit -m "feat(document-parse): 领域契约与 MinerU 响应模型"
```

---

### Task 2: MinerU v1 异步客户端

**Files:**
- Create: `backend/adapters/out/document_parse/mineru_client.py`
- Test: `backend/tests/unit/test_mineru_client.py`

**Interfaces:**
- Consumes: Task 1 的 `build_create_body/parse_task_snapshot/unpack_result_payload/MineruOutput` 与错误类型。
- Produces: `MineruClient(base_url, api_key="", timeout_seconds=300.0, poll_interval=1.0, transport=None)`。
  - `async parse_bytes(content, filename, *, page_range=None, output_formats=("default",), tier=None, ocr_mode=None, timeout_seconds=None) -> MineruOutput`
  - `async probe() -> Dict[str, Any]`（键：`reachable/serverAuthMode/serverTiers/serverVersion/reason/accessLevel`，**永不抛异常**）
  - `async cancel(task_id) -> None`

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_mineru_client.py
from __future__ import annotations

import asyncio
import io
import json
import zipfile

import httpx
import pytest

from backend.adapters.out.document_parse.mineru_client import MineruClient
from backend.adapters.out.document_parse.mineru_errors import (
    MineruAuthError,
    MineruTimeoutError,
)


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("markdown.md", "# parsed")
        zf.writestr("middle_json.json", json.dumps({"pages": [1]}))
    return buf.getvalue()


def _handler(record: list):
    state = {"polls": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        record.append(
            (request.method, request.url.path, request.headers.get("authorization"))
        )
        path = request.url.path
        if request.method == "POST" and path.endswith("/v1/tasks"):
            return httpx.Response(
                200,
                json={
                    "task_id": "t1",
                    "status": "waiting-file",
                    "files": [
                        {
                            "file_id": "f1",
                            "file_name": "a.pdf",
                            "status": "waiting-file",
                            "upload": {
                                "url": "/files/f1",
                                "headers": {"x-presigned": "1"},
                            },
                        }
                    ],
                },
            )
        if request.method == "PUT" and path.endswith("/files/f1"):
            assert request.headers.get("x-presigned") == "1"
            return httpx.Response(200)
        if path.endswith("/v1/tasks/t1"):
            state["polls"] += 1
            done = state["polls"] >= 2
            return httpx.Response(
                200,
                json={
                    "task_id": "t1",
                    "status": "completed" if done else "pending",
                    "files": [
                        {
                            "file_id": "f1",
                            "file_name": "a.pdf",
                            "status": "completed" if done else "running",
                            "result_url": "/v1/files/f1/content",
                        }
                    ],
                },
            )
        if path.endswith("/v1/files/f1/content"):
            return httpx.Response(200, content=_zip_bytes())
        return httpx.Response(
            404, json={"error": {"code": "not_found", "message": path}}
        )

    return handle


def test_parse_bytes_happy_path() -> None:
    record: list = []
    client = MineruClient(
        "http://mineru.local:8000",
        api_key="k",
        poll_interval=0.0,
        transport=httpx.MockTransport(_handler(record)),
    )
    out = asyncio.run(client.parse_bytes(b"%PDF-1.4", "a.pdf", tier="standard"))
    assert out.markdown == "# parsed"
    assert out.structured == {"pages": [1]}
    assert record[0][0] == "POST"
    assert record[0][2] == "Bearer k"
    assert any(r[0] == "PUT" for r in record)


def test_auth_error_is_mapped() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"code": "invalid_api_key", "message": "bad key"}}
        )

    client = MineruClient(
        "http://mineru.local:8000", transport=httpx.MockTransport(handle)
    )
    with pytest.raises(MineruAuthError) as exc:
        asyncio.run(client.parse_bytes(b"x", "a.pdf"))
    assert exc.value.code == "invalid_api_key"


def test_timeout_cancels_task() -> None:
    seen: list = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/v1/tasks"):
            return httpx.Response(
                200,
                json={
                    "task_id": "t2",
                    "status": "pending",
                    "files": [
                        {
                            "file_id": "f2",
                            "file_name": "a.pdf",
                            "status": "pending",
                        }
                    ],
                },
            )
        if request.url.path.endswith("/v1/tasks/t2/cancel"):
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "task_id": "t2",
                "status": "running",
                "files": [
                    {"file_id": "f2", "file_name": "a.pdf", "status": "running"}
                ],
            },
        )

    client = MineruClient(
        "http://mineru.local:8000",
        poll_interval=0.0,
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(MineruTimeoutError):
        asyncio.run(client.parse_bytes(b"x", "a.pdf", timeout_seconds=0.0))
    assert any(path.endswith("/v1/tasks/t2/cancel") for _, path in seen)


def test_probe_reports_auth_mode() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/usage"):
            return httpx.Response(200, json={"access_level": "registered"})
        return httpx.Response(404)

    client = MineruClient(
        "http://mineru.local:8000", api_key="k", transport=httpx.MockTransport(handle)
    )
    info = asyncio.run(client.probe())
    assert info["reachable"] is True
    assert info["serverAuthMode"] == "bearer"
    assert info["accessLevel"] == "registered"


def test_probe_never_raises_on_transport_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = MineruClient(
        "http://mineru.local:8000", transport=httpx.MockTransport(handle)
    )
    info = asyncio.run(client.probe())
    assert info["reachable"] is False
    assert info["reason"] == "unreachable"
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_mineru_client.py -q`
Expected: `ModuleNotFoundError`

- [x] **Step 3: 写实现**

`backend/adapters/out/document_parse/mineru_client.py`：

```python
"""MinerU v1 REST 异步客户端：create → upload → poll → download。"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlparse

import httpx

from .mineru_errors import (
    MineruAuthError,
    MineruConfigError,
    MineruRemoteError,
    MineruTimeoutError,
    MineruUnavailableError,
)
from .mineru_models import (
    TERMINAL_STATUSES,
    TaskSnapshot,
    build_create_body,
    parse_task_snapshot,
    unpack_result_payload,
)

_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BASE_DELAY = 0.25
_MAX_DELAY = 2.0
_MAX_REDIRECTS = 6


def _origin(url: str) -> Tuple[str, str, int]:
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class MineruClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 300.0,
        poll_interval: float = 1.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = (api_key or "").strip()
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval
        self._transport = transport
        self._sleep = sleep

    # ── 请求构造 ────────────────────────────────────────────────
    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": "Bearer " + self._api_key} if self._api_key else {}

    def _headers_for(self, url: str) -> Dict[str, str]:
        """跨源绝不转发 Authorization（上传 URL 可能是别的主机）。"""
        if _origin(url) != _origin(self.base_url):
            return {}
        return self._auth_headers()

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=30.0),
            trust_env=False,
            follow_redirects=False,
            transport=self._transport,
        )

    # ── 错误映射 ────────────────────────────────────────────────
    @staticmethod
    def _raise_for_response(response: httpx.Response) -> Dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code < 400:
            if not isinstance(payload, dict):
                raise MineruRemoteError("invalid_response", "response must be a JSON object")
            return payload
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or "unknown")
            message = str(error.get("message") or code)
            raw_param = error.get("param")
            param = str(raw_param) if raw_param is not None else None
        else:
            code = "http_error"
            message = "HTTP " + str(response.status_code)
            param = None
        if response.status_code in (401, 403) or code == "invalid_api_key":
            raise MineruAuthError(
                code, message, param=param, status_code=response.status_code
            )
        raise MineruRemoteError(
            code, message, param=param, status_code=response.status_code
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        content: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        retry: bool = False,
    ) -> Dict[str, Any]:
        attempts = _MAX_ATTEMPTS if retry else 1
        for attempt in range(1, attempts + 1):
            merged = dict(headers if headers is not None else self._headers_for(url))
            try:
                response = await client.request(
                    method, url, json=json_body, content=content, headers=merged
                )
            except httpx.HTTPError as exc:
                if attempt == attempts:
                    raise MineruUnavailableError("unavailable", str(exc)) from exc
                await self._sleep(self._delay(attempt))
                continue
            if response.status_code in _RETRYABLE_STATUSES and attempt < attempts:
                await self._sleep(self._delay(attempt))
                continue
            return self._raise_for_response(response)
        raise MineruUnavailableError("unavailable", "retry budget exhausted")

    @staticmethod
    def _delay(attempt: int) -> float:
        return min(_MAX_DELAY, _BASE_DELAY * (2 ** (attempt - 1)))

    # ── 四步协议 ────────────────────────────────────────────────
    async def _create(
        self, client: httpx.AsyncClient, body: Dict[str, Any]
    ) -> TaskSnapshot:
        payload = await self._request(
            client, "POST", self._url("/v1/tasks"), json_body=body, retry=False
        )
        return parse_task_snapshot(payload)

    async def _query(self, client: httpx.AsyncClient, task_id: str) -> TaskSnapshot:
        payload = await self._request(
            client, "GET", self._url("/v1/tasks/" + quote(task_id, safe="")), retry=True
        )
        return parse_task_snapshot(payload)

    async def _upload(
        self,
        client: httpx.AsyncClient,
        snapshot: TaskSnapshot,
        content: bytes,
    ) -> TaskSnapshot:
        target = snapshot.files[0].upload
        if snapshot.files[0].status != "waiting-file" or target is None:
            return snapshot
        url = urljoin(self.base_url + "/", target.url.lstrip("/"))
        headers = dict(target.headers)
        headers.update(self._headers_for(url))
        last_error: Optional[BaseException] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await client.request(
                    "PUT", url, content=content, headers=headers
                )
                if response.status_code >= 400:
                    self._raise_for_response(response)
                return await self._query(client, snapshot.task_id)
            except MineruAuthError:
                raise
            except MineruRemoteError as exc:
                if exc.status_code not in _RETRYABLE_STATUSES:
                    raise
                last_error = exc
            except MineruUnavailableError as exc:
                last_error = exc
            if attempt == _MAX_ATTEMPTS:
                break
            await self._sleep(self._delay(attempt))
            snapshot = await self._query(client, snapshot.task_id)
            target = snapshot.files[0].upload
            if snapshot.files[0].status != "waiting-file" or target is None:
                return snapshot
            url = urljoin(self.base_url + "/", target.url.lstrip("/"))
            headers = dict(target.headers)
            headers.update(self._headers_for(url))
        raise MineruUnavailableError(
            "upload_failed", str(last_error or "upload failed")
        )

    async def _download(self, client: httpx.AsyncClient, result_url: str) -> bytes:
        url = urljoin(self.base_url + "/", result_url.lstrip("/"))
        for _ in range(_MAX_REDIRECTS):
            response = await client.get(url, headers=self._headers_for(url))
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise MineruRemoteError(
                        "invalid_response", "download redirect missing Location"
                    )
                url = urljoin(url, location)
                continue
            if response.status_code >= 400:
                self._raise_for_response(response)
            return response.content
        raise MineruRemoteError("invalid_response", "too many download redirects")

    async def cancel(self, task_id: str) -> None:
        try:
            async with self._client() as client:
                await client.post(
                    self._url("/v1/tasks/" + quote(task_id, safe="") + "/cancel"),
                    headers=self._auth_headers(),
                    timeout=5.0,
                )
        except httpx.HTTPError:
            return

    async def parse_bytes(
        self,
        content: bytes,
        filename: str,
        *,
        page_range: Optional[str] = None,
        output_formats: Sequence[str] = ("default",),
        tier: Optional[str] = None,
        ocr_mode: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        if not self.base_url:
            raise MineruConfigError("not_configured", "MinerU baseUrl is empty")
        timeout = self._timeout if timeout_seconds is None else timeout_seconds
        body = build_create_body(
            filename=filename,
            content=content,
            page_range=page_range,
            output_formats=output_formats,
            tier=tier,
            ocr_mode=ocr_mode,
        )
        async with self._client() as client:
            snapshot = await self._create(client, body)
            snapshot = await self._query(client, snapshot.task_id)
            snapshot = await self._upload(client, snapshot, content)
            deadline = time.monotonic() + timeout
            while snapshot.status not in TERMINAL_STATUSES:
                if time.monotonic() >= deadline:
                    await self.cancel(snapshot.task_id)
                    raise MineruTimeoutError(
                        "timeout", "task " + snapshot.task_id + " did not finish"
                    )
                await self._sleep(self._poll_interval)
                snapshot = await self._query(client, snapshot.task_id)
                snapshot = await self._upload(client, snapshot, content)
            if snapshot.status in ("failed", "canceled"):
                raise MineruRemoteError(
                    snapshot.error_code or snapshot.status,
                    snapshot.error_message or ("task " + snapshot.status),
                )
            if snapshot.files[0].status != "completed":
                raise MineruRemoteError("parse_failed", "task file did not complete")
            result_url = snapshot.files[0].result_url
            if not result_url:
                raise MineruRemoteError(
                    "invalid_response", "completed task missing result_url"
                )
            payload = await self._download(client, result_url)
        return unpack_result_payload(payload, output_formats, snapshot.status)

    # ── 健康探测 ────────────────────────────────────────────────
    async def probe(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "reachable": False,
            "serverAuthMode": "unknown",
            "serverTiers": None,
            "serverVersion": None,
            "reason": "",
            "accessLevel": None,
        }
        if not self.base_url:
            base["reason"] = "not_configured"
            return base
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=5.0),
                trust_env=False,
                transport=self._transport,
            ) as client:
                usage = await client.get(
                    self._url("/v1/usage"), headers=self._auth_headers()
                )
                if usage.status_code == 200:
                    data = usage.json() if usage.content else {}
                    base.update(
                        reachable=True,
                        serverAuthMode="bearer" if self._api_key else "anonymous",
                        accessLevel=data.get("access_level")
                        if isinstance(data, dict)
                        else None,
                    )
                    return base
                if usage.status_code in (401, 403):
                    base.update(
                        reachable=True,
                        serverAuthMode="required",
                        reason="api_key_required_or_invalid",
                    )
                    return base
                for path, key in (
                    ("/v1/tiers", "serverTiers"),
                    ("/v1/health", "serverVersion"),
                ):
                    response = await client.get(self._url(path))
                    if response.status_code != 200:
                        continue
                    try:
                        data = response.json()
                    except ValueError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    base["reachable"] = True
                    if key == "serverTiers":
                        tiers = data.get("tiers") or data.get("available_tiers")
                        if isinstance(tiers, list):
                            base["serverTiers"] = [str(t) for t in tiers]
                    else:
                        version = data.get("version")
                        if isinstance(version, str):
                            base["serverVersion"] = version
                if base["reachable"]:
                    return base
                base["reason"] = "unreachable"
                return base
        except (httpx.HTTPError, ValueError):
            base["reason"] = "unreachable"
            return base
```

- [x] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_mineru_client.py -q`
Expected: 5 passed

- [x] **Step 5: ruff + commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/adapters/out/document_parse backend/tests/unit/test_mineru_client.py
git add backend/adapters/out/document_parse/mineru_client.py backend/tests/unit/test_mineru_client.py
git commit -m "feat(document-parse): MinerU v1 异步客户端（create/upload/poll/download）"
```

---

### Task 3: MinerU 配置加载 + SecretBox 字段加密 + preferences 白名单

**Files:**
- Create: `backend/services/document_parse/__init__.py`
- Create: `backend/services/document_parse/config.py`
- Modify: `backend/services/secret_box.py`
- Modify: `backend/data/settings_repo.py`
- Test: `backend/tests/unit/test_mineru_config.py`

**Interfaces:**
- Consumes: Task 1 的 `MineruSettings`。
- Produces: `MINERU_CONFIG_KEY = "mineru_service"`；`load_mineru_settings() -> MineruSettings`（env 优先 → preferences → 默认值；任何异常回默认值）。
- Produces: `wrap_mineru_service_json(raw: str) -> str`、`unwrap_mineru_service_json(raw: str) -> str`（字段 `apiKey` ↔ 加密账户 `mineru:api_key`）。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_mineru_config.py
from __future__ import annotations

import json

from backend.domain.document_parse import MineruSettings
from backend.services.document_parse import config as config_mod
from backend.services.secret_box import (
    is_wrapped,
    unwrap_mineru_service_json,
    wrap_mineru_service_json,
)


def test_secret_box_wraps_api_key_only() -> None:
    raw = json.dumps({"enabled": True, "baseUrl": "http://m:8000", "apiKey": "sk-synthetic"})
    wrapped = json.loads(wrap_mineru_service_json(raw))
    assert wrapped["enabled"] is True
    assert wrapped["baseUrl"] == "http://m:8000"
    assert is_wrapped(wrapped["apiKey"]) is True
    assert unwrap_mineru_service_json(json.dumps(wrapped)) == raw


def test_secret_box_is_idempotent() -> None:
    raw = json.dumps({"apiKey": "sk-synthetic"})
    once = wrap_mineru_service_json(raw)
    assert wrap_mineru_service_json(once) == once


def test_load_settings_prefers_env(monkeypatch) -> None:
    monkeypatch.setattr(config_mod, "_read_preference", lambda: {"apiKey": "pref"})
    monkeypatch.setenv("SAGE_MINERU_BASE_URL", "http://env:8000")
    monkeypatch.setenv("SAGE_MINERU_API_KEY", "sk-synthetic-env")
    monkeypatch.setenv("SAGE_MINERU_TIER", "advanced")
    settings = config_mod.load_mineru_settings()
    assert isinstance(settings, MineruSettings)
    assert settings.base_url == "http://env:8000"
    assert settings.api_key == "sk-synthetic-env"
    assert settings.default_tier == "advanced"


def test_load_settings_falls_back_to_defaults(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(config_mod, "_read_preference", boom)
    for name in (
        "SAGE_MINERU_BASE_URL",
        "SAGE_MINERU_API_KEY",
        "SAGE_MINERU_TIER",
        "SAGE_MINERU_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = config_mod.load_mineru_settings()
    assert settings.enabled is False
    assert settings.base_url == ""
    assert settings.default_tier == "standard"
    assert settings.timeout_seconds == 300.0
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_mineru_config.py -q`
Expected: ImportError

- [x] **Step 3: 写实现**

在 `backend/services/secret_box.py` 的 search_config 两个函数之后追加（复用同款逐字段逻辑；`List`/`Tuple` 已在文件顶部导入，否则补 `from typing import List, Tuple`）：

```python
#: MinerU 服务配置里需要静态加密的字段：(JSON 字段名, 加密账户名)
_MINERU_SERVICE_KEY_FIELDS: List[Tuple[str, str]] = [("apiKey", "mineru:api_key")]


def wrap_mineru_service_json(raw: str) -> str:
    """把 mineru_service 配置中的 apiKey 字段加密；失败 fail-open 保留明文。"""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(data, dict):
        return raw
    for field, account in _MINERU_SERVICE_KEY_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value and not is_wrapped(value):
            try:
                data[field] = encrypt_secret(value, account)
            except Exception:  # noqa: BLE001 — 加密失败不阻断保存
                logger.warning("mineru_service 字段加密失败: %s", field)
    return json.dumps(data, ensure_ascii=False)


def unwrap_mineru_service_json(raw: str) -> str:
    """与 :func:`wrap_mineru_service_json` 对称；单字段解密失败置空。"""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(data, dict):
        return raw
    for field, account in _MINERU_SERVICE_KEY_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and is_wrapped(value):
            try:
                data[field] = decrypt_secret(value, account)
            except Exception:  # noqa: BLE001 — fail-open 为空串，避免泄漏密文
                logger.warning("mineru_service 字段解密失败: %s", field)
                data[field] = ""
    return json.dumps(data, ensure_ascii=False)
```

`backend/data/settings_repo.py`：
- `KEYS` 中在 `"ocr_config"` 之后加 `"mineru_service"`。
- `get()` 的按 key 钩子分支追加：
```python
        if key == "mineru_service" and value is not None:
            from backend.services.secret_box import unwrap_mineru_service_json

            value = unwrap_mineru_service_json(value)
```
- `set()` 的按 key 钩子分支追加（与 app_settings/search_config 同位置）：
```python
        if key == "mineru_service":
            from backend.services.secret_box import wrap_mineru_service_json

            value = wrap_mineru_service_json(value)
```

`backend/services/document_parse/__init__.py`：

```python
"""文档解析服务层：配置、缓存、后台队列与装配。"""
```

`backend/services/document_parse/config.py`：

```python
"""MinerU 配置加载：env > preferences（解密） > 默认值。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from backend.domain.document_parse import (
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_MIN_QUALITY,
    DEFAULT_TIER,
    DEFAULT_TIMEOUT_SECONDS,
    MineruSettings,
)

logger = logging.getLogger(__name__)

MINERU_CONFIG_KEY = "mineru_service"


def _read_preference() -> Dict[str, Any]:
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(MINERU_CONFIG_KEY)
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — 配置读取失败退回默认值
        return {}


def _pick(raw: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return None


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, parsed))


def _as_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, parsed))


def _env_str(name: str) -> str:
    return os.environ.get(name, "").strip()


def load_mineru_settings() -> MineruSettings:
    raw = _read_preference()
    try:
        base_url = _env_str("SAGE_MINERU_BASE_URL") or str(
            _pick(raw, "baseUrl", "base_url") or ""
        ).strip()
        api_key = _env_str("SAGE_MINERU_API_KEY") or str(
            _pick(raw, "apiKey", "api_key") or ""
        ).strip()
        tier = _env_str("SAGE_MINERU_TIER") or str(
            _pick(raw, "defaultTier", "default_tier") or DEFAULT_TIER
        ).strip()
        timeout_raw = _env_str("SAGE_MINERU_TIMEOUT_SECONDS")
        timeout = _as_float(
            timeout_raw or _pick(raw, "timeoutSeconds", "timeout_seconds"),
            DEFAULT_TIMEOUT_SECONDS,
            5.0,
            3600.0,
        )
        return MineruSettings(
            enabled=_as_bool(_pick(raw, "enabled"), False),
            base_url=base_url,
            api_key=api_key,
            default_tier=tier or DEFAULT_TIER,
            timeout_seconds=timeout,
            max_upload_mb=_as_int(
                _pick(raw, "maxUploadMb", "max_upload_mb"),
                DEFAULT_MAX_UPLOAD_MB,
                1,
                200,
            ),
            use_in_chat_attachment=_as_bool(
                _pick(raw, "useInChatAttachment", "use_in_chat_attachment"), True
            ),
            min_quality_threshold=_as_float(
                _pick(raw, "minQualityThreshold", "min_quality_threshold"),
                DEFAULT_MIN_QUALITY,
                0.0,
                1.0,
            ),
        )
    except Exception:  # noqa: BLE001 — 配置异常不得阻断解析链路
        logger.warning("MinerU 配置解析失败，使用默认值", exc_info=True)
        return MineruSettings()
```

- [x] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_mineru_config.py -q`
Expected: 全绿

再跑既有 settings 守卫（若存在）：
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -q -k "settings" `
Expected: 全绿

- [x] **Step 5: ruff + commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/services/document_parse backend/services/secret_box.py backend/data/settings_repo.py backend/tests/unit/test_mineru_config.py
git add backend/services/document_parse backend/services/secret_box.py backend/data/settings_repo.py backend/tests/unit/test_mineru_config.py
git commit -m "feat(document-parse): MinerU 配置加载与 apiKey 静态加密"
```

---

### Task 4: 附件文本提取下沉 services + 质量信号 + 本地引擎

**Files:**
- Create: `backend/services/attachment_extract.py`
- Modify: `backend/api/chat_attachment_routes.py`（改为 re-export，删除已迁出实现）
- Create: `backend/adapters/out/document_parse/quality.py`
- Create: `backend/adapters/out/document_parse/local_engine.py`
- Test: `backend/tests/unit/test_quality_and_local_engine.py`

**Interfaces:**
- Consumes: 现有 `_extract_document_text` 等实现；`backend.core.lazy.load_module`。
- Produces: `backend.services.attachment_extract`：`EXTRACTABLE_DOC_EXTENSIONS`、`MAX_ATTACHMENT_PARSE_SECONDS`、`MAX_OFFICE_ZIP_MEMBERS`、`MAX_OFFICE_UNCOMPRESSED_BYTES`、`CH_NL`、`extract_attachment_text(content, ext) -> str`、`async extract_attachment_text_async(content, ext) -> str`、`_extract_document_text`、`_extract_pptx_text`、`_guard_office_zip_budget`、模块级 `__getattr__`（惰性 openpyxl/pymupdf/python-docx）。
- Produces: `QualitySignals(page_count, text_per_page, blank_page_ratio, has_table, has_formula)`；`score_quality(signals) -> float`；`compute_pdf_signals(content) -> Optional[QualitySignals]`。
- Produces: `LocalEngine(extractor=None)`（`name = "local"`，`async parse`，`async health`）。

- [x] **Step 1: 迁移提取函数（保持行为字节级一致）**

把 `backend/api/chat_attachment_routes.py` 中以下内容**原样**移到 `backend/services/attachment_extract.py`（连同其私有辅助函数与所需常量）：
`EXTRACTABLE_DOC_EXTENSIONS`、`MAX_ATTACHMENT_PARSE_SECONDS`、`MAX_OFFICE_ZIP_MEMBERS`、`MAX_OFFICE_UNCOMPRESSED_BYTES`、`CH_NL`、模块 `__getattr__`、`extract_attachment_text`、`extract_attachment_text_async`、`_extract_document_text`、`_extract_pptx_text`、`_guard_office_zip_budget`。
迁移时**只**搬运被这些函数引用的常量/辅助（如 `ALLOWED_TEXT_*`、`CH_NL`）；不要搬运 FastAPI 路由、pydantic 模型和 `MEDIA_ROOT` 相关代码。
路由模块顶部改为 re-export（`import name as name` 形式同时满足测试引用与 F401）：

```python
from backend.services.attachment_extract import (  # noqa: F401
    EXTRACTABLE_DOC_EXTENSIONS as EXTRACTABLE_DOC_EXTENSIONS,
    MAX_ATTACHMENT_PARSE_SECONDS as MAX_ATTACHMENT_PARSE_SECONDS,
    _extract_document_text as _extract_document_text,
    _guard_office_zip_budget as _guard_office_zip_budget,
    extract_attachment_text as extract_attachment_text,
    extract_attachment_text_async as extract_attachment_text_async,
)
```

- [x] **Step 2: 写失败测试**

```python
# backend/tests/unit/test_quality_and_local_engine.py
from __future__ import annotations

import asyncio

import pymupdf

from backend.adapters.out.document_parse.local_engine import LocalEngine
from backend.adapters.out.document_parse.quality import (
    QualitySignals,
    compute_pdf_signals,
    score_quality,
)
from backend.domain.document_parse import ParseRequest


def _pdf_bytes(text: str, pages: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_score_quality_full_penalties() -> None:
    signals = QualitySignals(1, 10.0, 0.9, True, True)
    assert score_quality(signals) == 0.0


def test_score_quality_clean_text() -> None:
    signals = QualitySignals(3, 2000.0, 0.0, False, False)
    assert score_quality(signals) == 1.0


def test_compute_pdf_signals_detects_blank_pages() -> None:
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc[0].insert_text((72, 72), "hello world " * 30)
    data = doc.tobytes()
    doc.close()
    signals = compute_pdf_signals(data)
    assert signals is not None
    assert signals.page_count == 2
    assert signals.blank_page_ratio == 0.5


def test_local_engine_returns_page_marked_text() -> None:
    engine = LocalEngine()
    result = asyncio.run(
        engine.parse(ParseRequest(filename="a.pdf", content_bytes=_pdf_bytes("hello")))
    )
    assert result.engine_used == "local"
    assert "--- page 1 ---" in result.text
    assert result.quality_score > 0.5
    assert result.duration_ms >= 0
```

> `--- page 1 ---` 断言依赖现有提取器对 PDF 的页标记格式；Task 4 执行时先用 `grep -n "page " backend/api/chat_attachment_routes.py backend/services/attachment_extract.py` 核对实际标记串，断言以实际实现为准（若现实现无页标记，则改为断言 `"hello" in result.text`）。

- [x] **Step 3: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_quality_and_local_engine.py -q`
Expected: ImportError

- [x] **Step 4: 写实现**

`backend/adapters/out/document_parse/quality.py`：

```python
"""PDF 解析质量信号与打分（纯函数；PyMuPDF 惰性导入）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_FORMULA_RE = re.compile(r"[∑∫√≈≠≤≥∂∞±×÷]|\\(frac|sum|int|sqrt|alpha|beta|theta)")


@dataclass(frozen=True)
class QualitySignals:
    page_count: int
    text_per_page: float
    blank_page_ratio: float
    has_table: bool
    has_formula: bool


def score_quality(signals: QualitySignals) -> float:
    score = 1.0
    if signals.text_per_page < 120:
        score -= 0.35
    if signals.blank_page_ratio > 0.5:
        score -= 0.30
    if signals.has_table:
        score -= 0.25
    if signals.has_formula:
        score -= 0.20
    return round(max(0.0, score), 3)


def compute_pdf_signals(content: bytes) -> Optional[QualitySignals]:
    from backend.core.lazy import load_module

    pymupdf = load_module("pymupdf")
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception:  # noqa: BLE001 — 损坏 PDF 交给本地提取器报错
        return None
    try:
        page_count = doc.page_count
        if page_count <= 0:
            return QualitySignals(0, 0.0, 1.0, False, False)
        texts = [page.get_text("text") for page in doc]
        total_chars = sum(len(t.strip()) for t in texts)
        blank = sum(1 for t in texts if not t.strip())
        has_table = False
        for page in doc:
            try:
                if page.find_tables().tables:
                    has_table = True
                    break
            except Exception:  # noqa: BLE001 — 单页表格探测失败不影响整体
                continue
        has_formula = bool(_FORMULA_RE.search("\n".join(texts)))
        return QualitySignals(
            page_count=page_count,
            text_per_page=round(total_chars / page_count, 2),
            blank_page_ratio=round(blank / page_count, 3),
            has_table=has_table,
            has_formula=has_formula,
        )
    finally:
        doc.close()
```

> `backend.core.lazy.load_module` 的签名以仓库实现为准（执行时 `grep -n "def load_module" -A 20 backend/core/lazy.py` 核对；若需额外参数，沿用 `chat_attachment_routes.__getattr__` 的现有调用形式）。

`backend/adapters/out/document_parse/local_engine.py`：

```python
"""本地解析引擎：复用聊天附件的纯文本提取，质量信号决定是否升级 MinerU。"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

from backend.domain.document_parse import (
    ENGINE_LOCAL,
    EngineHealth,
    ParseRequest,
    ParseResult,
)
from backend.services.attachment_extract import extract_attachment_text

from .quality import compute_pdf_signals, score_quality


class LocalEngine:
    name = ENGINE_LOCAL

    def __init__(
        self,
        extractor: Optional[Callable[[bytes, str], str]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._extractor = extractor or extract_attachment_text
        self._clock = clock

    async def parse(self, request: ParseRequest) -> ParseResult:
        loop = asyncio.get_running_loop()
        started = self._clock()
        text = await loop.run_in_executor(
            None, self._extractor, request.content_bytes, request.extension
        )
        quality = 1.0
        if request.extension == "pdf":
            signals = await loop.run_in_executor(
                None, compute_pdf_signals, request.content_bytes
            )
            if signals is not None:
                quality = score_quality(signals)
        return ParseResult(
            text=text,
            engine_used=ENGINE_LOCAL,
            quality_score=quality,
            duration_ms=int((self._clock() - started) * 1000),
        )

    async def health(self) -> EngineHealth:
        return EngineHealth(available=True, detail="local extractor")
```

- [x] **Step 5: 跑测试确认通过（含既有附件测试回归）**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_quality_and_local_engine.py backend/tests/unit/test_r39_pdf_docx_extract.py backend/tests/unit/test_attachment_pdf.py -q`
Expected: 全绿（re-export 保住了既有引用）

- [x] **Step 6: ruff + commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/services/attachment_extract.py backend/api/chat_attachment_routes.py backend/adapters/out/document_parse backend/tests/unit/test_quality_and_local_engine.py
git add backend/services/attachment_extract.py backend/api/chat_attachment_routes.py backend/adapters/out/document_parse/quality.py backend/adapters/out/document_parse/local_engine.py backend/tests/unit/test_quality_and_local_engine.py
git commit -m "refactor(document-parse): 提取器下沉 services + 质量信号 + 本地引擎"
```

---

### Task 5: SQLite 解析缓存（DDL + 仓储）

**Files:**
- Modify: `backend/data/database.py`（`init_db` 内新增 `document_parse_cache` 表）
- Create: `backend/services/document_parse/cache.py`
- Modify: `architecture-baseline.json`（`backend/data/database.py` 行数按实测）
- Test: `backend/tests/unit/test_document_parse_cache.py`

**Interfaces:**
- Produces: `SqliteParseCache(db=None)`，`get(content_hash, engine) -> Optional[ParseResult]`、`put(content_hash, engine, result) -> None`；任何异常都吞掉并记日志（缓存不得阻断解析）。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_document_parse_cache.py
from __future__ import annotations

from backend.data.database import Database
from backend.domain.document_parse import ParseResult
from backend.services.document_parse.cache import SqliteParseCache


def test_roundtrip(tmp_path) -> None:
    db = Database(str(tmp_path / "t.db"))
    db.init_db()
    cache = SqliteParseCache(db)
    result = ParseResult(
        text="hello",
        engine_used="mineru",
        structured={"pages": [1]},
        tier_used="standard",
        quality_score=0.9,
        duration_ms=12,
        warnings=["partial_result"],
        media_url=None,
        assets={"images/a.png": "/api/v1/media/x"},
    )
    cache.put("h1", "mineru", result)
    got = cache.get("h1", "mineru")
    assert got is not None
    assert got.text == "hello"
    assert got.structured == {"pages": [1]}
    assert got.tier_used == "standard"
    assert got.cached is True
    assert got.assets == {"images/a.png": "/api/v1/media/x"}
    assert cache.get("h1", "local") is None


def test_broken_db_never_raises() -> None:
    class Boom:
        def get_connection(self):
            raise RuntimeError("down")

    cache = SqliteParseCache(Boom())
    cache.put("h", "local", ParseResult(text="t", engine_used="local"))
    assert cache.get("h", "local") is None
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_cache.py -q`
Expected: ImportError

- [x] **Step 3: 写实现**

`backend/data/database.py`：在 `init_db` 的 schema 构建处（现有 `cursor.execute("""CREATE TABLE IF NOT EXISTS ...""")` 序列末尾）追加：

```python
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS document_parse_cache (
              content_hash TEXT NOT NULL,
              engine TEXT NOT NULL,
              tier TEXT,
              markdown TEXT,
              structured_json TEXT,
              images_dir TEXT,
              meta_json TEXT,
              created_at INTEGER NOT NULL,
              PRIMARY KEY (content_hash, engine)
            )
            """
        )
```

`backend/services/document_parse/cache.py`：

```python
"""document_parse_cache 的 SQLite 仓储（缓存失败一律降级为未命中）。"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from backend.data.database import Database, get_database
from backend.domain.document_parse import ParseResult

logger = logging.getLogger(__name__)


class SqliteParseCache:
    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db

    def _database(self) -> Database:
        if self._db is None:
            self._db = get_database()
        return self._db

    def get(self, content_hash: str, engine: str) -> Optional[ParseResult]:
        try:
            row = (
                self._database()
                .get_connection()
                .execute(
                    "SELECT tier, markdown, structured_json, images_dir, meta_json "
                    "FROM document_parse_cache WHERE content_hash=? AND engine=?",
                    (content_hash, engine),
                )
                .fetchone()
            )
        except Exception:  # noqa: BLE001 — 缓存不可用按未命中处理
            logger.warning("读取解析缓存失败", exc_info=True)
            return None
        if row is None:
            return None
        try:
            meta: Dict[str, Any] = json.loads(row["meta_json"] or "{}")
            structured = (
                json.loads(row["structured_json"]) if row["structured_json"] else None
            )
            assets = json.loads(row["images_dir"] or "{}")
        except (TypeError, ValueError):
            return None
        return ParseResult(
            text=row["markdown"] or "",
            engine_used=engine,
            structured=structured if isinstance(structured, dict) else None,
            tier_used=row["tier"],
            quality_score=float(meta.get("quality_score", 1.0)),
            duration_ms=int(meta.get("duration_ms", 0)),
            cached=True,
            warnings=list(meta.get("warnings") or []),
            media_url=meta.get("media_url"),
            assets=assets if isinstance(assets, dict) else {},
        )

    def put(self, content_hash: str, engine: str, result: ParseResult) -> None:
        meta = {
            "quality_score": result.quality_score,
            "duration_ms": result.duration_ms,
            "warnings": list(result.warnings),
            "media_url": result.media_url,
        }
        try:
            conn = self._database().get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO document_parse_cache "
                "(content_hash, engine, tier, markdown, structured_json, "
                "images_dir, meta_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    content_hash,
                    engine,
                    result.tier_used,
                    result.text,
                    json.dumps(result.structured, ensure_ascii=False)
                    if result.structured is not None
                    else None,
                    json.dumps(result.assets, ensure_ascii=False),
                    json.dumps(meta, ensure_ascii=False),
                    int(time.time()),
                ),
            )
            conn.commit()
        except Exception:  # noqa: BLE001 — 写缓存失败不影响本次解析
            logger.warning("写入解析缓存失败", exc_info=True)
```

- [x] **Step 4: 跑测试 + 棘轮 + 回填 baseline**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_cache.py -q
node scripts/architecture-check.mjs
```

若报 `backend/data/database.py` 超 baseline：把 `architecture-baseline.json` 中该文件值改为报错提示的实际行数，重跑至通过。

- [x] **Step 5: commit**

```bash
git add backend/data/database.py backend/services/document_parse/cache.py backend/tests/unit/test_document_parse_cache.py architecture-baseline.json
git commit -m "feat(document-parse): 解析结果 SQLite 缓存"
```

---

### Task 6: MinerU 引擎适配 + 编排服务（路由/熔断）

**Files:**
- Create: `backend/adapters/out/document_parse/mineru_engine.py`
- Create: `backend/application/document_parse.py`
- Test: `backend/tests/unit/test_document_parse_service.py`

**Interfaces:**
- Consumes: Task 1 契约、Task 2 `MineruClient`、Task 3 `MineruSettings`、Task 5 缓存协议。
- Produces: `MineruParseEngine(client, tier="standard", media_store_factory=None)`；`ParseResult.assets` 填 archive 图片名 → MediaStore api_url。
- Produces: `ParseCache` Protocol（`get/put`）。
- Produces: `CircuitBreaker(threshold=3, cooldown_seconds=60.0, clock=time.monotonic)`：`closed()`、`record_success()`、`record_failure()`。
- Produces: `DocumentParseService(*, local, mineru_factory, cache, settings_loader, breaker=None)`：`async parse(ParseRequest) -> ParseResult`。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_document_parse_service.py
from __future__ import annotations

import asyncio

from backend.adapters.out.document_parse.mineru_errors import MineruTimeoutError
from backend.application.document_parse import CircuitBreaker, DocumentParseService
from backend.domain.document_parse import (
    EngineHealth,
    MineruSettings,
    ParseRequest,
    ParseResult,
)


class FakeEngine:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result or ParseResult(text=name + " text", engine_used=name)
        self.error = error
        self.calls = 0

    async def parse(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    async def health(self):
        return EngineHealth(available=True)


class MemoryCache:
    def __init__(self):
        self.data = {}

    def get(self, content_hash, engine):
        return self.data.get((content_hash, engine))

    def put(self, content_hash, engine, result):
        self.data[(content_hash, engine)] = result


def _service(local, mineru, settings, cache=None, breaker=None):
    return DocumentParseService(
        local=local,
        mineru_factory=lambda _settings: mineru,
        cache=cache or MemoryCache(),
        settings_loader=lambda: settings,
        breaker=breaker,
    )


def _run(service, request):
    return asyncio.run(service.parse(request))


def test_high_quality_local_does_not_escalate() -> None:
    local = FakeEngine(
        "local", ParseResult(text="ok", engine_used="local", quality_score=0.95)
    )
    mineru = FakeEngine("mineru")
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x"),
    )
    assert result.engine_used == "local"
    assert mineru.calls == 0


def test_low_quality_escalates_to_mineru() -> None:
    local = FakeEngine(
        "local", ParseResult(text="", engine_used="local", quality_score=0.2)
    )
    mineru = FakeEngine(
        "mineru", ParseResult(text="good", engine_used="mineru", tier_used="standard")
    )
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x"),
    )
    assert result.engine_used == "mineru"


def test_hint_local_never_calls_mineru() -> None:
    local = FakeEngine(
        "local", ParseResult(text="", engine_used="local", quality_score=0.0)
    )
    mineru = FakeEngine("mineru")
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x", engine_hint="local"),
    )
    assert result.engine_used == "local"
    assert mineru.calls == 0


def test_non_pdf_never_escalates() -> None:
    local = FakeEngine(
        "local", ParseResult(text="", engine_used="local", quality_score=0.0)
    )
    mineru = FakeEngine("mineru")
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.docx", content_bytes=b"x"),
    )
    assert mineru.calls == 0


def test_mineru_failure_falls_back_with_warning() -> None:
    local = FakeEngine(
        "local", ParseResult(text="low", engine_used="local", quality_score=0.1)
    )
    mineru = FakeEngine("mineru", error=MineruTimeoutError("timeout", "slow"))
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x"),
    )
    assert result.engine_used == "local"
    assert any(w.startswith("mineru_failed") for w in result.warnings)


def test_breaker_opens_after_three_failures() -> None:
    breaker = CircuitBreaker(threshold=3)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.closed() is False


def test_cache_short_circuits_repeat_parse() -> None:
    local = FakeEngine("local", ParseResult(text="c", engine_used="local"))
    mineru = FakeEngine("mineru")
    cache = MemoryCache()
    service = _service(local, mineru, MineruSettings(), cache=cache)
    req = ParseRequest(filename="a.txt", content_bytes=b"same")
    _run(service, req)
    second = _run(service, req)
    assert second.cached is True
    assert local.calls == 1
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_service.py -q`
Expected: ImportError

- [x] **Step 3: 写实现**

`backend/adapters/out/document_parse/mineru_engine.py`：

```python
"""MinerU 引擎适配：调用客户端并把 docx/html 产物与图片落 MediaStore。"""

from __future__ import annotations

import json
import time
from typing import Callable, Dict, Optional

from backend.domain.document_parse import (
    ENGINE_MINERU,
    OUTPUT_DOCX,
    OUTPUT_HTML,
    OUTPUT_STRUCTURED,
    EngineHealth,
    ParseRequest,
    ParseResult,
)

from .mineru_client import MineruClient


class MineruParseEngine:
    name = ENGINE_MINERU

    def __init__(
        self,
        client: MineruClient,
        tier: str = "standard",
        media_store_factory: Optional[Callable[[], object]] = None,
    ) -> None:
        self._client = client
        self._tier = tier
        self._media_store_factory = media_store_factory
        self._store = None

    def _media_store(self):
        if self._store is None:
            from backend.services.multimodal.media_store import MEDIA_ROOT, MediaKind, MediaStore

            self._store = (
                self._media_store_factory()
                if self._media_store_factory is not None
                else MediaStore(root=MEDIA_ROOT)
            )
            self._media_kind = MediaKind
        return self._store

    async def parse(self, request: ParseRequest) -> ParseResult:
        started = time.monotonic()
        if request.output_format == OUTPUT_DOCX:
            formats = ["docx"]
        elif request.output_format == OUTPUT_HTML:
            formats = ["html"]
        else:
            formats = ["default"]
        target_tier = request.tier or self._tier
        output = await self._client.parse_bytes(
            request.content_bytes,
            request.filename,
            page_range=request.page_range,
            output_formats=formats,
            tier=target_tier,
            timeout_seconds=request.timeout_seconds,
        )
        warnings = ["partial_result"] if output.status == "partial" else []
        store = self._media_store()
        if output.file_bytes is not None and output.file_ext:
            ref = store.save(
                content=output.file_bytes,
                kind=self._media_kind.DOCUMENT,
                source="mineru_parse",
                metadata={"original_filename": request.filename},
                ext=output.file_ext,
            )
            return ParseResult(
                text="",
                engine_used=ENGINE_MINERU,
                tier_used=target_tier,
                quality_score=1.0,
                duration_ms=int((time.monotonic() - started) * 1000),
                warnings=warnings,
                media_url=ref.api_url,
            )
        assets: Dict[str, str] = {}
        for name, data in output.images.items():
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else None
            ref = store.save(
                content=data,
                kind=self._media_kind.IMAGE,
                source="mineru_parse",
                metadata={"archive_name": name},
                ext=ext,
            )
            assets[name] = ref.api_url
        text = output.markdown
        if request.output_format == OUTPUT_STRUCTURED and output.structured is not None:
            text = json.dumps(output.structured, ensure_ascii=False)
        return ParseResult(
            text=text,
            engine_used=ENGINE_MINERU,
            structured=output.structured,
            tier_used=target_tier,
            quality_score=1.0,
            duration_ms=int((time.monotonic() - started) * 1000),
            warnings=warnings,
            assets=assets,
        )

    async def health(self) -> EngineHealth:
        info = await self._client.probe()
        return EngineHealth(
            available=bool(info.get("reachable")),
            detail=str(info.get("reason") or info.get("serverAuthMode") or ""),
            server_tiers=info.get("serverTiers"),
            server_version=info.get("serverVersion"),
        )
```

`backend/application/document_parse.py`：

```python
"""文档解析编排：路由、熔断、缓存。仅依赖领域契约与注入的引擎/缓存。"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, Protocol

from backend.domain.document_parse import (
    ENGINE_AUTO,
    ENGINE_CHOICES,
    ENGINE_LOCAL,
    ENGINE_MINERU,
    MineruSettings,
    ParseEngine,
    ParseRequest,
    ParseResult,
)

logger = logging.getLogger(__name__)


class ParseCache(Protocol):
    def get(self, content_hash: str, engine: str) -> Optional[ParseResult]: ...

    def put(self, content_hash: str, engine: str, result: ParseResult) -> None: ...


class CircuitBreaker:
    """MinerU 连续失败熔断（冷却期内不再尝试）。"""

    def __init__(
        self,
        threshold: int = 3,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: Optional[float] = None

    def closed(self) -> bool:
        if self._opened_at is None:
            return True
        if self._clock() - self._opened_at >= self._cooldown:
            self._opened_at = None
            self._failures = 0
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


class DocumentParseService:
    def __init__(
        self,
        *,
        local: ParseEngine,
        mineru_factory: Callable[[MineruSettings], ParseEngine],
        cache: ParseCache,
        settings_loader: Callable[[], MineruSettings],
        breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self._local = local
        self._mineru_factory = mineru_factory
        self._cache = cache
        self._load_settings = settings_loader
        self._breaker = breaker or CircuitBreaker()
        self._mineru_engine: Optional[ParseEngine] = None
        self._mineru_signature: Optional[tuple] = None

    async def parse(self, request: ParseRequest) -> ParseResult:
        settings = self._load_settings()
        hint = (
            request.engine_hint if request.engine_hint in ENGINE_CHOICES else ENGINE_AUTO
        )

        if hint == ENGINE_MINERU:
            if self._block_reason(settings, request, None, hint) is None:
                done = await self._try_mineru(settings, request)
                if done is not None:
                    return done
            local = await self._cached_parse(self._local, request, ENGINE_LOCAL)
            return local.with_warning("mineru_failed")

        local = await self._cached_parse(self._local, request, ENGINE_LOCAL)
        if self._block_reason(settings, request, local.quality_score, hint) is not None:
            return local
        done = await self._try_mineru(settings, request)
        if done is not None:
            return done
        return local.with_warning("mineru_failed")

    # ── 内部 ────────────────────────────────────────────────────
    def _block_reason(
        self,
        settings: MineruSettings,
        request: ParseRequest,
        local_score: Optional[float],
        hint: str,
    ) -> Optional[str]:
        if hint == ENGINE_LOCAL:
            return "local_hint"
        if request.extension != "pdf":
            return "non_pdf"
        if not settings.enabled:
            return "disabled"
        if not settings.configured:
            return "not_configured"
        if len(request.content_bytes) > settings.max_upload_mb * 1024 * 1024:
            return "too_large"
        if not self._breaker.closed():
            return "circuit_open"
        if local_score is not None and local_score >= settings.min_quality_threshold:
            return "quality_ok"
        return None

    async def _cached_parse(
        self, engine: ParseEngine, request: ParseRequest, engine_name: str
    ) -> ParseResult:
        key = request.content_hash()
        cached = self._cache.get(key, engine_name)
        if cached is not None:
            return cached
        result = await engine.parse(request)
        self._cache.put(key, engine_name, result)
        return result

    def _engine(self, settings: MineruSettings) -> ParseEngine:
        signature = (
            settings.base_url,
            settings.api_key,
            settings.default_tier,
            settings.timeout_seconds,
        )
        if self._mineru_engine is None or self._mineru_signature != signature:
            self._mineru_engine = self._mineru_factory(settings)
            self._mineru_signature = signature
        return self._mineru_engine

    async def _try_mineru(
        self, settings: MineruSettings, request: ParseRequest
    ) -> Optional[ParseResult]:
        key = request.content_hash()
        cached = self._cache.get(key, ENGINE_MINERU)
        if cached is not None:
            return cached
        try:
            result = await self._engine(settings).parse(request)
        except Exception as exc:  # noqa: BLE001 — 升级失败必须回退本地
            self._breaker.record_failure()
            logger.warning(
                "MinerU 解析失败，回退本地: %s: %s", type(exc).__name__, exc
            )
            return None
        self._breaker.record_success()
        self._cache.put(key, ENGINE_MINERU, result)
        return result
```

- [x] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_service.py -q`
Expected: 8 passed

- [x] **Step 5: ruff + commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/application/document_parse.py backend/adapters/out/document_parse/mineru_engine.py backend/tests/unit/test_document_parse_service.py
git add backend/application/document_parse.py backend/adapters/out/document_parse/mineru_engine.py backend/tests/unit/test_document_parse_service.py
git commit -m "feat(document-parse): 编排服务（质量路由/熔断/缓存）与 MinerU 引擎适配"
```

---

### Task 7: 后台队列 + 装配工厂

**Files:**
- Create: `backend/services/document_parse/queue.py`
- Create: `backend/services/document_parse/factory.py`
- Test: `backend/tests/unit/test_document_parse_queue.py`

**Interfaces:**
- Produces: `MineruBackgroundQueue(service)`：`submit(*, content, filename, tier=None, page_range=None) -> str`（task_key = `sha256:tier`，重复提交同一 key 返回原 key 且不重复入队）、`get_status(task_key) -> str`（`pending|running|completed|failed|unknown`）。
- Produces: `build_document_parse_service() -> DocumentParseService`、`get_document_parse_service()`、`reset_document_parse_service()`、`get_mineru_queue()`、`reset_mineru_queue()`。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_document_parse_queue.py
from __future__ import annotations

import asyncio

from backend.domain.document_parse import ParseResult
from backend.services.document_parse.queue import MineruBackgroundQueue


class FakeService:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def parse(self, request):
        self.requests.append(request)
        return self.result


def test_queue_dedupes_and_completes() -> None:
    async def scenario() -> None:
        service = FakeService(ParseResult(text="m", engine_used="mineru"))
        queue = MineruBackgroundQueue(service)
        key = queue.submit(content=b"same", filename="a.pdf")
        assert queue.submit(content=b"same", filename="a.pdf") == key
        await asyncio.sleep(0.05)
        assert queue.get_status(key) == "completed"
        assert len(service.requests) == 1

    asyncio.run(scenario())


def test_queue_marks_failed_when_fallback() -> None:
    async def scenario() -> None:
        service = FakeService(
            ParseResult(text="l", engine_used="local", warnings=["mineru_failed"])
        )
        queue = MineruBackgroundQueue(service)
        key = queue.submit(content=b"x", filename="a.pdf")
        await asyncio.sleep(0.05)
        assert queue.get_status(key) == "failed"

    asyncio.run(scenario())
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_queue.py -q`
Expected: ImportError

- [x] **Step 3: 写实现**

`backend/services/document_parse/queue.py`：

```python
"""MinerU 后台解析队列：单 worker 串行执行，按内容哈希去重。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Dict, Optional

from backend.application.document_parse import DocumentParseService
from backend.domain.document_parse import ENGINE_MINERU, ParseRequest

logger = logging.getLogger(__name__)


class MineruBackgroundQueue:
    def __init__(self, service: DocumentParseService) -> None:
        self._service = service
        self._queue: "asyncio.Queue[Optional[dict]]" = asyncio.Queue()
        self._worker: Optional[asyncio.Task] = None
        self._jobs: Dict[str, dict] = {}
        self._status: Dict[str, str] = {}

    def submit(
        self,
        *,
        content: bytes,
        filename: str,
        tier: Optional[str] = None,
        page_range: Optional[str] = None,
    ) -> str:
        content_hash = hashlib.sha256(content).hexdigest()
        task_key = content_hash + ":" + (tier or "auto")
        if task_key in self._jobs:
            return task_key
        job = {
            "task_key": task_key,
            "content": content,
            "filename": filename,
            "tier": tier,
            "page_range": page_range,
        }
        self._jobs[task_key] = job
        self._status[task_key] = "pending"
        self._ensure_worker()
        self._queue.put_nowait(job)
        return task_key

    def get_status(self, task_key: str) -> str:
        return self._status.get(task_key, "unknown")

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run_worker())

    async def _run_worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                key = job["task_key"]
                self._status[key] = "running"
                result = await self._service.parse(
                    ParseRequest(
                        filename=job["filename"],
                        content_bytes=job["content"],
                        engine_hint=ENGINE_MINERU,
                        tier=job["tier"],
                        page_range=job["page_range"],
                    )
                )
                self._status[key] = (
                    "completed" if result.engine_used == ENGINE_MINERU else "failed"
                )
            except Exception:  # noqa: BLE001 — 后台任务失败不得拖垮 worker
                logger.warning("MinerU 后台解析任务失败", exc_info=True)
                if job:
                    self._status[job["task_key"]] = "failed"
            finally:
                self._queue.task_done()
```

`backend/services/document_parse/factory.py`：

```python
"""文档解析装配：把适配器/缓存/配置接进编排服务。"""

from __future__ import annotations

from typing import Optional

from backend.adapters.out.document_parse.local_engine import LocalEngine
from backend.adapters.out.document_parse.mineru_client import MineruClient
from backend.adapters.out.document_parse.mineru_engine import MineruParseEngine
from backend.application.document_parse import DocumentParseService
from backend.domain.document_parse import MineruSettings

from .cache import SqliteParseCache
from .config import load_mineru_settings
from .queue import MineruBackgroundQueue


def _build_mineru_engine(settings: MineruSettings) -> MineruParseEngine:
    client = MineruClient(
        settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
    )
    return MineruParseEngine(client, tier=settings.default_tier)


def build_document_parse_service() -> DocumentParseService:
    return DocumentParseService(
        local=LocalEngine(),
        mineru_factory=_build_mineru_engine,
        cache=SqliteParseCache(),
        settings_loader=load_mineru_settings,
    )


_service: Optional[DocumentParseService] = None
_queue: Optional[MineruBackgroundQueue] = None


def get_document_parse_service() -> DocumentParseService:
    global _service
    if _service is None:
        _service = build_document_parse_service()
    return _service


def reset_document_parse_service() -> None:
    global _service
    _service = None


def get_mineru_queue() -> MineruBackgroundQueue:
    global _queue
    if _queue is None:
        _queue = MineruBackgroundQueue(get_document_parse_service())
    return _queue


def reset_mineru_queue() -> None:
    global _queue
    _queue = None
```

- [x] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_document_parse_queue.py -q`
Expected: 2 passed

- [x] **Step 5: ruff + commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/services/document_parse backend/tests/unit/test_document_parse_queue.py
git add backend/services/document_parse/queue.py backend/services/document_parse/factory.py backend/tests/unit/test_document_parse_queue.py
git commit -m "feat(document-parse): 后台队列与装配工厂"
```

---

### Task 8: `parse_document` 工具 + bundle 注册 + 黄金快照

**Files:**
- Create: `backend/tools/parse_document_tool.py`
- Modify: `backend/tools/__init__.py`（`_LAZY_TOOL_EXPORTS` + `__all__`）
- Modify: `backend/tools/tool_bundles.py`（`_install_document_parse` + `BUNDLES`）
- Modify: `backend/tests/unit/test_tool_bundles_parity.py`（`_EXPECTED_ONLINE` 122→123；`_EXPECTED_BUNDLE_NAMES`）
- Modify: `backend/tests/unit/test_risk.py`（若含内置工具风险验收表）
- Modify: `architecture-baseline.json`（实测）
- Test: `backend/tests/unit/test_parse_document_tool.py`

**Interfaces:**
- Consumes: Task 7 `get_document_parse_service()`；`MediaStore`；`current_tool_context`；`backend.tools.base._is_safe_path`。
- Produces: 工具名 `parse_document`，`requires_tool_context=True`，`risk=RiskClass.EXTERNAL`，`is_blocking=True`；`execute(path=None, media_id=None, engine="auto", output_format="markdown", pages=None, tier=None)`；`ToolResult.content` = 文本（docx/html 时为产物说明），`ToolResult.output` = `{engine_used,tier_used,quality_score,cached,duration_ms,warnings,media_url,assets}`。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_parse_document_tool.py
from __future__ import annotations

import asyncio

from backend.domain.document_parse import ParseRequest, ParseResult
from backend.tools.parse_document_tool import ParseDocumentTool, _run_async


def test_schema_contract() -> None:
    schema = ParseDocumentTool().get_schema()
    assert schema["name"] == "parse_document"
    assert "intranet" in schema["description"].lower()
    props = schema["parameters"]["properties"]
    assert props["engine"]["enum"] == ["auto", "local", "mineru"]
    assert props["output_format"]["enum"] == ["markdown", "structured", "docx", "html"]


def test_run_async_bridge_from_sync_context() -> None:
    async def add(a, b):
        return a + b

    assert _run_async(add(1, 2)) == 3


def test_execute_requires_source() -> None:
    result = ParseDocumentTool().execute()
    assert result.success is False
    assert result.error == "path_or_media_id_required"


def test_execute_uses_service(monkeypatch) -> None:
    class FakeService:
        async def parse(self, request: ParseRequest) -> ParseResult:
            return ParseResult(text="parsed", engine_used="local", duration_ms=3)

    import backend.tools.parse_document_tool as mod

    monkeypatch.setattr(mod, "get_document_parse_service", lambda: FakeService())
    monkeypatch.setattr(
        mod, "read_source_bytes", lambda path, media_id: ("a.pdf", b"%PDF")
    )
    result = ParseDocumentTool().execute(media_id="m1")
    assert result.success is True
    assert result.content == "parsed"
    assert result.output["engine_used"] == "local"
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_parse_document_tool.py -q`
Expected: ImportError

- [x] **Step 3: 写实现**

`backend/tools/parse_document_tool.py`：

```python
"""parse_document 工具：本地/内网 MinerU 可插拔解析（EXTERNAL）。

engine=auto 在本地文本质量低且 MinerU 已配置时，会把文档内容上传到内网
MinerU 服务；engine=local 保证文档绝不离机。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

from backend.domain.document_parse import ParseRequest, ParseResult
from backend.domain.risk import RiskClass
from backend.services.document_parse.factory import get_document_parse_service
from backend.tools.base import BaseTool, ToolResult, ToolSchema, _is_safe_path
from backend.tools.context import current_tool_context

_MAX_SOURCE_BYTES = 200 * 1024 * 1024


def _run_async(coro: Any) -> Any:
    """同步工具边界执行协程（有运行中事件循环时换新线程）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: List[Any] = []
    errors: List[BaseException] = []

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            box.append(loop.run_until_complete(coro))
        except BaseException as exc:  # noqa: BLE001 — 原样回抛给调用方
            errors.append(exc)
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, name="parse-document-bridge")
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return box[0]


def read_source_bytes(path: Optional[str], media_id: Optional[str]) -> Tuple[str, bytes]:
    """读取解析源：优先 media_id（聊天附件），其次已校验的工作区路径。"""
    if media_id:
        from backend.services.multimodal.media_store import MediaStore

        loaded = MediaStore().load(media_id)
        if loaded is None:
            raise FileNotFoundError("media_not_found")
        ref, content = loaded
        name = str(ref.metadata.get("original_filename") or (media_id + ".bin"))
        return name, content
    assert path is not None
    target = Path(path)
    if target.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError("source_too_large")
    return target.name, target.read_bytes()


class ParseDocumentTool(BaseTool):
    requires_tool_context = True
    risk = RiskClass.EXTERNAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="parse_document",
            description=(
                "Parse a PDF/image/office document into text or structured output. "
                "The local engine runs on this machine; engine=mineru (or engine=auto "
                "when local text quality is low) uploads the document to the intranet "
                "MinerU server configured in Settings. Use engine=local to keep the "
                "document on-device."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Document path inside the active workspace.",
                    },
                    "media_id": {
                        "type": "string",
                        "description": "Chat media id (alternative to path).",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["auto", "local", "mineru"],
                        "description": "Parsing engine; defaults to auto.",
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "structured", "docx", "html"],
                        "description": "Desired output; defaults to markdown.",
                    },
                    "pages": {
                        "type": "string",
                        "description": "PDF page range, e.g. '1-3' (MinerU only).",
                    },
                    "tier": {
                        "type": "string",
                        "enum": ["flash", "basic", "standard", "advanced"],
                        "description": "MinerU quality tier; defaults to the configured tier.",
                    },
                },
                "required": [],
            },
        )

    def execute(
        self,
        path: Optional[str] = None,
        media_id: Optional[str] = None,
        engine: Optional[str] = None,
        output_format: Optional[str] = None,
        pages: Optional[str] = None,
        tier: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not path and not media_id:
            return ToolResult(success=False, error="path_or_media_id_required")
        resolved_path = path
        if path and not media_id:
            ctx = current_tool_context()
            if ctx is None:
                return ToolResult(success=False, error="missing_tool_context")
            target = self._resolve_workspace_path(ctx, path)
            if target is None:
                return ToolResult(success=False, error="path_outside_workspace")
            if not target.is_file():
                return ToolResult(success=False, error="file_not_found")
            resolved_path = str(target)
        try:
            filename, content = read_source_bytes(resolved_path, media_id)
            request = ParseRequest(
                filename=filename,
                content_bytes=content,
                engine_hint=engine or "auto",
                output_format=output_format or "markdown",
                page_range=pages,
                tier=tier,
                source_path=resolved_path,
                media_id=media_id,
            )
            result: ParseResult = _run_async(
                get_document_parse_service().parse(request)
            )
        except Exception as exc:  # noqa: BLE001 — 工具边界统一折叠
            return ToolResult(success=False, error="parse_failed: " + str(exc))
        content_text = result.text
        if not content_text and result.media_url:
            content_text = "已生成文件：" + result.media_url
        return ToolResult(
            success=True,
            content=content_text,
            output={
                "engine_used": result.engine_used,
                "tier_used": result.tier_used,
                "quality_score": result.quality_score,
                "cached": result.cached,
                "duration_ms": result.duration_ms,
                "warnings": list(result.warnings),
                "media_url": result.media_url,
                "assets": dict(result.assets),
            },
        )

    def _resolve_workspace_path(self, ctx: Any, raw_path: str) -> Optional[Path]:
        """与 OcrImageTool 同款工作区解析（fail-closed）。"""
        if not raw_path:
            return None
        root: Optional[Path] = None
        policy_root = getattr(self._policy, "workspace_root", None)
        if policy_root:
            root = Path(policy_root).resolve()
        if root is None:
            try:
                from backend.data.database import get_database
                from backend.office.session_workspace import get_active_workspace

                conn = get_database().get_connection()
                binding = get_active_workspace(
                    conn,
                    ctx.session_id,
                    expected_generation=ctx.binding_generation,
                )
                if binding is not None:
                    root = Path(binding.workspace_path).resolve()
            except Exception:  # noqa: BLE001 — 无绑定按不可用处理
                root = None
        if root is None:
            return None
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not _is_safe_path(str(candidate), str(root)):
            return None
        return candidate
```

> 执行时用 `grep -n "def get_active_workspace" -A 15 backend/office/session_workspace.py` 核对 `get_active_workspace` 的实参名（若参数名不是 `expected_generation`，按实际签名调整；该调用是 OcrImageTool 的既有写法，直接照抄可避免偏差）。

`backend/tools/__init__.py`：`_LAZY_TOOL_EXPORTS` 加 `"ParseDocumentTool": ".parse_document_tool"`；`__all__` 按现有字母序插入 `"ParseDocumentTool"`（与 `OcrImageTool` 相邻）。

`backend/tools/tool_bundles.py`：

```python
def _install_document_parse(ctx: Any) -> None:
    from backend.tools.parse_document_tool import ParseDocumentTool

    ctx.registry.register(ParseDocumentTool(policy=ctx.policy))
```

`BUNDLES` 中在 `ToolBundle("multimodal", _install_multimodal),` 之后插入：

```python
    ToolBundle("document_parse", _install_document_parse),
```

`backend/tests/unit/test_tool_bundles_parity.py`：
- `_EXPECTED_ONLINE`：在 `"ocr_image",` 与 `"read_sage_config",` 之间插入 `"parse_document",`；同步把该列表长度断言 122 改为 123（若断言写作 `len(...) == 122`）。
- `_EXPECTED_BUNDLE_NAMES`：在 `"multimodal",` 之后插入 `"document_parse",`。
- `_EXPECTED_SCHEMA_NAMES` **不变**：`get_schemas_for_llm()` 在无活动 `ToolExecutionContext` 时过滤 `requires_tool_context=True` 的工具（`ocr_image` 同样缺席），`parse_document` 与之同构。

- [x] **Step 4: 跑工具/快照/风险测试**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_parse_document_tool.py backend/tests/unit/test_tool_bundles_parity.py backend/tests/unit/test_risk.py -q
```

若 `test_risk.py` 存在内置工具风险验收表：把 `parse_document: RiskClass.EXTERNAL` 加入。

- [x] **Step 5: 棘轮回填 + ruff + commit**

```bash
node scripts/architecture-check.mjs   # 按提示回填 architecture-baseline.json
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/tools
git add backend/tools/parse_document_tool.py backend/tools/__init__.py backend/tools/tool_bundles.py backend/tests/unit/test_tool_bundles_parity.py backend/tests/unit/test_parse_document_tool.py architecture-baseline.json
git commit -m "feat(document-parse): parse_document 工具与 document_parse bundle"
```

---

### Task 9: 聊天附件双阶段 + `/api/v1/mineru/status`

**Files:**
- Modify: `backend/api/chat_attachment_routes.py`（上传后 fire-and-forget；读文本缓存优先）
- Create: `backend/api/mineru_routes.py`
- Modify: `backend/main.py`（导入 + `include_router`）
- Modify: `architecture-baseline.json`（`backend/main.py` 实测）
- Test: `backend/tests/unit/test_mineru_routes.py`、`backend/tests/unit/test_chat_attachment_dual_phase.py`

**Interfaces:**
- Consumes: Task 7 `get_mineru_queue()`；Task 3 `load_mineru_settings()`；Task 5 `SqliteParseCache`；Task 2 `MineruClient.probe()`。
- Produces: `GET /api/v1/mineru/status` → `{configured, enabled, hasApiKey, reachable, serverAuthMode, serverTiers, serverVersion, reason}`（**绝不含 key 明文**）。
- Produces: `GET /api/v1/chat/attachments/{media_id}/text` 响应新增 `source`（`local|mineru`）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_mineru_routes.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import mineru_routes
from backend.domain.document_parse import MineruSettings


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(mineru_routes.router, prefix="/api/v1")
    return app


def test_status_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(mineru_routes, "load_mineru_settings", lambda: MineruSettings())
    body = TestClient(_app()).get("/api/v1/mineru/status").json()
    assert body["configured"] is False
    assert body["hasApiKey"] is False
    assert body["reason"] == "not_configured"
    assert "apiKey" not in body


def test_status_probes_without_leaking_key(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def probe(self):
            return {
                "reachable": True,
                "serverAuthMode": "anonymous",
                "serverTiers": ["flash", "standard"],
                "serverVersion": "4.1.7",
                "reason": "",
                "accessLevel": "anonymous",
            }

    monkeypatch.setattr(
        mineru_routes,
        "load_mineru_settings",
        lambda: MineruSettings(
            enabled=True, base_url="http://m:8000", api_key="sk-synthetic"
        ),
    )
    monkeypatch.setattr(mineru_routes, "MineruClient", FakeClient)
    response = TestClient(_app()).get("/api/v1/mineru/status")
    assert "sk-synthetic" not in response.text
    body = response.json()
    assert body["hasApiKey"] is True
    assert body["reachable"] is True
    assert body["serverTiers"] == ["flash", "standard"]
```

```python
# backend/tests/unit/test_chat_attachment_dual_phase.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import chat_attachment_routes


def test_pdf_upload_enqueues_when_enabled(monkeypatch, tmp_path) -> None:
    submitted = []

    class FakeQueue:
        def submit(self, **kwargs):
            submitted.append(kwargs)
            return "k"

    class FakeSettings:
        enabled = True
        configured = True
        use_in_chat_attachment = True
        max_upload_mb = 25
        base_url = "http://m:8000"

    monkeypatch.setattr(chat_attachment_routes, "MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(chat_attachment_routes, "get_mineru_queue", lambda: FakeQueue())
    monkeypatch.setattr(
        chat_attachment_routes, "load_mineru_settings", lambda: FakeSettings()
    )
    app = FastAPI()
    app.include_router(chat_attachment_routes.router, prefix="/api/v1")
    pdf = b"%PDF-1.4\n%%EOF"
    response = TestClient(app).post(
        "/api/v1/chat/attachments",
        files={"file": ("a.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 200
    assert submitted and submitted[0]["filename"] == "a.pdf"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_mineru_routes.py backend/tests/unit/test_chat_attachment_dual_phase.py -q`
Expected: ImportError / 404

- [ ] **Step 3: 写实现**

`backend/api/mineru_routes.py`：

```python
"""MinerU 服务状态路由（只暴露 hasApiKey，绝不回显密钥）。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.adapters.out.document_parse.mineru_client import MineruClient
from backend.services.document_parse.config import load_mineru_settings

router = APIRouter(prefix="/mineru", tags=["mineru"])


@router.get("/status")
async def mineru_status() -> dict:
    settings = load_mineru_settings()
    body = {
        "configured": settings.configured,
        "enabled": settings.enabled,
        "hasApiKey": bool(settings.api_key),
        "reachable": False,
        "serverAuthMode": "unknown",
        "serverTiers": None,
        "serverVersion": None,
        "reason": "",
    }
    if not settings.configured:
        body["reason"] = "not_configured"
        return body
    info = await MineruClient(
        settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=min(settings.timeout_seconds, 10.0),
    ).probe()
    body.update(
        reachable=bool(info.get("reachable")),
        serverAuthMode=info.get("serverAuthMode", "unknown"),
        serverTiers=info.get("serverTiers"),
        serverVersion=info.get("serverVersion"),
        reason=info.get("reason", ""),
    )
    return body
```

`backend/main.py`：在 `from backend.api.ocr_routes import router as ocr_router` 同区加 `from backend.api.mineru_routes import router as mineru_router`；在 `app.include_router(ocr_router, prefix="/api/v1")` 之后加 `app.include_router(mineru_router, prefix="/api/v1")`。

`backend/api/chat_attachment_routes.py`：
- 顶部以模块级名导入双阶段依赖（便于测试 monkeypatch）：

```python
from backend.services.document_parse.config import load_mineru_settings
from backend.services.document_parse.factory import get_mineru_queue
```

- 在 `upload_chat_attachment` 中、PDF 附件处理完成并返回响应**之前**调用：

```python
    if ext == "pdf":
        _schedule_mineru_enrichment(content, file.filename or "attachment.pdf")
```

> 注意：调用点必须位于 `content` 已读取、且本地文本已经算好（或不再需要）之后；执行时按现有函数体结构定位（用 `grep -n "async def upload_chat_attachment" -A 120 backend/api/chat_attachment_routes.py` 查看真实变量名，可能是 `file_content`）。

- 文件内新增：

```python
def _schedule_mineru_enrichment(content: bytes, filename: str) -> None:
    """阶段 2：本地文本已返回后，后台提交 MinerU（失败静默）。"""
    try:
        settings = load_mineru_settings()
        if not (
            settings.enabled
            and settings.configured
            and settings.use_in_chat_attachment
        ):
            return
        get_mineru_queue().submit(content=content, filename=filename)
    except Exception:  # noqa: BLE001 — 双阶段补充不得影响上传响应
        logger.warning("MinerU 后台解析提交失败", exc_info=True)
```

- `get_chat_attachment_text`（text 路由函数）在拿到 `content`、返回本地文本之前，插入缓存优先命中：

```python
    try:
        import hashlib

        from backend.services.document_parse.cache import SqliteParseCache

        cached = SqliteParseCache().get(hashlib.sha256(content).hexdigest(), "mineru")
    except Exception:  # noqa: BLE001 — 缓存不可用回退本地
        cached = None
    if cached is not None and cached.text:
        return {"media_id": media_id, "text": cached.text, "source": "mineru"}
```

- 既有本地返回改为：

```python
    return {"media_id": media_id, "text": text, "source": "local"}
```

> 若有既有测试断言该响应仅含 `{"media_id","text"}`，按新契约补充 `source` 字段断言（属于预期变更）。

- [ ] **Step 4: 跑测试确认通过（含附件回归）**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_mineru_routes.py backend/tests/unit/test_chat_attachment_dual_phase.py backend/tests/unit/test_r39_pdf_docx_extract.py backend/tests/unit/test_attachment_pdf.py backend/tests/unit/test_quality_and_local_engine.py -q
node scripts/architecture-check.mjs
```

- [ ] **Step 5: commit**

```bash
git add backend/api/mineru_routes.py backend/api/chat_attachment_routes.py backend/main.py backend/tests/unit/test_mineru_routes.py backend/tests/unit/test_chat_attachment_dual_phase.py architecture-baseline.json
git commit -m "feat(document-parse): 聊天附件双阶段与 MinerU 状态接口"
```

---

### Task 10: 前端设置卡片 + 状态 API + 注册表/i18n

**Files:**
- Create: `src/shared/api/mineruApi.ts`
- Create: `src/pages/settings/MineruServiceCard.tsx`
- Create: `src/pages/settings/__tests__/MineruServiceCard.test.tsx`
- Modify: `src/pages/settings/ModelsTab.tsx`（`<LocalOcrCard />` 之后）
- Modify: `src/entities/setting/settingsRegistry.ts`（`ocr_config` 之后）
- Modify: `src/shared/api/settingsClient.ts`（`PreferenceKey` 加 `'mineru_service'`）
- Modify: `src/shared/lib/i18n/locales/{zh,en}/settingsUi.ts`

**Interfaces:**
- Produces: `mineruApi.status(): Promise<MineruStatus>`；`MineruStatus` 字段与后端一致。
- Produces: preferences `mineru_service` JSON：`{enabled,baseUrl,apiKey,defaultTier,timeoutSeconds,maxUploadMb,useInChatAttachment,minQualityThreshold}`。

- [ ] **Step 1: 写失败测试**

```tsx
// src/pages/settings/__tests__/MineruServiceCard.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { MineruServiceCard } from '../MineruServiceCard';

const { mocks } = vi.hoisted(() => ({
  mocks: { status: vi.fn(), getPreference: vi.fn(), setPreference: vi.fn() },
}));

vi.mock('../../../shared/api/mineruApi', () => ({
  mineruApi: { status: mocks.status },
}));
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: mocks.getPreference,
    setPreference: mocks.setPreference,
  },
}));

function renderCard() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MineruServiceCard />
    </I18nProvider>,
  );
}

describe('MineruServiceCard', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows server status and warns when auth required without key', async () => {
    mocks.status.mockResolvedValue({
      configured: true,
      enabled: true,
      hasApiKey: false,
      reachable: true,
      serverAuthMode: 'required',
      serverTiers: ['flash', 'standard'],
      serverVersion: '4.1.7',
      reason: 'api_key_required_or_invalid',
    });
    mocks.getPreference.mockResolvedValue(
      JSON.stringify({ enabled: true, baseUrl: 'http://10.0.0.8:8000' }),
    );
    renderCard();
    expect(await screen.findByText(/需要 API Key/)).toBeTruthy();
    expect(screen.getByDisplayValue('http://10.0.0.8:8000')).toBeTruthy();
  });

  it('persists edited fields', async () => {
    mocks.status.mockResolvedValue({
      configured: false,
      enabled: false,
      hasApiKey: false,
      reachable: false,
      serverAuthMode: 'unknown',
      serverTiers: null,
      serverVersion: null,
      reason: 'not_configured',
    });
    mocks.getPreference.mockResolvedValue(null);
    mocks.setPreference.mockResolvedValue(undefined);
    renderCard();
    const input = await screen.findByPlaceholderText('http://10.0.0.8:8000');
    fireEvent.change(input, { target: { value: 'http://10.1.1.1:8000' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    const [, raw] = mocks.setPreference.mock.calls[0];
    expect(JSON.parse(raw).baseUrl).toBe('http://10.1.1.1:8000');
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
npx vitest run src/pages/settings/__tests__/MineruServiceCard.test.tsx
```
Expected: 找不到 `MineruServiceCard`

- [ ] **Step 3: 写实现**

`src/shared/api/mineruApi.ts`：

```ts
/**
 * MinerU 服务 API（后端 backend/api/mineru_routes.py → /api/v1/mineru/*）
 * 状态接口只返回 hasApiKey 布尔值，密钥不会出现在响应中。
 */

import { backendRequest } from './backendRequest';

export interface MineruStatus {
  configured: boolean;
  enabled: boolean;
  hasApiKey: boolean;
  reachable: boolean;
  serverAuthMode: 'bearer' | 'anonymous' | 'required' | 'unknown';
  serverTiers: string[] | null;
  serverVersion: string | null;
  reason: string;
}

export const mineruApi = {
  status(): Promise<MineruStatus> {
    return backendRequest<MineruStatus>({
      method: 'GET',
      path: '/api/v1/mineru/status',
    });
  },
};
```

> 执行时用 `ls src/shared/api/backendRequest*` + 打开文件核对导出名与签名（若仓库用的是 `apiRequest`/`authFetch` 等，按其签名改写调用；不要新增未知依赖）。

`src/pages/settings/MineruServiceCard.tsx`：

```tsx
/**
 * 设置页「MinerU 文档解析」卡片：服务端状态 + 连接配置。
 * 数据源：GET /api/v1/mineru/status、preferences KV `mineru_service`。
 */

import { useEffect, useState } from 'react';

import { mineruApi, type MineruStatus } from '../../shared/api/mineruApi';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n } from '../../shared/lib/i18n';

export interface MineruServiceConfig {
  enabled: boolean;
  baseUrl: string;
  apiKey: string;
  defaultTier: 'flash' | 'basic' | 'standard' | 'advanced';
  timeoutSeconds: number;
  maxUploadMb: number;
  useInChatAttachment: boolean;
  minQualityThreshold: number;
}

const DEFAULT_CONFIG: MineruServiceConfig = {
  enabled: false,
  baseUrl: '',
  apiKey: '',
  defaultTier: 'standard',
  timeoutSeconds: 300,
  maxUploadMb: 25,
  useInChatAttachment: true,
  minQualityThreshold: 0.85,
};

function parseConfig(raw: string | null): MineruServiceConfig {
  if (!raw) return DEFAULT_CONFIG;
  try {
    const parsed = JSON.parse(raw) as Partial<MineruServiceConfig>;
    return { ...DEFAULT_CONFIG, ...parsed };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function MineruServiceCard() {
  const { t } = useI18n();
  const [status, setStatus] = useState<MineruStatus | null>(null);
  const [config, setConfig] = useState<MineruServiceConfig>(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);

  const refreshStatus = () => mineruApi.status().catch(() => null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      refreshStatus(),
      settingsClient.getPreference('mineru_service').catch(() => null),
    ]).then(([nextStatus, raw]) => {
      if (cancelled) return;
      setStatus(nextStatus);
      setConfig(parseConfig(raw));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await settingsClient.setPreference(
        'mineru_service',
        JSON.stringify(config),
      );
      setStatus(await refreshStatus());
    } finally {
      setSaving(false);
    }
  };

  const authMismatch =
    status?.reachable && status.serverAuthMode === 'required' && !config.apiKey;

  return (
    <div
      className="space-y-3 rounded border border-border p-3"
      data-testid="mineru-service-card"
    >
      <div className="text-sm font-semibold">{t('settings.mineru.title')}</div>
      <p className="text-xs text-muted">{t('settings.mineru.desc')}</p>

      {status && (
        <div className="text-xs" data-testid="mineru-status">
          {status.reachable
            ? t('settings.mineru.reachable').replace('{mode}', status.serverAuthMode)
            : t('settings.mineru.unreachable').replace(
                '{reason}',
                status.reason || 'unknown',
              )}
        </div>
      )}
      {authMismatch && (
        <div className="rounded bg-red-50 p-2 text-xs text-red-700" role="alert">
          {t('settings.mineru.auth_required')}
        </div>
      )}

      <label className="block text-xs">
        {t('settings.mineru.base_url')}
        <input
          className="mt-1 w-full rounded border border-border px-2 py-1"
          placeholder="http://10.0.0.8:8000"
          value={config.baseUrl}
          onChange={(e) => setConfig({ ...config, baseUrl: e.target.value })}
        />
      </label>
      <label className="block text-xs">
        {t('settings.mineru.api_key')}
        <input
          type="password"
          className="mt-1 w-full rounded border border-border px-2 py-1"
          placeholder={t('settings.mineru.api_key_placeholder')}
          value={config.apiKey}
          onChange={(e) => setConfig({ ...config, apiKey: e.target.value })}
        />
      </label>

      <div className="flex gap-3 text-xs">
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
          />
          {t('settings.mineru.enabled')}
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={config.useInChatAttachment}
            onChange={(e) =>
              setConfig({ ...config, useInChatAttachment: e.target.checked })
            }
          />
          {t('settings.mineru.chat_attachment')}
        </label>
      </div>

      <button
        type="button"
        className="rounded bg-accent px-3 py-1 text-xs text-white disabled:opacity-50"
        disabled={saving}
        onClick={save}
      >
        {t('settings.mineru.save')}
      </button>
    </div>
  );
}
```

`src/pages/settings/ModelsTab.tsx`：顶部 import `MineruServiceCard`；在 `<LocalOcrCard />` 之后加：

```tsx
      {/* MinerU：内网高保真文档解析（可选；本地质量低时升级） */}
      <MineruServiceCard />
```

`src/entities/setting/settingsRegistry.ts`：在 `ocr_config` 条目之后加：

```ts
  mineru_service: {
    key: 'mineru_service',
    label: 'MinerU 文档解析',
    description: '连接内网 MinerU 服务，本地解析质量不足时升级为高保真解析',
    scope: 'global',
    storage: 'preference',
    defaultValue: {
      enabled: false,
      baseUrl: '',
      apiKey: '',
      defaultTier: 'standard',
      timeoutSeconds: 300,
      maxUploadMb: 25,
      useInChatAttachment: true,
      minQualityThreshold: 0.85,
    },
    applyMode: 'next-request',
    visibility: 'advanced',
    riskLevel: 'low',
    constraints: { type: 'json' },
  },
```

`src/shared/api/settingsClient.ts`：`PreferenceKey` 联合类型在 `| 'ocr_config'` 之后加 `| 'mineru_service'`。

i18n `zh/settingsUi.ts` 追加（`en/settingsUi.ts` 同键英文）：

```ts
  'settings.mineru.title': 'MinerU 文档解析',
  'settings.mineru.desc':
    '内网 MinerU 服务；本地文本质量不足时自动升级（会把文档上传到该服务）',
  'settings.mineru.reachable': '服务可达（鉴权模式：{mode}）',
  'settings.mineru.unreachable': '服务不可达（{reason}）',
  'settings.mineru.auth_required': '服务端需要 API Key：请填写后保存',
  'settings.mineru.base_url': '服务地址',
  'settings.mineru.api_key': 'API Key（可选）',
  'settings.mineru.api_key_placeholder': '留空 = 服务端未开鉴权',
  'settings.mineru.enabled': '启用',
  'settings.mineru.chat_attachment': '聊天附件后台升级',
  'settings.mineru.save': '保存',
```

英文：

```ts
  'settings.mineru.title': 'MinerU document parsing',
  'settings.mineru.desc':
    'Intranet MinerU server; low-quality local text is upgraded (the document is uploaded to that server)',
  'settings.mineru.reachable': 'Server reachable (auth mode: {mode})',
  'settings.mineru.unreachable': 'Server unreachable ({reason})',
  'settings.mineru.auth_required': 'Server requires an API key: enter one and save',
  'settings.mineru.base_url': 'Server URL',
  'settings.mineru.api_key': 'API key (optional)',
  'settings.mineru.api_key_placeholder': 'Leave empty when the server has auth disabled',
  'settings.mineru.enabled': 'Enabled',
  'settings.mineru.chat_attachment': 'Upgrade chat attachments in background',
  'settings.mineru.save': 'Save',
```

> 若设置页存在「偏好键完整性」校验测试（如 settingsRegistry 快照 / 搜索索引），按测试提示登记 `mineru_service`。

- [ ] **Step 4: 跑前端测试 + 类型检查**

```bash
npx vitest run src/pages/settings/__tests__/MineruServiceCard.test.tsx
npx tsc --noEmit -p tsconfig.json
```

- [ ] **Step 5: commit**

```bash
git add src/shared/api/mineruApi.ts src/pages/settings/MineruServiceCard.tsx src/pages/settings/__tests__/MineruServiceCard.test.tsx src/pages/settings/ModelsTab.tsx src/entities/setting/settingsRegistry.ts src/shared/api/settingsClient.ts src/shared/lib/i18n/locales
git commit -m "feat(document-parse): MinerU 设置卡片与状态 API"
```

---

### Task 11: 技术文档 + 全量门禁 + spec 状态回写

**Files:**
- Create: `docs/technical/160-mineru-document-parse.md`
- Modify: `docs/technical/README.md`（目录表追加 160）
- Modify: `docs/plans/2026-11-23_mineru-document-parse-subsystem.md`（勾选已完成的 M1–M7）

- [ ] **Step 1: 写技术文档**

`docs/technical/160-mineru-document-parse.md` 必含章节：

1. 架构分层图（domain/application/adapters/services 职责与依赖方向）
2. `ParseEngine` 契约与 `DocumentParseService` 路由表（hint/扩展名/质量阈值/熔断/大小上限）
3. MinerU 4 步协议时序、重试规则（创建不重试、GET 类按 3 次退避）、错误码映射（401/403/`invalid_api_key` → `MineruAuthError`；任务 failed/canceled → `MineruRemoteError`；超时 → cancel + `MineruTimeoutError`）
4. 质量打分公式（`1.0 - 0.35·text_per_page<120 - 0.30·blank_ratio>0.5 - 0.25·has_table - 0.20·has_formula`，clamp ≥0，默认阈值 0.85）
5. 缓存表 `document_parse_cache` 结构与失效口径（内容哈希 + 引擎为主键；无自动过期）
6. 熔断（3 连败开 60 s 半开）与队列语义（单 worker 串行、按 `sha256:tier` 去重）
7. `parse_document` 工具风险声明（EXTERNAL + 上传披露 + `engine=local` 保证不离机）
8. 聊天双阶段时序（本地先返回 → 后台 MinerU → 文本接口下次读到 `source=mineru`）
9. 配置项与 env 覆盖（`SAGE_MINERU_BASE_URL/API_KEY/TIER/TIMEOUT_SECONDS`）
10. `GET /api/v1/mineru/status` 响应字段表与「绝不含 key」
11. 故障排查：401/403、`feature_requires_api_key`、`api_key_required_or_invalid`；离线包未传 `--api-key` 即未开鉴权，此时 `apiKey` 可留空

`docs/technical/README.md` 目录表追加：

```markdown
| 160 | [MinerU 文档解析](./160-mineru-document-parse.md) | 可插拔解析引擎 / async API 客户端 / 质量路由 / 缓存 / 双阶段附件 |
```

- [ ] **Step 2: 全量后端门禁**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -q
node scripts/architecture-check.mjs
```

Expected: 全绿。若出现既有环境性失败（端口/git 中文/AsyncMock），先比对改动前的失败集合，确认集合一致再放行。

- [ ] **Step 3: 前端门禁**

```bash
npx tsc --noEmit -p tsconfig.json
npx vitest run src/pages/settings/__tests__
```

- [ ] **Step 4: spec 状态回写 + commit**

在 spec §5 的 M1–M7 条目上标记 `[x]`，然后：

```bash
git add docs/technical/160-mineru-document-parse.md docs/technical/README.md docs/plans/2026-11-23_mineru-document-parse-subsystem.md
git commit -m "docs(document-parse): 技术文档与轨道 A 状态回写"
```

---

## Self-Review

**1. Spec coverage**

| Spec 章节 | 覆盖任务 |
|---|---|
| §3.1 新文件（含两处补充文件） | T1–T7 |
| §3.2 修改文件（settings/secret_box/database/tools/bundles/chat/main） | T3/T5/T8/T9 |
| §3.3 前端三件套 + 注册/i18n | T10 |
| §4.2 契约 | T1 |
| §4.3 客户端约束/错误映射/ZIP 图片落盘 | T2/T6 |
| §4.4 质量公式 + 自动路由 | T4/T6 |
| §4.5 缓存 DDL | T5 |
| §4.6 后台队列 | T7 |
| §4.7 工具 | T8 |
| §4.8 配置与 SecretBox | T3 |
| §4.9 状态接口与卡片 | T9/T10 |
| §4.10 聊天双阶段 | T9 |
| §11 文档漂移清单 | T11 |
| §12 双分支同步 | 合并后另行执行（本轮不做） |

**2. Placeholder scan**：无 TBD/TODO；所有代码步骤给出可粘贴实现；所有测试含断言；三处「执行时核对」均为带明确命令与回退分支的验证步骤（`load_module` 签名、`get_active_workspace` 形参名、`backendRequest` 导出名）。

**3. Type consistency**：`ParseRequest/ParseResult/MineruSettings/ParseEngine` 在 T1 定义并在 T2–T9 同名引用；`MineruOutput` 字段在 T1 定义、T2 产出、T6 消费；`SqliteParseCache.get(hash, engine)` 在 T5 定义、T6/T9 调用；`get_document_parse_service()`/`get_mineru_queue()` 在 T7 定义、T8/T9 调用；`MineruParseEngine(client, tier=...)` 与工厂调用一致；`_run_async` 仅在 T8 定义与使用。

## 验收清单（spec §9）

- [ ] `parse_document` 出现在工具清单与 `document_parse` bundle，且 `requires_tool_context` 过滤后 schema 快照不变。
- [ ] 设置页可保存/清除 MinerU 地址与（可选）key；保存后 `GET /api/v1/mineru/status` 反映 `configured/hasApiKey/reachable`。
- [ ] key 明文不出现在任何接口响应、日志与缓存。
- [ ] 低质量 PDF 自动升级 MinerU；MinerU 宕机时聊天与工具均回退本地且不抛错。
- [ ] 未启用 MinerU 时行为与当前版本一致（本地提取路径不变）。
- [ ] 攻击面：上传 ZIP 成员数受控；跨源上传不携带 Authorization。
