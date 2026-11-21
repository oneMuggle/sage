# M1a：文献调研最小闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `backend/literature/` 上打通"运行目录 + 文件契约 + 确定性门禁 + Markdown/BibTeX 导出 + profile 驱动浏览器执行器 + `literature-research` skill"的最小闭环，为 xueshu789 录制与实跑提供可执行骨架。

**Architecture:** 纯 Python 领域模块 + JSONL/JSON 运行目录；LLM 负责语义检索/筛选/写作，确定性 Python 负责 schema 校验、引用解析、门禁与导出；skill 通过 `execute_code` 调用这些模块，浏览器动作仍走现有 `browser_*` 工具。不新增 chat 工具，避免 tool_names/capability 棘轮。

**Tech Stack:** Python 3.10（开发）/ 3.8（兼容）；PyYAML；dataclasses；pytest；现有 Sage browser 工具与 execute_code。

**Spec:** `docs/plans/2026-11-21_literature-research-paper-pipeline.md`（M1 里程碑）

> **实施状态（2026-11-21）**：Task 1–8 已在分支
> `feat/literature-research-m1` 上完成；`backend/tests/unit/test_literature_pipeline.py`
> 26 例通过，含端到端合成闭环。真实 xueshu789 录制/检索与编排 lane 接入留 M1b。

## Global Constraints

- Python 3.8 兼容：`typing.Optional/List/Dict/Tuple`，禁止 PEP 604/585；`# noqa: UP038` 处理 tuple isinstance。
- 不新增第三方依赖；不新增 chat 工具；不修改现有 `academic-search` / `cnki-research` / `paper-writing` 行为。
- 站点差异只在 profile；pipeline 禁止 `if site == ...`。
- 不捕获裸 `Exception`；只捕获明确的 `SiteProfileError` / `yaml.YAMLError` / `OSError` / `ValueError`。
- 运行目录写入原子化（临时文件 + `os.replace`）；JSON 日期统一 ISO 8601 UTC（`2026-11-21T09:30:00+00:00`）。
- 引用语法：`[cite:KEY]` 或 `[cite:KEY1, KEY2]`；引用 key 只能来自 papers 池。
- 测试 hermetic：`tmp_path`；不依赖 `~/.sage`、网络、真实浏览器。
- 合规：仅本人账号/机构授权；不代填密码、不导出 cookie、不绕过付费墙。

---

## File Structure

**Create**
- `backend/literature/pipeline_models.py` — EvidenceRecord / Outline / GateReport / from_dict 校验
- `backend/literature/run_store.py` — 运行目录、meta/JSONL/JSON 读写、状态
- `backend/literature/gates.py` — 引用解析、证据/大纲校验、运行门禁、参考文献生成
- `backend/literature/export.py` — final.md / references.json / papers.bib / paper-writing handoff
- `backend/literature/search.py` — BrowserDriver 协议、profile 驱动检索/下载、PDF 校验
- `backend/literature/recording.py` — 从观测 JSON 生成 draft profile YAML
- `backend/literature/cli.py` — `python -m backend.literature.cli` 子命令
- `backend/skills/skill_md/shipped/literature-research/SKILL.md`
- `backend/skills/skill_md/shipped/literature-research/references/pipeline.md`
- `backend/tests/unit/test_literature_pipeline.py`

**Modify**
- `docs/plans/2026-11-21_literature-research-paper-pipeline.md` — M1 勾选
- `backend/tests/unit/test_shipped_writing_skills.py`（仅在新增技能影响断言时）

---

## Task 1: Pipeline 模型与校验

**Files:**
- Create: `backend/literature/pipeline_models.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`

**Interfaces:**
- Produces:
  - `EvidenceRecord` / `evidence_from_dict(raw)`
  - `OutlineSection` / `Outline` / `outline_from_dict(raw)`
  - `GateReport(ok, errors, warnings, citations)` / `.to_dict()`
  - `paper_record_from_dict(raw) -> PaperRecord`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/unit/test_literature_pipeline.py`:

```python
"""文献调研最小闭环：模型 / 运行目录 / 门禁 / 导出 / 检索 / CLI。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.literature.pipeline_models import (
    EvidenceRecord,
    Outline,
    GateReport,
    evidence_from_dict,
    outline_from_dict,
    paper_record_from_dict,
)

pytestmark = pytest.mark.unit


def _paper(key="p1", title="示例论文", authors=("张三",), year="2024"):
    return {
        "paper_key": key,
        "title": title,
        "authors": list(authors),
        "year": year,
        "venue": "示例期刊",
        "source_site": "demo",
    }


class TestPipelineModels:
    def test_paper_record_from_dict(self):
        record = paper_record_from_dict(_paper())
        assert record.paper_key == "p1"
        assert record.authors == ("张三",)
        with pytest.raises(ValueError, match="paper_key"):
            paper_record_from_dict({"title": "缺 key"})
        with pytest.raises(ValueError, match="title"):
            paper_record_from_dict({"paper_key": "p1", "title": " "})

    def test_evidence_from_dict_requires_paper_key(self):
        record = evidence_from_dict(
            {
                "evidence_id": "e1",
                "paper_key": "p1",
                "kind": "finding",
                "text": "发现 A",
                "locator": "p.3",
            }
        )
        assert record.kind == "finding"
        with pytest.raises(ValueError, match="paper_key"):
            evidence_from_dict({"evidence_id": "e1", "kind": "finding", "text": "x"})

    def test_outline_from_dict(self):
        outline = outline_from_dict(
            {
                "title": "综述",
                "sections": [
                    {"id": "s1", "title": "引言", "summary": "背景", "source_keys": ["p1"]}
                ],
            }
        )
        assert isinstance(outline, Outline)
        assert outline.sections[0].source_keys == ("p1",)
        with pytest.raises(ValueError, match="sections"):
            outline_from_dict({"title": "x", "sections": []})

    def test_gate_report_to_dict(self):
        report = GateReport(ok=False, errors=["bad"], warnings=["warn"], citations=["p1"])
        assert report.to_dict()["ok"] is False
        assert report.to_dict()["citations"] == ["p1"]
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-literature-research-m1
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
```
Expected: `ModuleNotFoundError: backend.literature.pipeline_models`。

- [ ] **Step 3: 实现模型**

Create `backend/literature/pipeline_models.py`:

```python
"""文献调研流水线的中间产物模型（Python 3.8 兼容）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import PaperRecord


