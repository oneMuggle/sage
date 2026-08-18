# office_create 工具自动创建 Office 文档 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `office_create` LLM 工具，让 Sage 在对话中自动创建 Word/Excel/PPT 到任意路径（写工作区外经 M1 审批链确认）。

**Architecture:** 复用现有生成器（`generate_docx/generate_xlsx/generate_ppt`，各加可选 `output_dir` 参数）+ 新 `OfficeCreateTool`（`requires_tool_context=False`，直接提问即触发）+ `PermissionEnforcer` 注入 `path_boundary_validator`（与现有 `bash_validator` 对称）→ 把"写工作区外"从 allow 升级为 ask → 复用现有 `permission_request` → `ApprovalDialog` → `permissions_answer` 审批链。边界来源是**当前会话的 workspace 绑定**（`session_workspace` 表），非 `ToolPolicy.workspace_root`（后者在 legacy 链路恒为 None）。

**Tech Stack:** Python 3.11（main 分支），pydantic v2，python-docx / openpyxl / python-pptx（已有），pytest。`path_safety.py` / `permissions.py` 修改须保持 **Python 3.8 兼容语法**（可 cherry-pick 到 release/win7）。

## Global Constraints

- 生成器默认行为（**不传** `output_dir`）必须与现有 HTTP 端点行为完全一致（回归约束）。
- 文件名安全唯一入口 `validate_supported_filename`（拦分隔符 / `..` 穿越 / 错误扩展名）。
- 目标文件**已存在 → 拒绝**，不覆盖。
- `output_dir` resolve 后是已存在文件而非目录 → 拒绝。
- **FULL_ACCESS 模式跳过 path_boundary 校验**（用户已确认 full_access 放行）。
- 会话未绑定 workspace → 跳过边界检查（与 `write_file` 未绑定语义一致）。
- 测试运行：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest <path>`（项目强制 sage-backend 环境，见 CLAUDE.md）。
- 新工具 `requires_tool_context = False`、`risk = RiskClass.WRITE_LOCAL`。

---

### Task 1: `resolve_output_path` 路径安全 helper

**Files:**
- Modify: `backend/office/path_safety.py`（文件末尾 `__all__` 前加函数）
- Test: `backend/tests/unit/office/test_path_safety.py`

**Interfaces:**
- Consumes: `validate_supported_filename`（本文件已有）、`OfficeDocType`（`backend/office/models.py`）
- Produces: `resolve_output_path(output_dir: str, doc_type: OfficeDocType, filename: str) -> Path`——组合一个信任目标目录下的输出路径（不做 workspace 边界）；供 Task 2 的三个生成器调用。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/office/test_path_safety.py` 末尾追加：

```python
import pytest

from backend.office.models import OfficeDocType
from backend.office.path_safety import OfficePathError, resolve_output_path


def test_resolve_output_path_appends_canonical_extension(tmp_path):
    out = resolve_output_path(str(tmp_path), OfficeDocType.WORD, "天气")
    assert out.name == "天气.docx"
    assert out.parent == tmp_path.resolve()


def test_resolve_output_path_keeps_correct_extension(tmp_path):
    out = resolve_output_path(str(tmp_path), OfficeDocType.EXCEL, "data.xlsx")
    assert out.name == "data.xlsx"


def test_resolve_output_path_expands_home(monkeypatch, tmp_path):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    out = resolve_output_path("~/Desktop", OfficeDocType.PPT, "slides")
    assert out.parent == (home / "Desktop").resolve()
    assert out.name == "slides.pptx"


@pytest.mark.parametrize(
    "filename",
    ["../evil.docx", "a/b.docx", "a\\b.docx", "bad.txt", ".."],
)
def test_resolve_output_path_rejects_unsafe_filename(tmp_path, filename):
    with pytest.raises(OfficePathError):
        resolve_output_path(str(tmp_path), OfficeDocType.WORD, filename)
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_path_safety.py -k resolve_output_path -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_output_path'`

- [ ] **Step 3: 实现**

在 `backend/office/path_safety.py` 中 `validate_supported_filename` 之后、`_validate_doc_id` 之前插入（**Py3.8 兼容语法**）：

```python
def resolve_output_path(output_dir: str, doc_type: OfficeDocType, filename: str) -> Path:
    """Compose an output path under an arbitrary (trusted) target directory.

    Unlike :func:`managed_document_path` (workspace sandbox), ``output_dir``
    is a user-specified directory (Desktop, Downloads, ...) that the caller
    has already authorized to write into. The ``filename`` is still validated
    via :func:`validate_supported_filename` (no separators / traversal /
    wrong extension), so a hostile filename cannot escape ``output_dir``.
    """
    safe_filename = validate_supported_filename(filename, doc_type)
    target_dir = Path(output_dir).expanduser().resolve()
    return target_dir / safe_filename
```