def _require_str(value: Any, name: str, *, required: bool = True) -> str:
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ValueError(f"{name} 必填")
        return ""
    return value.strip()


def _str_tuple(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):  # noqa: UP038 — py38 兼容
        raise ValueError(f"{name} 必须是字符串数组")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} 不能包含空值")
        result.append(item.strip())
    return tuple(result)


def paper_record_from_dict(raw: Dict[str, Any]) -> PaperRecord:
    if not isinstance(raw, dict):
        raise ValueError("paper 必须是对象")
    key = _require_str(raw.get("paper_key"), "paper_key")
    title = _require_str(raw.get("title"), "title")
    authors = _str_tuple(raw.get("authors"), "authors")
    return PaperRecord(
        paper_key=key,
        title=title,
        authors=authors,
        year=_require_str(raw.get("year"), "year", required=False) or None,
        venue=_require_str(raw.get("venue"), "venue", required=False) or None,
        abstract=_require_str(raw.get("abstract"), "abstract", required=False) or None,
        url=_require_str(raw.get("url"), "url", required=False) or None,
        doi=_require_str(raw.get("doi"), "doi", required=False) or None,
        source_site=_require_str(raw.get("source_site"), "source_site", required=False),
        source_query=_require_str(raw.get("source_query"), "source_query", required=False)
        or None,
        retrieved_at=_require_str(raw.get("retrieved_at"), "retrieved_at", required=False)
        or None,
        fulltext_path=_require_str(
            raw.get("fulltext_path"), "fulltext_path", required=False
        )
        or None,
        language=_require_str(raw.get("language"), "language", required=False) or None,
        extra=dict(raw.get("extra") or {}),
    )


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    paper_key: str
    kind: str
    text: str
    locator: Optional[str] = None
    quote: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "paper_key": self.paper_key,
            "kind": self.kind,
            "text": self.text,
            "locator": self.locator,
            "quote": self.quote,
            "confidence": self.confidence,
        }


def evidence_from_dict(raw: Dict[str, Any]) -> EvidenceRecord:
    if not isinstance(raw, dict):
        raise ValueError("evidence 必须是对象")
    confidence = raw.get("confidence")
    if confidence is not None:
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence 必须在 0..1")
    return EvidenceRecord(
        evidence_id=_require_str(raw.get("evidence_id"), "evidence_id"),
        paper_key=_require_str(raw.get("paper_key"), "paper_key"),
        kind=_require_str(raw.get("kind"), "kind"),
        text=_require_str(raw.get("text"), "text"),
        locator=_require_str(raw.get("locator"), "locator", required=False) or None,
        quote=_require_str(raw.get("quote"), "quote", required=False) or None,
        confidence=confidence,
    )


@dataclass(frozen=True)
class OutlineSection:
    id: str
    title: str
    summary: str = ""
    source_keys: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Outline:
    title: str
    sections: Tuple[OutlineSection, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "summary": section.summary,
                    "source_keys": list(section.source_keys),
                }
                for section in self.sections
            ],
        }


def outline_from_dict(raw: Dict[str, Any]) -> Outline:
    if not isinstance(raw, dict):
        raise ValueError("outline 必须是对象")
    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ValueError("outline.sections 必须是非空数组")
    sections = []
    seen = set()
    for item in sections_raw:
        if not isinstance(item, dict):
            raise ValueError("outline.sections 元素必须是对象")
        section_id = _require_str(item.get("id"), "section.id")
        if section_id in seen:
            raise ValueError(f"section.id 重复: {section_id}")
        seen.add(section_id)
        sections.append(
            OutlineSection(
                id=section_id,
                title=_require_str(item.get("title"), "section.title"),
                summary=_require_str(item.get("summary"), "section.summary", required=False),
                source_keys=_str_tuple(item.get("source_keys"), "section.source_keys"),
            )
        )
    return Outline(
        title=_require_str(raw.get("title"), "outline.title"),
        sections=tuple(sections),
    )


@dataclass
class GateReport:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "citations": list(self.citations),
        }
```

- [ ] **Step 4: 测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
git add backend/literature/pipeline_models.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): add pipeline evidence/outline/gate models"
```

---

## Task 2: 运行目录与文件契约

**Files:**
- Create: `backend/literature/run_store.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`（追加）

**Interfaces:**
- Produces:
  - `LiteratureRun(run_id, run_dir, topic, site_id, created_at, status)`
  - `create_run(root, topic, site_id, run_id=None) -> LiteratureRun`
  - `load_run(run_dir) -> LiteratureRun`
  - `write_json / read_json / append_jsonl / read_jsonl / atomic_write_text`
  - `record_query`, `record_papers`, `record_evidence`, `save_outline`, `load_outline`, `save_draft`, `read_draft`, `list_papers`, `list_evidence`, `run_status`
  - 目录契约：
    ```
    <run>/
      meta.json
      query_log.jsonl
      papers.jsonl
      evidence.jsonl
      outline.json
      draft.md
      verification.json
      export/
    ```

- [ ] **Step 1: 追加失败测试**

```python
class TestRunStore:
    def test_create_load_and_status(self, tmp_path):
        from backend.literature.run_store import create_run, load_run, run_status

        run = create_run(tmp_path, topic="大模型综述", site_id="xueshu789", run_id="r1")
        assert run.run_dir == tmp_path / "r1"
        assert (run.run_dir / "meta.json").is_file()
        loaded = load_run(run.run_dir)
        assert loaded.topic == "大模型综述"
        status = run_status(run)
        assert status["papers"] == 0
        assert status["has_draft"] is False

    def test_record_papers_dedupes_by_key(self, tmp_path):
        from backend.literature.run_store import create_run, read_jsonl, record_papers

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        added = record_papers(run, [_paper("p1"), _paper("p1"), _paper("p2")])
        assert added == 2
        assert len(read_jsonl(run.run_dir / "papers.jsonl")) == 2

    def test_record_evidence_rejects_unknown_paper(self, tmp_path):
        from backend.literature.run_store import create_run, record_evidence

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        with pytest.raises(ValueError, match="paper_key"):
            record_evidence(
                run,
                [{"evidence_id": "e1", "paper_key": "missing", "kind": "finding", "text": "x"}],
            )

    def test_save_outline_and_draft(self, tmp_path):
        from backend.literature.run_store import (
            create_run, load_outline, read_draft, run_status, save_draft, save_outline,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        save_outline(run, {"title": "x", "sections": [{"id": "s1", "title": "引言"}]})
        assert load_outline(run).sections[0].id == "s1"
        save_draft(run, "# 草稿\n\n正文 [cite:p1]\n")
        assert "cite:p1" in read_draft(run)
        assert run_status(run)["has_draft"] is True

    def test_invalid_run_dir(self, tmp_path):
        from backend.literature.run_store import load_run

        with pytest.raises(ValueError, match="meta.json"):
            load_run(tmp_path / "missing")
```

- [ ] **Step 2: 实现 run_store**

Create `backend/literature/run_store.py`（关键实现）：

```python
"""文献调研运行目录：meta / 查询日志 / 文献池 / 证据 / 大纲 / 草稿。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .models import PaperRecord
from .pipeline_models import (
    EvidenceRecord,
    Outline,
    evidence_from_dict,
    outline_from_dict,
    paper_record_from_dict,
)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class LiteratureRun:
    run_id: str
    run_dir: Path
    topic: str
    site_id: str
    created_at: str
    status: str = "active"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def create_run(root: Path, topic: str, site_id: str, run_id: Optional[str] = None) -> LiteratureRun:
    if not topic.strip():
        raise ValueError("topic 不能为空")
    if not site_id.strip():
        raise ValueError("site_id 不能为空")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if not _RUN_ID_RE.match(run_id):
        raise ValueError("run_id 只能包含字母/数字/._-")
    run_dir = Path(root) / run_id
    if run_dir.exists():
        raise ValueError(f"运行目录已存在: {run_dir}")
    run_dir.mkdir(parents=True)
    meta = {
        "run_id": run_id,
        "topic": topic.strip(),
        "site_id": site_id.strip(),
        "created_at": _now_iso(),
        "status": "active",
    }
    write_json(run_dir / "meta.json", meta)
    return LiteratureRun(run_id, run_dir, meta["topic"], meta["site_id"], meta["created_at"])


def load_run(run_dir: Path) -> LiteratureRun:
    run_dir = Path(run_dir)
    meta = read_json(run_dir / "meta.json")
    if not isinstance(meta, dict):
        raise ValueError(f"缺少 meta.json: {run_dir}")
    return LiteratureRun(
        run_id=meta["run_id"],
        run_dir=run_dir,
        topic=meta["topic"],
        site_id=meta["site_id"],
        created_at=meta["created_at"],
        status=meta.get("status", "active"),
    )


def _papers(run: LiteratureRun) -> List[PaperRecord]:
    return [paper_record_from_dict(row) for row in read_jsonl(run.run_dir / "papers.jsonl")]


def record_query(run, query, site_id, result_count, note=None):
    append_jsonl(
        run.run_dir / "query_log.jsonl",
        [{"query": query, "site_id": site_id, "result_count": int(result_count),
          "note": note, "at": _now_iso()}],
    )


def record_papers(run, rows: Sequence[Dict[str, Any]]) -> int:
    existing = {p.paper_key for p in _papers(run)}
    new_rows = []
    for row in rows:
        record = paper_record_from_dict(row)
        if record.paper_key in existing:
            continue
        existing.add(record.paper_key)
        new_rows.append(record.to_dict())
    append_jsonl(run.run_dir / "papers.jsonl", new_rows)
    return len(new_rows)


def record_evidence(run, rows: Sequence[Dict[str, Any]]) -> int:
    known = {p.paper_key for p in _papers(run)}
    new_rows = []
    for row in rows:
        record = evidence_from_dict(row)
        if record.paper_key not in known:
            raise ValueError(f"paper_key 不在文献池中: {record.paper_key}")
        new_rows.append(record.to_dict())
    append_jsonl(run.run_dir / "evidence.jsonl", new_rows)
    return len(new_rows)


def save_outline(run, raw: Dict[str, Any]) -> Outline:
    outline = outline_from_dict(raw)
    write_json(run.run_dir / "outline.json", outline.to_dict())
    return outline


def load_outline(run) -> Optional[Outline]:
    raw = read_json(run.run_dir / "outline.json")
    return outline_from_dict(raw) if raw else None


def save_draft(run, text: str) -> None:
    if not text.strip():
        raise ValueError("草稿不能为空")
    atomic_write_text(run.run_dir / "draft.md", text)


def read_draft(run) -> str:
    path = run.run_dir / "draft.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def list_papers(run) -> List[PaperRecord]:
    return _papers(run)


def list_evidence(run) -> List[EvidenceRecord]:
    return [evidence_from_dict(row) for row in read_jsonl(run.run_dir / "evidence.jsonl")]


def run_status(run) -> Dict[str, Any]:
    return {
        "run_id": run.run_id,
        "topic": run.topic,
        "site_id": run.site_id,
        "status": run.status,
        "queries": len(read_jsonl(run.run_dir / "query_log.jsonl")),
        "papers": len(_papers(run)),
        "evidence": len(read_jsonl(run.run_dir / "evidence.jsonl")),
        "has_outline": (run.run_dir / "outline.json").is_file(),
        "has_draft": (run.run_dir / "draft.md").is_file(),
        "has_verification": (run.run_dir / "verification.json").is_file(),
    }
```