把 `resolve_output_path` 加入模块底部 `__all__` 列表。

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_path_safety.py -k resolve_output_path -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/office/path_safety.py backend/tests/unit/office/test_path_safety.py
git commit -m "feat: path_safety.resolve_output_path 支持信任目标目录组合"
```

---

### Task 2: 生成器 `output_dir` 参数（word / excel / ppt）

**Files:**
- Modify: `backend/office/word.py`（`generate_docx`，196-244 行区域）
- Modify: `backend/office/excel.py`（`generate_xlsx`，195-237 行区域）
- Modify: `backend/office/ppt.py`（`generate_ppt`，236-286 行区域）
- Test: Create `backend/tests/unit/office/test_generate_output_dir.py`

**Interfaces:**
- Consumes: Task 1 的 `resolve_output_path`；`managed_document_path` / `validate_workspace`（现状，`output_dir=None` 分支保持）
- Produces: `generate_docx(req, output_dir: Optional[str] = None) -> Path`（word/excel/ppt 同签名），供 Task 3 的 `OfficeCreateTool` 调用。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/unit/office/test_generate_output_dir.py`：

```python
"""生成器 output_dir 参数测试：任意路径写入 + 默认行为回归。"""

from __future__ import annotations

import pytest

from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.models import (
    ExcelSheetSpec,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
    PptSlideSpec,
    WordParagraphSpec,
)
from backend.office.ppt import generate_ppt, read_ppt
from backend.office.word import generate_docx, read_docx

pytestmark = pytest.mark.unit


def test_generate_docx_with_output_dir(tmp_path):
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename="weather.docx",
        title="天气",
        paragraphs=[WordParagraphSpec(text="今天天气很好")],
    )
    out = generate_docx(req, output_dir=str(tmp_path))
    assert out == (tmp_path / "weather.docx")
    assert out.exists()
    result = read_docx(out, workspace_path="")
    assert [p.text for p in result.paragraphs] == ["今天天气很好"]


def test_generate_xlsx_with_output_dir(tmp_path):
    req = OfficeExcelGenerateRequest(
        workspace_path="",
        filename="report.xlsx",
        sheets=[ExcelSheetSpec(name="Sheet1", headers=["A", "B"], rows=[["1", "2"]])],
    )
    out = generate_xlsx(req, output_dir=str(tmp_path))
    assert out == (tmp_path / "report.xlsx")
    assert out.exists()
    result = read_xlsx(out, workspace_path="")
    assert result.sheets[0].rows[0] == ["1", "2"]


def test_generate_ppt_with_output_dir(tmp_path):
    req = OfficePptGenerateRequest(
        workspace_path="",
        filename="deck.pptx",
        slides=[PptSlideSpec(title="标题", bullets=["第一点", "第二点"])],
    )
    out = generate_ppt(req, output_dir=str(tmp_path))
    assert out == (tmp_path / "deck.pptx")
    assert out.exists()
    result = read_ppt(out, workspace_path="")
    assert result.slides[0].title == "标题"


def test_generate_docx_default_output_dir_still_uses_workspace(tmp_path):
    """回归：不传 output_dir 时行为与 HTTP 端点完全一致（写 workspace 沙箱）。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    req = OfficeWordGenerateRequest(
        workspace_path=str(workspace), filename="a.docx", title="t"
    )
    out = generate_docx(req)  # output_dir=None → managed_document_path
    assert workspace in out.parents
    assert out.exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_generate_output_dir.py -v`
Expected: FAIL with `TypeError: generate_docx() got an unexpected keyword argument 'output_dir'`

- [ ] **Step 3: 实现**（三文件同样模式）

**`backend/office/word.py::generate_docx`** — 把函数签名和路径解析段改为：

```python
def generate_docx(req, output_dir: Optional[str] = None) -> Path:
    """Generate a .docx file from structured Pydantic input.

    ``output_dir`` 提供时写入该任意目录（信任的用户指定目录，经
    :func:`resolve_output_path` 校验文件名）；``None`` 时保持现状写
    workspace 沙箱（``<workspace>/office/word/<id>/<name>``）。
    """
    import uuid

    from docx import Document as _Doc

    from .errors import OfficeGenerateError
    from .models import OfficeDocType
    from .path_safety import managed_document_path, resolve_output_path
    from .storage import validate_workspace

    if output_dir is not None:
        output_path = resolve_output_path(output_dir, OfficeDocType.WORD, req.filename)
    else:
        workspace = validate_workspace(Path(req.workspace_path))
        doc_id = uuid.uuid4().hex
        output_path = managed_document_path(workspace, OfficeDocType.WORD, doc_id, req.filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
```

（其余 body 不变。注意 `doc_id` 仅在不走 output_dir 分支时定义，与原逻辑一致。）

**`backend/office/excel.py::generate_xlsx`** — 同模式，`OfficeDocType.EXCEL`；把 210-216 行替换为：

```python
    if output_dir is not None:
        output_path = resolve_output_path(output_dir, OfficeDocType.EXCEL, req.filename)
    else:
        workspace = validate_workspace(Path(req.workspace_path))
        doc_id = uuid.uuid4().hex
        output_path = managed_document_path(workspace, OfficeDocType.EXCEL, doc_id, req.filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
```

并把函数签名改为 `def generate_xlsx(req, output_dir: Optional[str] = None) -> Path:`，import 增加 `resolve_output_path`。

**`backend/office/ppt.py::generate_ppt`** — 同模式，`OfficeDocType.PPT`；把 243-252 行替换为：

```python
    if output_dir is not None:
        output_path = resolve_output_path(output_dir, OfficeDocType.PPT, req.filename)
    else:
        workspace = validate_workspace(Path(req.workspace_path))
        import uuid
        doc_id = uuid.uuid4().hex
        output_path = managed_document_path(workspace, OfficeDocType.PPT, doc_id, req.filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
```

签名改为 `def generate_ppt(req, output_dir: Optional[str] = None) -> Path:`。

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_generate_output_dir.py backend/tests/unit/office/test_word.py backend/tests/unit/office/test_excel.py backend/tests/unit/office/test_ppt.py -v`
Expected: 全部 PASS（含新增 output_dir 用例 + 现有生成器回归）

- [ ] **Step 5: Commit**

```bash
git add backend/office/word.py backend/office/excel.py backend/office/ppt.py backend/tests/unit/office/test_generate_output_dir.py
git commit -m "feat: 生成器支持 output_dir 任意路径写入（默认行为不变）"
```

---

### Task 3: `OfficeCreateTool` 工具

**Files:**
- Create: `backend/tools/office_create_tool.py`
- Test: Create `backend/tests/unit/tools/test_office_create_tool.py`

**Interfaces:**
- Consumes: Task 2 的 `generate_docx/generate_xlsx/generate_ppt`（带 `output_dir`）；`models.py` 生成请求模型；`path_safety.validate_supported_filename`；`file_tool._record_artifact_safely`；`BaseTool`
- Produces: `OfficeCreateTool`（`name="office_create"`，`requires_tool_context=False`，`risk=WRITE_LOCAL`），供 Task 5 的 `register_all_tools` 注册。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/unit/tools/test_office_create_tool.py`：

```python
"""Unit tests for :mod:`backend.tools.office_create_tool`."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.office.excel import read_xlsx
from backend.office.word import read_docx
from backend.tools.office_create_tool import OfficeCreateTool

pytestmark = pytest.mark.unit


def _tool(**policy_kwargs) -> OfficeCreateTool:
    return OfficeCreateTool(policy=ToolPolicy(**policy_kwargs))


def _word_args(output_dir: str) -> dict:
    return {
        "doc_type": "word",
        "output_dir": output_dir,
        "filename": "天气.docx",
        "content": {"title": "天气", "paragraphs": [{"text": "今天天气很好"}]},
    }


def test_schema_requires_no_tool_context_and_exposes_fields():
    tool = _tool()
    assert tool.requires_tool_context is False
    props = tool.schema.parameters["properties"]
    assert set(props.keys()) == {"doc_type", "output_dir", "filename", "content"}
    assert props["doc_type"]["enum"] == ["word", "excel", "ppt"]


def test_create_word_to_output_dir(tmp_path):
    out_dir = tmp_path / "desktop"
    out_dir.mkdir()
    result = _tool().execute(**_word_args(str(out_dir)))
    assert result.success is True
    target = out_dir / "天气.docx"
    assert result.content["path"] == str(target)
    assert target.exists()
    parsed = read_docx(target, workspace_path="")
    assert [p.text for p in parsed.paragraphs] == ["今天天气很好"]


def test_create_excel_to_output_dir(tmp_path):
    result = _tool().execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="data.xlsx",
        content={"sheets": [{"name": "S1", "headers": ["A"], "rows": [["1"]]}]},
    )
    assert result.success is True
    target = tmp_path / "data.xlsx"
    assert target.exists()
    parsed = read_xlsx(target, workspace_path="")
    assert parsed.sheets[0].rows[0] == ["1"]


def test_create_ppt_to_output_dir(tmp_path):
    result = _tool().execute(
        doc_type="ppt",
        output_dir=str(tmp_path),
        filename="deck.pptx",
        content={"slides": [{"title": "标题", "bullets": ["点"]}]},
    )
    assert result.success is True
    assert (tmp_path / "deck.pptx").exists()


def test_rejects_existing_target_file(tmp_path):
    target = tmp_path / "天气.docx"
    target.write_text("occupied")
    result = _tool().execute(**_word_args(str(tmp_path)))
    assert result.success is False
    assert result.error.startswith("file_exists")


def test_rejects_output_dir_that_is_a_file(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    result = _tool().execute(**{**_word_args(str(blocker)), "filename": "a.docx"})
    assert result.success is False
    assert result.error == "output_dir_not_directory"


def test_rejects_unsupported_doc_type(tmp_path):
    result = _tool().execute(doc_type="pdf", output_dir=str(tmp_path), filename="a.pdf", content={})
    assert result.success is False
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/tools/test_office_create_tool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.tools.office_create_tool'`