- [ ] **Step 3: 测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
git add backend/literature/run_store.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): add run store with jsonl artifacts and atomic writes"
```

---

## Task 3: 门禁与引用解析

**Files:**
- Create: `backend/literature/gates.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`（追加）

**Interfaces:**
- Produces:
  - `extract_citations(draft) -> List[str]`（首次出现顺序）
  - `run_gates(run) -> GateReport`（写 `verification.json`）
  - `build_references(draft, papers, style="gbt7714") -> Tuple[str, List[Dict[str, Any]]]`

- [ ] **Step 1: 追加失败测试**

```python
class TestGates:
    def _run(self, tmp_path):
        from backend.literature.run_store import (
            create_run, record_papers, save_draft, save_outline,
        )
        run = create_run(tmp_path, "t", "demo", run_id="r1")
        record_papers(run, [_paper("p1"), _paper("p2")])
        save_outline(run, {"title": "x", "sections": [
            {"id": "s1", "title": "引言", "source_keys": ["p1"]},
            {"id": "s2", "title": "方法", "source_keys": ["p2"]},
        ]})
        save_draft(run, "# 草稿\n\nP1 的发现 [cite:p1]。\n")
        return run

    def test_extract_citations_orders_and_splits(self):
        from backend.literature.gates import extract_citations
        assert extract_citations("a [cite:p2] b [cite:p1, p2] c [cite:p2]") == ["p2", "p1"]

    def test_gate_ok_with_unused_warning(self, tmp_path):
        from backend.literature.gates import run_gates
        report = run_gates(self._run(tmp_path))
        assert report.ok is True
        assert report.citations == ["p1"]
        assert any("p2" in w for w in report.warnings)

    def test_unresolved_citation_fails(self, tmp_path):
        from backend.literature.gates import run_gates
        from backend.literature.run_store import save_draft
        run = self._run(tmp_path)
        save_draft(run, "引用不存在的 [cite:missing]")
        report = run_gates(run)
        assert report.ok is False
        assert any("missing" in e for e in report.errors)

    def test_missing_query_log_fails(self, tmp_path):
        from backend.literature.gates import run_gates
        report = run_gates(self._run(tmp_path))
        assert any("检索日志" in e for e in report.errors)

    def test_build_references_only_cited(self):
        from backend.literature.gates import build_references
        from backend.literature.models import PaperRecord
        papers = [
            PaperRecord("p1", "论文一", ("张三", "李四"), "2024", "期刊A"),
            PaperRecord("p2", "论文二", ("王五",), "2023", "期刊B"),
        ]
        text, entries = build_references("b [cite:p2] a [cite:p1]", papers)
        assert "[1] 王五. 论文二[J]. 期刊B, 2023." in text
        assert "[2] 张三, 李四. 论文一[J]. 期刊A, 2024." in text
        assert [e["key"] for e in entries] == ["p2", "p1"]