- [ ] **Step 3: 实现**

新建 `backend/tools/office_create_tool.py`：

```python
"""Office create tool for the LLM tool loop.

``office_create`` lets the LLM generate a Word / Excel / PPT document to an
arbitrary (trusted) target directory -- e.g. the user's Desktop. Unlike the
existing ``office_list`` / ``office_read`` (which need an @-mention to bind a
``ToolExecutionContext``), ``requires_tool_context = False`` so the tool is
always visible and a plain question ("create a word doc on my desktop") can
trigger it directly.

Writing outside the session workspace is gated by ``path_boundary_validator``
in the M1 ``PermissionEnforcer`` (see permissions.py) -- the tool itself is a
pure executor and performs no permission decisions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain.risk import RiskClass
from backend.office.excel import generate_xlsx
from backend.office.models import (
    OfficeDocType,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
)
from backend.office.path_safety import OfficePathError, validate_supported_filename
from backend.office.ppt import generate_ppt
from backend.office.word import generate_docx
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.file_tool import _record_artifact_safely

#: doc_type 参数合法取值（与 models.OfficeDocType 对齐）
_VALID_DOC_TYPES = ("word", "excel", "ppt")


class OfficeCreateTool(BaseTool):
    """Generate an Office document (word/excel/ppt) to a target directory."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_create",
            description=(
                "Create a new Office document (Word/Excel/PPT) and write it to "
                "a target directory. Use when the user asks to create / generate "
                "a .docx/.xlsx/.pptx file (e.g. on their Desktop). `content` is "
                "an object whose shape depends on `doc_type`: word → "
                "{title, paragraphs:[{text, heading?}], tables:[{headers, rows[]}]}, "
                "excel → {sheets:[{name, headers[], rows[]}]}, ppt → "
                "{slides:[{title, bullets[], notes?}]}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_type": {
                        "type": "string",
                        "enum": list(_VALID_DOC_TYPES),
                        "description": "Document type to create.",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Target directory (absolute or ~-prefixed, e.g. "
                            "~/Desktop). Directory is created if missing."
                        ),
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Output filename. Extension is appended if missing "
                            "(.docx/.xlsx/.pptx); a wrong extension is rejected."
                        ),
                    },
                    "content": {
                        "type": "object",
                        "description": "Structured content keyed by doc_type.",
                    },
                },
                "required": ["doc_type", "output_dir", "filename", "content"],
            },
        )

    def execute(
        self,
        doc_type: Optional[str] = None,
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        # --- 参数校验（fail-fast） -----------------------------------------
        if doc_type not in _VALID_DOC_TYPES:
            return ToolResult(success=False, error=f"unsupported_doc_type: {doc_type}")
        if not isinstance(output_dir, str) or not output_dir.strip():
            return ToolResult(success=False, error="output_dir_required")
        if not isinstance(filename, str) or not filename.strip():
            return ToolResult(success=False, error="filename_required")
        if not isinstance(content, dict) or not content:
            return ToolResult(success=False, error="content_required")

        doc_type_enum = OfficeDocType(doc_type)

        # --- 路径守卫：目录必须是目录；目标文件已存在则拒绝（不覆盖） ------
        target_dir = Path(output_dir).expanduser().resolve()
        if target_dir.exists() and not target_dir.is_dir():
            return ToolResult(success=False, error="output_dir_not_directory")
        try:
            safe_name = validate_supported_filename(filename, doc_type_enum)
        except OfficePathError as exc:
            return ToolResult(success=False, error=str(exc))
        target_file = target_dir / safe_name
        if target_file.exists():
            return ToolResult(
                success=False,
                error=f"file_exists: {target_file} 已存在，请更换文件名",
            )

        # --- 构造生成请求并执行（复用生成器 + Pydantic 校验） --------------
        payload: Dict[str, Any] = dict(content)
        payload["workspace_path"] = ""
        payload["filename"] = filename
        try:
            if doc_type_enum is OfficeDocType.WORD:
                req = OfficeWordGenerateRequest(**payload)
                output = generate_docx(req, output_dir=str(target_dir))
            elif doc_type_enum is OfficeDocType.EXCEL:
                req = OfficeExcelGenerateRequest(**payload)
                output = generate_xlsx(req, output_dir=str(target_dir))
            else:
                req = OfficePptGenerateRequest(**payload)
                output = generate_ppt(req, output_dir=str(target_dir))
        except Exception as exc:
            return ToolResult(success=False, error=f"generate_failed: {exc}")

        # --- 记录 Artifacts（无 tool_context 时静默跳过，不阻断结果） ------
        try:
            _record_artifact_safely(str(output), output.stat().st_size)
        except Exception:
            pass

        return ToolResult(
            success=True,
            content={
                "path": str(output),
                "filename": output.name,
                "bytes": output.stat().st_size,
            },
        )


__all__ = ["OfficeCreateTool"]
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/tools/test_office_create_tool.py -v`
Expected: PASS（注意 `test_create_ppt_to_output_dir` 需 `python-pptx` 已装，sage-backend 环境已具备）

- [ ] **Step 5: Commit**

```bash
git add backend/tools/office_create_tool.py backend/tests/unit/tools/test_office_create_tool.py
git commit -m "feat: OfficeCreateTool 工具（word/excel/ppt 任意路径生成，防覆盖）"
```

---

### Task 4: `PermissionEnforcer` 注入 `path_boundary_validator`

**Files:**
- Modify: `backend/tools/permissions.py`
- Test: `backend/tests/unit/test_permissions_enforcer.py`

**Interfaces:**
- Consumes: `_ask` / `PermissionDecision` / `PermissionMode` / `_is_safe_path`（`backend/tools/base.py`）
- Produces:
  - `TOOL_CAPABILITIES["office_create"] = ToolCapability.WRITE`
  - `PermissionEnforcer(..., path_boundary_validator=None)` 可选构造参数
  - `make_office_path_boundary(boundary_resolver)` 工厂 → `Callable[[str, Dict], Optional[PermissionDecision]]`
  - `load_enforcer_from_settings(repo=None, path_boundary_validator=None)` 透传参数
  供 Task 5 装配。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_permissions_enforcer.py` 末尾追加（复用文件顶部已有 imports，另需 `from backend.tools.permissions import make_office_path_boundary` 追加到顶部 import 块）：

```python
def test_office_create_registered_as_write_capability():
    assert TOOL_CAPABILITIES["office_create"] is ToolCapability.WRITE


def test_path_boundary_within_workspace_allows(tmp_path):
    enforcer = PermissionEnforcer(
        mode=PermissionMode.WORKSPACE_WRITE,
        rules=[],
        path_boundary_validator=make_office_path_boundary(lambda: str(tmp_path)),
    )
    decision = enforcer.check("office_create", {"output_dir": str(tmp_path / "sub")})
    assert decision.allowed is True
    assert decision.needs_approval is False


def test_path_boundary_outside_workspace_asks(tmp_path, tmp_path_factory):
    workspace = tmp_path
    outside = tmp_path_factory.mktemp("outside")
    enforcer = PermissionEnforcer(
        mode=PermissionMode.WORKSPACE_WRITE,
        rules=[],
        path_boundary_validator=make_office_path_boundary(lambda: str(workspace)),
    )
    decision = enforcer.check("office_create", {"output_dir": str(outside)})
    assert decision.allowed is False
    assert decision.needs_approval is True
    assert "工作区外" in decision.reason


def test_path_boundary_unbound_workspace_allows(tmp_path):
    enforcer = PermissionEnforcer(
        mode=PermissionMode.WORKSPACE_WRITE,
        rules=[],
        path_boundary_validator=make_office_path_boundary(lambda: None),
    )
    decision = enforcer.check("office_create", {"output_dir": str(tmp_path)})
    assert decision.allowed is True