```

- [ ] **Step 2: 实现 gates**

Create `backend/literature/gates.py`:

```python
"""确定性门禁：引用解析、证据/大纲校验、参考文献生成。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .models import PaperRecord
from .pipeline_models import GateReport
from .run_store import (
    list_evidence,
    list_papers,
    load_outline,
    read_draft,
    read_jsonl,
    write_json,
)

_CITE_RE = re.compile(r"\[cite:([^\]]+)\]")


def extract_citations(text: str) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for match in _CITE_RE.finditer(text or ""):
        for key in match.group(1).split(","):
            key = key.strip()
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def _author_text(authors: Sequence[str]) -> str:
    if not authors:
        return "佚名"
    if len(authors) <= 3:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + ", 等"


def _reference_line(number: int, paper: PaperRecord) -> str:
    authors = _author_text(paper.authors)
    venue = paper.venue or "[出版者不详]"
    year = paper.year or "[年份不详]"
    return f"[{number}] {authors}. {paper.title}[J]. {venue}, {year}."


def build_references(
    draft: str, papers: Sequence[PaperRecord], style: str = "gbt7714"
) -> Tuple[str, List[Dict[str, Any]]]:
    if style != "gbt7714":
        raise ValueError(f"暂不支持的引用样式: {style}")
    by_key = {p.paper_key: p for p in papers}
    entries: List[Dict[str, Any]] = []
    lines: List[str] = []
    for number, key in enumerate(extract_citations(draft), start=1):
        paper = by_key.get(key)
        if paper is None:
            continue
        lines.append(_reference_line(number, paper))
        entries.append({"key": key, "number": number, "paper": paper.to_dict()})
    return "\n".join(lines), entries


def run_gates(run) -> GateReport:
    errors: List[str] = []
    warnings: List[str] = []
    papers = list_papers(run)
    paper_keys = {p.paper_key for p in papers}
    draft = read_draft(run)

    if not read_jsonl(run.run_dir / "query_log.jsonl"):
        errors.append("检索日志为空：至少记录一次 query_log")
    if not papers:
        errors.append("文献池为空：没有可引用的文献")

    for evidence in list_evidence(run):
        if evidence.paper_key not in paper_keys:
            errors.append(f"证据 {evidence.evidence_id} 指向未知文献 {evidence.paper_key}")

    outline = load_outline(run)
    if outline is None:
        errors.append("缺少大纲 outline.json")
    else:
        for section in outline.sections:
            for key in section.source_keys:
                if key not in paper_keys:
                    errors.append(f"大纲章节 {section.id} 引用未知文献 {key}")

    if not draft.strip():
        errors.append("缺少草稿 draft.md")

    citations = extract_citations(draft)
    for key in citations:
        if key not in paper_keys:
            errors.append(f"草稿引用未知文献: {key}")
    for key in sorted(paper_keys - set(citations)):
        warnings.append(f"文献未被正文引用: {key}")

    report = GateReport(ok=not errors, errors=errors, warnings=warnings, citations=citations)
    write_json(run.run_dir / "verification.json", report.to_dict())
    return report
```

- [ ] **Step 3: 测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
git add backend/literature/gates.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): add deterministic citation and run gates"
```

---

## Task 4: 导出与 paper-writing 交接

**Files:**
- Create: `backend/literature/export.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`（追加）

**Interfaces:**
- Produces:
  - `export_run(run) -> Dict[str, Path]`
  - `build_bibtex(papers, cited_keys) -> str`
  - `build_handoff(run) -> Dict[str, Any]`

- [ ] **Step 1: 追加失败测试**

```python
class TestExport:
    def _run(self, tmp_path):
        from backend.literature.gates import run_gates
        from backend.literature.run_store import (
            create_run, record_papers, record_query, save_draft, save_outline,
        )
        run = create_run(tmp_path, "t", "demo", run_id="r1")
        record_query(run, "q", "demo", 2)
        record_papers(run, [_paper("p1"), _paper("p2")])
        save_outline(run, {"title": "x", "sections": [{"id": "s1", "title": "引言"}]})
        save_draft(run, "# 草稿\n\n发现 [cite:p1]。\n")
        run_gates(run)
        return run

    def test_export_writes_final_references_and_bibtex(self, tmp_path):
        from backend.literature.export import export_run
        paths = export_run(self._run(tmp_path))
        final = paths["final"].read_text(encoding="utf-8")
        assert "## 参考文献" in final
        assert "[1] 张三. 示例论文[J]. 示例期刊, 2024." in final
        assert "p2" not in paths["references"].read_text(encoding="utf-8")
        assert "@article{p1" in paths["bibtex"].read_text(encoding="utf-8")

    def test_export_fails_when_gate_fails(self, tmp_path):
        from backend.literature.export import export_run
        from backend.literature.run_store import save_draft
        run = self._run(tmp_path)
        save_draft(run, "坏引用 [cite:missing]")
        with pytest.raises(ValueError, match="门禁"):
            export_run(run)

    def test_handoff_has_references(self, tmp_path):
        from backend.literature.export import build_handoff
        data = build_handoff(self._run(tmp_path))
        assert data["references"][0]["key"] == "p1"
        assert data["references"][0]["ref_type"] == "journal"
```

- [ ] **Step 2: 实现 export**

Create `backend/literature/export.py`:

```python
"""把通过门禁的运行导出为 Markdown / BibTeX / paper-writing 交接数据。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence

from .gates import build_references, run_gates
from .models import PaperRecord
from .run_store import atomic_write_text, list_papers, read_draft, write_json


def _bibtex_entry(paper: PaperRecord) -> str:
    authors = " and ".join(paper.authors) if paper.authors else "佚名"
    fields = [
        f"  title = {{{paper.title}}}",
        f"  author = {{{authors}}}",
        f"  year = {{{paper.year or ''}}}",
    ]
    if paper.venue:
        fields.append(f"  journal = {{{paper.venue}}}")
    if paper.doi:
        fields.append(f"  doi = {{{paper.doi}}}")
    return "@article{" + paper.paper_key + ",\n" + ",\n".join(fields) + "\n}\n"


def build_bibtex(papers: Sequence[PaperRecord], cited_keys: Sequence[str]) -> str:
    by_key = {p.paper_key: p for p in papers}
    return "\n".join(
        _bibtex_entry(by_key[key]) for key in cited_keys if key in by_key
    )


def build_handoff(run) -> Dict[str, Any]:
    papers = list_papers(run)
    draft = read_draft(run)
    _, entries = build_references(draft, papers)
    references = []
    for entry in entries:
        paper = entry["paper"]
        references.append(
            {
                "key": entry["key"],
                "ref_type": "journal",
                "title": paper["title"],
                "authors": paper["authors"],
                "year": paper["year"] or "",
                "source": paper["venue"] or "",
                "doi": paper["doi"] or "",
            }
        )
    return {"references": references, "draft_path": str(run.run_dir / "draft.md")}


def export_run(run) -> Dict[str, Path]:
    report = run_gates(run)
    if not report.ok:
        raise ValueError("门禁未通过，无法导出: " + "; ".join(report.errors))

    papers = list_papers(run)
    draft = read_draft(run)
    references_md, entries = build_references(draft, papers)
    export_dir = run.run_dir / "export"
    final = draft.rstrip() + "\n\n## 参考文献\n\n" + references_md + "\n"
    final_path = export_dir / "final.md"
    refs_path = export_dir / "references.json"
    bib_path = export_dir / "papers.bib"
    atomic_write_text(final_path, final)
    write_json(refs_path, {"style": "gbt7714", "entries": entries})
    atomic_write_text(bib_path, build_bibtex(papers, report.citations))
    return {"final": final_path, "references": refs_path, "bibtex": bib_path}
```

- [ ] **Step 3: 测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
git add backend/literature/export.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): export markdown references and bibtex with handoff"
```

---

## Task 5: Profile 驱动浏览器执行器

**Files:**
- Create: `backend/literature/search.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`（追加）

**Interfaces:**
- Produces:
  - `BrowserDriver` Protocol（navigate/snapshot/click/current_url/current_title/wait_download）
  - `SearchObservation(url, page_url, page_title, guidance, snapshot)`
  - `search_with_profile(profile, query, driver, limit=10)`
  - `DownloadResult(path, ok, errors)`
  - `download_pdf(profile, driver, expected_title, dest_dir)`
  - `validate_pdf(path, expected_title, magic="%PDF-") -> List[str]`