def test_path_boundary_read_only_mode_denies(tmp_path):
    enforcer = PermissionEnforcer(
        mode=PermissionMode.READ_ONLY,
        rules=[],
        path_boundary_validator=make_office_path_boundary(lambda: str(tmp_path)),
    )
    decision = enforcer.check("office_create", {"output_dir": str(tmp_path)})
    assert decision.allowed is False
    assert decision.needs_approval is False


def test_path_boundary_full_access_mode_bypasses_validation(tmp_path):
    enforcer = PermissionEnforcer(
        mode=PermissionMode.FULL_ACCESS,
        rules=[],
        path_boundary_validator=make_office_path_boundary(lambda: str(tmp_path)),
    )
    # 即使 target 在 workspace 外，FULL_ACCESS 也放行（用户已确认语义）
    decision = enforcer.check("office_create", {"output_dir": "/tmp/elsewhere"})
    assert decision.allowed is True
    assert decision.needs_approval is False


def test_path_boundary_ignores_non_office_tools(tmp_path):
    enforcer = PermissionEnforcer(
        mode=PermissionMode.WORKSPACE_WRITE,
        rules=[],
        path_boundary_validator=make_office_path_boundary(lambda: str(tmp_path)),
    )
    decision = enforcer.check("write_file", {"path": "/tmp/x"})
    assert decision.allowed is True  # 不干预其他工具


def test_path_boundary_without_validator_unaffected(tmp_path):
    enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE_WRITE, rules=[])
    decision = enforcer.check("office_create", {"output_dir": str(tmp_path)})
    assert decision.allowed is True  # 无 validator 时保持旧行为
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_permissions_enforcer.py -v`
Expected: FAIL（`ImportError` 或 `AttributeError: 'PermissionEnforcer' object has no attribute '_path_boundary_validator'`）

- [ ] **Step 3: 实现**

**`backend/tools/permissions.py`：**

(a) 文件顶部 import 增加：

```python
from backend.tools.base import _is_safe_path
```

（`base.py` 不 import `permissions.py`，无循环依赖。）

(b) `TOOL_CAPABILITIES` 字典中 `"write_file": ToolCapability.WRITE,` 之后增加：

```python
    "office_create": ToolCapability.WRITE,
```

(c) `PermissionEnforcer.__init__` 增加参数与属性：

```python
    def __init__(
        self,
        mode: PermissionMode,
        rules: Sequence[PermissionRule],
        bash_validator: Optional[Callable[[str], Any]] = None,
        path_boundary_validator: Optional[
            Callable[[str, Dict[str, Any]], Optional[PermissionDecision]]
        ] = None,
    ) -> None:
        self._mode = mode
        self._rules: Tuple[PermissionRule, ...] = tuple(rules)
        self._bash_validator = bash_validator
        self._path_boundary_validator = path_boundary_validator
```

(d) `check()` 末尾 `return self._mode_decision(tool_name, capability, bash_result)` 改为：

```python
        decision = self._mode_decision(tool_name, capability, bash_result)
        # path boundary override（M1 架构对称扩展）：非 FULL_ACCESS 且原决策
        # 为 allow 时，边界校验可把"写工作区外"升级为 ask/deny。
        if (
            decision.allowed
            and self._mode is not PermissionMode.FULL_ACCESS
            and self._path_boundary_validator is not None
        ):
            override = self._path_boundary_validator(tool_name, args)
            if override is not None:
                return override
        return decision
```

(e) 模块级新增工厂（`load_enforcer_from_settings` 之前）：

```python
def make_office_path_boundary(
    boundary_resolver: Optional[Callable[[], Optional[str]]] = None,
) -> Callable[[str, Dict[str, Any]], Optional[PermissionDecision]]:
    """构造 ``office_create`` 的 path-boundary 校验器。

    ``boundary_resolver`` 每次调用返回当前会话 workspace_root（``None`` 表示
    未绑定 → 不检查边界，与 write_file 未绑定语义一致）。返回的校验器仅对
    ``office_create`` 且带非空 ``output_dir`` 参数生效：目标目录 resolve 后
    落在 workspace 内 → ``None``（放行）；在外 → ``ask``（写工作区外需确认）。
    """

    def _validator(tool_name: str, args: Dict[str, Any]) -> Optional[PermissionDecision]:
        if tool_name != "office_create":
            return None
        if boundary_resolver is None:
            return None
        root = boundary_resolver()
        if not root:
            return None
        output_dir = args.get("output_dir")
        if not isinstance(output_dir, str) or not output_dir.strip():
            return None
        if _is_safe_path(output_dir, root):
            return None
        return _ask(f"office_create 写入工作区外的路径 {output_dir}，需要用户确认")

    return _validator
```

(f) `load_enforcer_from_settings` 签名加透传参数，并把 `PermissionEnforcer(...)` 构造传入：

```python
def load_enforcer_from_settings(
    repo: Optional[Any] = None,
    path_boundary_validator: Optional[Callable] = None,
) -> PermissionEnforcer:
    ...
    return PermissionEnforcer(
        mode=mode, rules=rules, bash_validator=validate_bash,
        path_boundary_validator=path_boundary_validator,
    )
```

（异常 fallback 分支同样加 `path_boundary_validator=path_boundary_validator`。）

(g) `__all__` 增加 `"make_office_path_boundary"`。

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_permissions_enforcer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tools/permissions.py backend/tests/unit/test_permissions_enforcer.py
git commit -m "feat: PermissionEnforcer path_boundary_validator + office_create 写工作区外升级审批"
```

---

### Task 5: 注册 + agent 装配 + 集成测试

**Files:**
- Modify: `backend/tools/__init__.py`（`register_all_tools`）
- Modify: `backend/core/legacy/agent.py`（`_build_permission_enforcer` + 新增 `_office_boundary_resolver`）
- Test: Create `backend/tests/integration/test_agent_office_create_flow.py`

**Interfaces:**
- Consumes: Task 3 的 `OfficeCreateTool`；Task 4 的 `make_office_path_boundary` / `load_enforcer_from_settings` / `DEFAULT_PERMISSION_MODE`；`backend.tools.context.current_tool_context`；`backend.office.session_workspace.get_workspace_binding`；`backend.data.database.get_database`
- Produces: `register_all_tools` 包含 `office_create`；`SageAgent._build_permission_enforcer` 装配默认 boundary validator（边界来自会话绑定）。

- [ ] **Step 1: 写集成测试（先失败：工具未注册）**

新建 `backend/tests/integration/test_agent_office_create_flow.py`：

```python
"""office_create 审批链集成测试：写工作区外 → permission_request → 批准 → 生成。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.data.database import get_database
from backend.office.session_workspace import bind_session_workspace
from backend.services.permission_gate import init_permission_gate, reset_permission_gate
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _gate_lifecycle():
    reset_permission_gate()
    yield
    reset_permission_gate()


def _office_agent(workspace_out: Path) -> SageAgent:
    """LLM 第一轮返回 office_create（写 workspace 外的目录），第二轮给终答。

    permission_enforcer 不注入 → 走 _build_permission_enforcer 默认装配，
    其 boundary validator 经 _office_boundary_resolver 从会话绑定解析。
    """
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_office",
                        name="office_create",
                        arguments=(
                            '{"doc_type": "word", "output_dir": "%s", '
                            '"filename": "天气.docx", "content": {"title": "天气", '
                            '"paragraphs": [{"text": "今天天气很好"}]}}'
                            % str(workspace_out)
                        ),
                    )
                ],
            ),
            LLMResponse(content="已创建"),
        ]
    )
    return agent


async def test_office_create_outside_workspace_asks_then_creates(tmp_path):
    workspace_in = tmp_path / "ws-in"
    workspace_in.mkdir()
    workspace_out = tmp_path / "desktop"

    # 绑定会话到 workspace_in（office boundary 的来源）
    conn = get_database().get_connection()
    bind_session_workspace(conn, "sess-office-1", str(workspace_in))
    ctx = ToolExecutionContext(
        session_id="sess-office-1",
        stream_id="stream-1",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)

    agent = _office_agent(workspace_out)
    gate = init_permission_gate()
    answered = {}

    async def approver():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        answered["request"] = pending[0]
        assert pending[0].tool_name == "office_create"
        gate.answer(pending[0].request_id, approved=True)

    try:
        approver_task = asyncio.create_task(approver())
        events = []
        async for evt in agent.run_loop([{"role": "user", "content": "帮我建 word 到桌面"}]):
            events.append(evt)
        await approver_task
    finally:
        reset_tool_context(token)

    states = [e.state for e in events]
    assert AgentState.PERMISSION_REQUEST in states
    assert events[-1].state == AgentState.DONE
    assert (workspace_out / "天气.docx").exists()


async def test_office_create_denial_does_not_create(tmp_path):
    workspace_in = tmp_path / "ws-in"
    workspace_in.mkdir()
    workspace_out = tmp_path / "desktop"

    conn = get_database().get_connection()
    bind_session_workspace(conn, "sess-office-2", str(workspace_in))
    ctx = ToolExecutionContext(
        session_id="sess-office-2",
        stream_id="stream-2",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)

    agent = _office_agent(workspace_out)
    gate = init_permission_gate()

    async def denier():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        gate.answer(pending[0].request_id, approved=False)

    try:
        denier_task = asyncio.create_task(denier())
        events = []
        async for evt in agent.run_loop([{"role": "user", "content": "帮我建 word 到桌面"}]):
            events.append(evt)
        await denier_task
    finally:
        reset_tool_context(token)

    assert not (workspace_out / "天气.docx").exists()
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "未获批准" in observing.tool_result.content
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_agent_office_create_flow.py -v`
Expected: FAIL（office_create 尚未注册 → "工具不存在"，或 run_loop 早期错误）