- [ ] **Step 1: 追加失败测试**

```python
class _FakeDriver:
    def __init__(self):
        self.navigated = []
        self.clicks = []
        self.snapshot_text = "<tree>results</tree>"
        self.download_path = None

    def navigate(self, url, wait_for=""):
        self.navigated.append((url, wait_for))
        return "https://demo.example/home/1"

    def snapshot(self):
        return self.snapshot_text

    def click(self, target):
        self.clicks.append(target)

    def current_url(self):
        return "https://demo.example/home/1"

    def current_title(self):
        return "文献列表"

    def wait_download(self, timeout_s=60):
        return self.download_path


class TestBrowserSearch:
    def _profile(self):
        from backend.literature.models import profile_from_dict
        return profile_from_dict(_raw_profile())

    def test_search_navigates_and_returns_guidance(self):
        from backend.literature.search import search_with_profile
        driver = _FakeDriver()
        obs = search_with_profile(self._profile(), "机器学习", driver, limit=5)
        assert "demo.example/search" in obs.url
        assert obs.page_url.endswith("/home/1")
        assert "Demo 学术站" in obs.guidance
        assert driver.navigated[0][1] == ".result-list"

    def test_download_validates_pdf_and_title(self, tmp_path):
        from backend.literature.search import download_pdf
        driver = _FakeDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.4\nfake")
        driver.download_path = str(pdf)
        result = download_pdf(self._profile(), driver, "示例论文", tmp_path)
        assert result.ok is True, result.errors
        assert driver.clicks == ["a.downloadlink"]

    def test_download_rejects_bad_magic(self, tmp_path):
        from backend.literature.search import download_pdf
        driver = _FakeDriver()
        bad = tmp_path / "示例论文.pdf"
        bad.write_bytes(b"NOTPDF")
        driver.download_path = str(bad)
        result = download_pdf(self._profile(), driver, "示例论文", tmp_path)
        assert result.ok is False
        assert any("%PDF" in e for e in result.errors)
```

- [ ] **Step 2: 实现 search**

Create `backend/literature/search.py`:

```python
"""Profile 驱动的浏览器检索/下载执行器（不直接依赖 browser 工具）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Protocol

from .guidance import render_search_guidance
from .models import SiteProfile, render_search_url


class BrowserDriver(Protocol):
    def navigate(self, url: str, wait_for: str = "") -> str: ...
    def snapshot(self) -> str: ...
    def click(self, target: str) -> None: ...
    def current_url(self) -> str: ...
    def current_title(self) -> str: ...
    def wait_download(self, timeout_s: float = 60) -> Optional[str]: ...


@dataclass(frozen=True)
class SearchObservation:
    url: str
    page_url: str
    page_title: str
    guidance: str
    snapshot: str


def search_with_profile(
    profile: SiteProfile, query: str, driver: BrowserDriver, limit: int = 10
) -> SearchObservation:
    url = render_search_url(profile, query, limit=limit)
    wait_for = ", ".join(profile.search.wait_for)
    page_url = driver.navigate(url, wait_for=wait_for)
    snapshot = driver.snapshot()
    guidance = render_search_guidance(
        profile,
        query,
        limit=limit,
        page_url=driver.current_url() or page_url,
        page_title=driver.current_title(),
    )
    return SearchObservation(url, page_url, driver.current_title(), guidance, snapshot)


@dataclass
class DownloadResult:
    path: Optional[str]
    ok: bool
    errors: List[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")


def validate_pdf(path: Path, expected_title: str, magic: str = "%PDF-") -> List[str]:
    errors: List[str] = []
    if not path.is_file():
        return [f"下载文件不存在: {path}"]
    with path.open("rb") as handle:
        head = handle.read(len(magic))
    if head != magic.encode("ascii"):
        errors.append(f"文件头不是 {magic}")
    if expected_title:
        expected = _normalize(expected_title)
        actual = _normalize(path.stem)
        if expected and expected not in actual and actual not in expected:
            errors.append(f"文件名与题名不匹配: {path.name!r} vs {expected_title!r}")
    return errors


def download_pdf(
    profile: SiteProfile,
    driver: BrowserDriver,
    expected_title: str,
    dest_dir: Path,
    timeout_s: float = 60,
) -> DownloadResult:
    if profile.pdf is None:
        return DownloadResult(None, False, ["站点未配置 pdf 下载"])
    target = profile.pdf.entry_selector or profile.pdf.entry_text
    if not target:
        return DownloadResult(None, False, ["站点未配置 PDF 入口"])
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    driver.click(target)
    downloaded = driver.wait_download(timeout_s=timeout_s)
    if not downloaded:
        return DownloadResult(None, False, ["等待下载超时"])
    path = Path(downloaded)
    errors = validate_pdf(path, expected_title, profile.pdf.magic)
    if profile.pdf.forbid:
        for word in profile.pdf.forbid:
            if word.lower() in path.suffix.lower():
                errors.append(f"禁止的下载格式: {word}")
    return DownloadResult(str(path), not errors, errors)
```