- [ ] **Step 3: 注册 + 装配实现**

**(a) `backend/tools/__init__.py`**：在现有 `OfficeReadTool(policy=policy)` 注册之后加：

```python
    from backend.tools.office_create_tool import OfficeCreateTool

    registry.register(OfficeCreateTool(policy=policy))
```

（保持既有 import 风格——若该文件顶部已 import 工具类则并入顶部，否则与 `office_tool` 的局部 import 风格一致。）

**(b) `backend/core/legacy/agent.py`**：

- 顶部 import 增加（若已存在则并入，避免重复）：

```python
from backend.data.database import get_database
from backend.tools.context import current_tool_context
from backend.tools.permissions import (
    DEFAULT_PERMISSION_MODE,
    make_office_path_boundary,
)
```

（确认 `DEFAULT_PERMISSION_MODE`、`validate_bash` 已在既有 import 中。）

- 新增方法（放在 `_build_permission_enforcer` 附近）：

```python
    def _office_boundary_resolver(self) -> Optional[str]:
        """从当前会话绑定解析 workspace_root；未绑定返回 None。"""
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return None
        try:
            from backend.office.session_workspace import get_workspace_binding

            binding = get_workspace_binding(
                get_database().get_connection(), ctx.session_id
            )
            return binding.workspace_path if binding is not None else None
        except Exception:
            return None
```

- 改写 `_build_permission_enforcer`（现有 907-922 行区域）：

```python
    def _build_permission_enforcer(self) -> PermissionEnforcer:
        """构造本轮 run 的权限执行器。

        优先用注入的 ``self.permission_enforcer``；否则从 settings 现读。
        office_create 的 path boundary 校验器注入：边界来自当前会话绑定
        （``_office_boundary_resolver``），写工作区外升级为 ask。
        """
        if self.permission_enforcer is not None:
            return self.permission_enforcer
        validator = make_office_path_boundary(self._office_boundary_resolver)
        try:
            return load_enforcer_from_settings(path_boundary_validator=validator)
        except Exception as exc:  # noqa: BLE001 — DB 故障不应阻塞 agent 启动
            logger.warning("权限执行器从 settings 构造失败，回退默认: %s", exc)
            return PermissionEnforcer(
                mode=DEFAULT_PERMISSION_MODE,
                rules=(),
                bash_validator=validate_bash,
                path_boundary_validator=validator,
            )
```

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_agent_office_create_flow.py -v`
Expected: PASS

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_path_safety.py backend/tests/unit/office/test_generate_output_dir.py backend/tests/unit/tools/test_office_create_tool.py backend/tests/unit/test_permissions_enforcer.py -q`
Expected: 全绿

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_agent_permission_flow.py backend/tests/integration/test_office_routes.py -q`
Expected: 全绿（确认无回归）

- [ ] **Step 5: Commit**

```bash
git add backend/tools/__init__.py backend/core/legacy/agent.py backend/tests/integration/test_agent_office_create_flow.py
git commit -m "feat: 注册 office_create + agent 装配会话绑定边界（写工作区外审批）"
```

---

### Task 6: 手动验证（Electron）

- [ ] **Step 1: 启动后端 + 前端**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py &
npm run dev
```

- [ ] **Step 2: 在 Electron 对话中提问**

输入："帮我在桌面上创建一份 Word 文档，写入『今天天气很好』"
Expected: LLM 调用 `office_create` → 若会话绑定 workspace 且桌面在 workspace 外 → 弹出 ApprovalDialog → 允许 → 桌面生成 `天气.docx`；LLM 汇报路径。

- [ ] **Step 3: 验证产物**

确认 `~/Desktop/天气.docx` 存在且可打开；对话 Artifacts 面板出现该文件记录。

- [ ] **Step 4: 回归确认**

现有 Office 读取（@提及 → `office_list`/`office_read`）仍正常；`/word/generate` HTTP 端点仍写 workspace 沙箱。