- [ ] **Step 3: 测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
git add backend/literature/search.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): add profile-driven browser search/download executor"
```

---

## Task 6: 录制模式（观测 → draft profile）

**Files:**
- Create: `backend/literature/recording.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`（追加）

**Interfaces:**
- Produces:
  - `profile_draft_from_observation(raw: Dict[str, Any]) -> str`
  - `write_profile_draft(raw, out_path) -> SiteProfile`

- [ ] **Step 1: 追加失败测试**

```python
class TestRecording:
    def test_observation_becomes_valid_draft_profile(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore
        from backend.literature.recording import write_profile_draft

        raw = {
            "id": "xueshu789",
            "display_name": "学术资源站",
            "home_url": "https://www.xueshu789.cc/",
            "domains": ["xueshu789.cc"],
            "access": {
                "mode": "browser",
                "login": {
                    "method": "form",
                    "account_label": "您的卡号",
                    "password_label": "您的密码",
                    "url_contains": "/dbList/",
                    "title_not_contains": "登录",
                },
            },
            "search": {
                "url_template": "https://www.xueshu789.cc/dbItem/1?kw={query}",
                "wait_for": [".result-list"],
                "result_fields": {"title": {"selector": ".title"}},
            },
            "pdf": {"entry": {"selector": "a.downloadlink"}},
        }
        out_dir = tmp_path / "sites"
        out_dir.mkdir()
        out_path = out_dir / "xueshu789.yaml"
        profile = write_profile_draft(raw, out_path)
        assert profile.status == "draft"
        assert profile.last_verified_at is not None
        store = SiteProfileStore([ProfileRoot(out_dir, "user")])
        assert store.get("xueshu789").search.wait_for == (".result-list",)
```

- [ ] **Step 2: 实现 recording**

Create `backend/literature/recording.py`:

```python
"""把人工/agent 观测到的页面事实写成 draft profile YAML。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

from .models import SiteProfile, profile_from_dict
from .run_store import atomic_write_text


def profile_draft_from_observation(raw: Dict[str, Any]) -> str:
    data = copy.deepcopy(raw)
    data.setdefault("status", "draft")
    data.setdefault("version", "0.1.0")
    data.setdefault(
        "last_verified_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    data.setdefault("compliance", {"note": "仅本人账号/机构授权", "default_enabled": False})
    profile_from_dict(data)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write_profile_draft(raw: Dict[str, Any], out_path: Path) -> SiteProfile:
    data = copy.deepcopy(raw)
    data.setdefault("status", "draft")
    data.setdefault("version", "0.1.0")
    data.setdefault(
        "last_verified_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    data.setdefault("compliance", {"note": "仅本人账号/机构授权", "default_enabled": False})
    profile = profile_from_dict(data)
    atomic_write_text(Path(out_path), yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return profile
```

- [ ] **Step 3: 测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
git add backend/literature/recording.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): record observed site facts as draft profile yaml"
```

---

## Task 7: CLI 与 shipped skill

**Files:**
- Create: `backend/literature/cli.py`
- Create: `backend/skills/skill_md/shipped/literature-research/SKILL.md`
- Create: `backend/skills/skill_md/shipped/literature-research/references/pipeline.md`
- Test: `backend/tests/unit/test_literature_pipeline.py`（追加 CLI 测试）

**Interfaces:**
- Produces: `python -m backend.literature.cli <command>`；退出码 0/1；stdout JSON。
- Skill 通过 `execute_code` 调用模块（不依赖 cwd），CLI 作为本地/脚本入口。

- [ ] **Step 1: 追加 CLI 测试**

```python
class TestCli:
    def test_init_record_gate_export_flow(self, tmp_path):
        from backend.literature import cli
        root = tmp_path / "runs"
        assert cli.main(["init", "--root", str(root), "--topic", "t", "--site", "demo", "--run-id", "r1"]) == 0
        run_dir = root / "r1"

        papers = tmp_path / "papers.json"
        papers.write_text(json.dumps([_paper("p1")]), encoding="utf-8")
        assert cli.main(["record-query", "--run", str(run_dir), "--query", "q", "--site", "demo", "--result-count", "1"]) == 0
        assert cli.main(["record-papers", "--run", str(run_dir), "--json", str(papers)]) == 0

        outline = tmp_path / "outline.json"
        outline.write_text(json.dumps({"title": "x", "sections": [{"id": "s1", "title": "引言"}]}), encoding="utf-8")
        assert cli.main(["save-outline", "--run", str(run_dir), "--json", str(outline)]) == 0

        draft = tmp_path / "draft.md"
        draft.write_text("# 草稿\n\n发现 [cite:p1]。\n", encoding="utf-8")
        assert cli.main(["save-draft", "--run", str(run_dir), "--md", str(draft)]) == 0

        assert cli.main(["gate", "--run", str(run_dir)]) == 0
        assert cli.main(["export", "--run", str(run_dir)]) == 0
        assert (run_dir / "export" / "final.md").is_file()

    def test_gate_failure_exit_code(self, tmp_path):
        from backend.literature import cli
        root = tmp_path / "runs"
        cli.main(["init", "--root", str(root), "--topic", "t", "--site", "demo", "--run-id", "r1"])
        assert cli.main(["gate", "--run", str(root / "r1")]) == 1
```

- [ ] **Step 2: 实现 CLI**

Create `backend/literature/cli.py`，至少包含：
- `_read_text(path)` / `_read_json(path)`（`-` = stdin）
- `_print(data)`（JSON, ensure_ascii=False）
- 子命令：init / guidance / record-query / record-papers / record-evidence / save-outline / save-draft / gate / export / status / validate-profile / draft-profile
- `main(argv=None) -> int`；argparse 错误返回 2。
- `guidance` 命令使用 `get_default_store().get(site)` 与 `render_search_guidance`。
- `draft-profile` 命令读取观测 JSON，调用 `write_profile_draft`。

- [ ] **Step 3: 写 skill**

Create `SKILL.md` frontmatter：

```yaml
---
name: literature-research
description: 文献调研与综述最小闭环——选站点、检索、筛选、证据表、大纲、分节写作、引用门禁与导出，并交接给 paper-writing 生成 docx。
license: Apache-2.0
compatibility: 需要 browser_*、execute_code、write_file/read_file、office_create/office_parse_bibtex
when_to_use: 当用户要做文献调研、写文献综述、literature review、或"找资料并整理成综述"时使用；单纯写论文正文请用 paper-writing
allowed-tools: browser_launch browser_navigate browser_snapshot browser_interact browser_downloads browser_login ask_user_question execute_code bash write_file read_file office_parse_bibtex office_create office_lint_word
triggers: []
---
```

Body steps（中文），包含：
1. 范围确认（ask_user_question）。
2. 站点选择与登录（profile 列表：xueshu789/CNKI；合规提示）。
3. 初始化运行目录（execute_code 调 `create_run`）。
4. 检索（execute_code 调 `render_search_guidance` → browser_navigate/snapshot → LLM 解析 JSON → `record_papers` + `record_query`）。
5. 筛选与证据（LLM 生成 evidence JSON → `record_evidence`）。
6. 大纲（`save_outline`）。
7. 分节写作（write_file → `save_draft`，只用 `[cite:KEY]`）。
8. 门禁（`run_gates`；修复后重跑）。
9. 导出（`export_run`；`build_handoff` 交给 paper-writing）。
10. 边界（不编造、不绕过付费墙、验证码交还用户）。

`references/pipeline.md`：运行目录契约、JSON schema、引用语法、门禁语义、xueshu789 现状（draft 选择器待录制）。

- [ ] **Step 4: 测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py backend/tests/unit/test_shipped_writing_skills.py backend/tests/unit/test_skill_md_loader.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
git add backend/literature/cli.py backend/skills/skill_md/shipped/literature-research backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): add CLI and literature-research shipped skill"
```

---

## Task 8: 端到端测试、文档与收尾

**Files:**
- Test: `backend/tests/unit/test_literature_pipeline.py`（端到端）
- Modify: `docs/plans/2026-11-21_literature-research-paper-pipeline.md`
- Modify: `docs/plans/2026-11-21_literature-research-m1-implementation.md`（勾选）

- [ ] **Step 1: 端到端合成测试**

追加：

```python
class TestEndToEnd:
    def test_synthetic_survey_flow(self, tmp_path):
        from backend.literature.export import export_run
        from backend.literature.gates import run_gates
        from backend.literature.run_store import (
            create_run, record_evidence, record_papers, record_query,
            save_draft, save_outline,
        )
        run = create_run(tmp_path, "合成综述", "demo", run_id="e2e")
        record_query(run, "合成", "demo", 3)
        record_papers(run, [_paper("p1"), _paper("p2"), _paper("p3")])
        record_evidence(run, [
            {"evidence_id": "e1", "paper_key": "p1", "kind": "finding", "text": "A"},
            {"evidence_id": "e2", "paper_key": "p2", "kind": "method", "text": "B"},
        ])
        save_outline(run, {"title": "合成综述", "sections": [
            {"id": "s1", "title": "背景", "source_keys": ["p1"]},
            {"id": "s2", "title": "方法", "source_keys": ["p2"]},
        ]})
        save_draft(run, "# 合成综述\n\n背景 [cite:p1]。\n\n方法 [cite:p2]。\n")
        report = run_gates(run)
        assert report.ok is True
        assert any("p3" in w for w in report.warnings)
        paths = export_run(run)
        assert paths["final"].is_file()
        assert paths["bibtex"].is_file()
```

- [ ] **Step 2: 全量目标测试 + 门禁**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_pipeline.py \
  backend/tests/unit/test_literature_site_profiles.py \
  backend/tests/unit/test_academic_adapters.py \
  backend/tests/unit/test_academic_search.py \
  backend/tests/unit/test_shipped_writing_skills.py \
  backend/tests/unit/test_skill_md_loader.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/skills/skill_md/shipped/literature-research backend/tests/unit/test_literature_pipeline.py
/home/fz/anaconda3/envs/sage-backend/bin/python scripts/check_py38_compat.py backend/literature
```

- [ ] **Step 3: 更新设计文档 M1 勾选**

在 `docs/plans/2026-11-21_literature-research-paper-pipeline.md` 的 M1 中标记：
- `[x]` 新增 `literature-research` shipped skill
- `[x]` 实现 scoping → search → screen → evidence → outline → draft → verify（存在性）→ export(Markdown) 的确定性骨架
- `[x]` 硬门禁：schema 校验、引用 key 解析、检索日志完整性、参考文献只列已引用
- `[ ]` 接入编排 lanes、阶段事件、运行目录恢复（M1b）
- `[ ]` 与 paper-writing 的 docx 交接实跑（M1b）
- `[x]` 端到端合成测试（非真实网络）

- [ ] **Step 4: 最终提交**

```bash
git add docs/plans/2026-11-21_literature-research-paper-pipeline.md docs/plans/2026-11-21_literature-research-m1-implementation.md backend/tests/unit/test_literature_pipeline.py
git commit -m "test(literature): add end-to-end synthetic survey flow and docs"
git log --oneline -8
```

---

## Self-Review

**Spec coverage**
- 运行目录 + 文件契约：Task 2。
- 确定性门禁（schema / 引用 / 检索日志 / 参考文献只列已引用）：Task 3。
- Markdown/BibTeX 导出与 paper-writing 交接：Task 4。
- Profile 驱动浏览器检索/下载（可假驱动测试）：Task 5。
- 录制模式（观测 → draft profile）：Task 6。
- `literature-research` skill：Task 7。
- 端到端合成测试：Task 8。
- 未覆盖（明确留 M1b/M2）：通用 Workflow v1.1 执行器、chat 工具、真实 xueshu789 登录/检索/下载验收、claim-support 核验、SQLite PaperDB。

**Placeholder scan**
- 所有代码步骤均给出接口与关键实现；`cli.py` 的子命令列表明确，按现有 run_store/gates/export API 实现。

**Type consistency**
- `LiteratureRun` / `PaperRecord` / `EvidenceRecord` / `Outline` / `GateReport` 命名一致。
- `record_papers` / `record_evidence` 返回新增条数；`save_outline` 返回 `Outline`；`run_gates` 返回 `GateReport`；`export_run` 返回路径字典。
