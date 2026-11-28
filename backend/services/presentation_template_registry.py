"""PresentationTemplateRegistry — ppt-master 内置模板库索引。

扫描技能目录下的四类模板（brand / style / layout / deck），把元数据落到
SQLite（``presentation_templates`` 表，见 migrations/v23），供管理 API 列表、
前端选择器使用，并在渲染前把选中的模板 workspace 解析成绝对路径交给
``apply_template.py`` 安装。

扫描来源（后者覆盖前者）：

    templates/<kind_dir>/<kind_dir>_index.json        内置库
    templates/local/<kind_dir>/<kind_dir>_index.json  用户本地库（可缺省）

索引与 spec frontmatter 都没有 ``name`` 字段，展示名直接用 template_id。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import yaml

from backend.data.database import get_database
from backend.services.ppt_master_adapter import _resolve_skill_root
from backend.services.presentation_service import PresentationInputError

__all__ = [
    "TemplateEntry",
    "PresentationTemplateRegistry",
    "TEMPLATE_KINDS",
]

logger = logging.getLogger(__name__)

#: 模板种类 -> 技能目录名（templates/<dir>/）。
KIND_DIRS: Dict[str, str] = {
    "brand": "brands",
    "style": "styles",
    "layout": "layouts",
    "deck": "decks",
}
TEMPLATE_KINDS: Tuple[str, ...] = ("brand", "style", "layout", "deck")

_SELECT_COLUMNS = (
    "kind, template_id, name, summary, primary_color, canvas_format, "
    "page_count, page_types, root_path"
)
_INSERT_SQL = (
    "INSERT INTO presentation_templates ("
    "kind, template_id, name, summary, primary_color, canvas_format, "
    "page_count, page_types, root_path, updated_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(frozen=True)
class TemplateEntry:
    """一个模板库条目的元数据（root_path 为模板 workspace 绝对路径）。"""

    kind: str
    template_id: str
    name: str
    summary: str
    primary_color: Optional[str]
    canvas_format: Optional[str]
    page_count: Optional[int]
    page_types: Tuple[str, ...]
    root_path: str


def _default_conn() -> Any:
    return get_database().get_connection()


class PresentationTemplateRegistry:
    """模板库索引：扫描 / 查询 / 解析安装根路径。"""

    def __init__(
        self,
        conn_factory: Optional[Callable[[], Any]] = None,
        skill_root: Optional[Path] = None,
    ) -> None:
        self._conn_factory = conn_factory or _default_conn
        self._skill_root: Optional[Path] = Path(skill_root) if skill_root else None

    @property
    def skill_root(self) -> Path:
        if self._skill_root is None:
            self._skill_root = _resolve_skill_root(None)
        return self._skill_root

    # ------------------------------------------------------------------ #
    # 扫描 / 刷新
    # ------------------------------------------------------------------ #
    def refresh(self) -> int:
        """全量重扫技能模板目录并重写索引，返回条目数。"""
        entries = self._scan()
        now = datetime.now(timezone.utc).isoformat()  # noqa: UP017 — py3.8 无 datetime.UTC
        rows = [
            (
                entry.kind,
                entry.template_id,
                entry.name,
                entry.summary,
                entry.primary_color,
                entry.canvas_format,
                entry.page_count,
                json.dumps(list(entry.page_types), ensure_ascii=False),
                entry.root_path,
                now,
            )
            for entry in entries
        ]
        conn = self._conn_factory()
        try:
            conn.execute("DELETE FROM presentation_templates")
            conn.executemany(_INSERT_SQL, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        logger.info("模板库索引已刷新：%d 条", len(rows))
        return len(rows)

    def ensure_fresh(self) -> None:
        """空表时惰性扫描一次（技能目录更新后由用户手动刷新）。"""
        conn = self._conn_factory()
        row = conn.execute("SELECT COUNT(*) FROM presentation_templates").fetchone()
        count = int(row[0]) if row is not None else 0
        if count == 0:
            self.refresh()

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def list_templates(self, kind: Optional[str] = None) -> List[TemplateEntry]:
        if kind is not None:
            _require_kind(kind)
        query = f"SELECT {_SELECT_COLUMNS} FROM presentation_templates"
        params: Tuple[Any, ...] = ()
        if kind is not None:
            query += " WHERE kind = ?"
            params = (kind,)
        query += " ORDER BY kind, template_id"
        conn = self._conn_factory()
        rows = conn.execute(query, params).fetchall()
        return [_row_to_entry(row) for row in rows]

    def resolve_roots(self, template_ids: Sequence[str]) -> List[Path]:
        """把 ``kind:id`` 选择解析成模板 workspace 绝对路径列表。

        拒绝：格式非法、未知模板、同类多选、目录已被删除。只接受库内条目
        标识，不接受客户端传任意路径。
        """
        if not template_ids:
            return []
        conn = self._conn_factory()
        roots: List[Path] = []
        seen_kinds: List[str] = []
        for raw in template_ids:
            kind, sep, template_id = str(raw).partition(":")
            if not sep or not kind or not template_id:
                raise PresentationInputError(f"模板标识非法：{raw}（应形如 kind:id）")
            _require_kind(kind, raw)
            if kind in seen_kinds:
                raise PresentationInputError(f"同一类模板最多选择一个：{kind}")
            row = conn.execute(
                "SELECT root_path FROM presentation_templates "
                "WHERE kind = ? AND template_id = ?",
                (kind, template_id),
            ).fetchone()
            if row is None:
                raise PresentationInputError(f"未知模板：{raw}")
            root = Path(row[0])
            if not root.is_dir():
                raise PresentationInputError(f"模板目录已不存在：{raw}")
            roots.append(root)
            seen_kinds.append(kind)
        return roots

    # ------------------------------------------------------------------ #
    # 内部扫描
    # ------------------------------------------------------------------ #
    def _scan(self) -> List[TemplateEntry]:
        templates_root = self.skill_root / "templates"
        merged: Dict[Tuple[str, str], TemplateEntry] = {}
        for kind in TEMPLATE_KINDS:
            dir_name = KIND_DIRS[kind]
            for base in (templates_root / dir_name, templates_root / "local" / dir_name):
                for entry in _scan_kind_dir(kind, dir_name, base):
                    merged[(kind, entry.template_id)] = entry
        return list(merged.values())


def _scan_kind_dir(kind: str, dir_name: str, base: Path) -> List[TemplateEntry]:
    index_path = base / f"{dir_name}_index.json"
    if not index_path.is_file():
        return []
    index = _load_json_dict(index_path)
    if index is None:
        logger.warning("模板索引不可解析，跳过：%s", index_path)
        return []

    entries: List[TemplateEntry] = []
    for template_id, raw_meta in index.items():
        if not isinstance(template_id, str) or not template_id:
            continue
        root = base / template_id
        spec_path = root / "templates" / "design_spec.md"
        if not spec_path.is_file():
            logger.warning("跳过模板 %s:%s（缺少 %s）", kind, template_id, spec_path)
            continue
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        front = _read_frontmatter(spec_path)
        entries.append(
            TemplateEntry(
                kind=kind,
                template_id=template_id,
                name=template_id,
                summary=_first_str(meta.get("summary"), front.get("summary")),
                primary_color=_opt_str(meta.get("primary_color") or front.get("primary_color")),
                canvas_format=_opt_str(meta.get("canvas_format") or front.get("canvas_format")),
                page_count=_opt_int(meta.get("page_count") or front.get("page_count")),
                page_types=tuple(_str_list(meta.get("page_types") or front.get("page_types"))),
                root_path=str(root.resolve()),
            )
        )
    return entries


def _require_kind(kind: str, raw: Optional[str] = None) -> None:
    if kind not in KIND_DIRS:
        label = f"（来自 {raw}）" if raw is not None else ""
        raise PresentationInputError(
            f"未知模板种类：{kind}{label}；可选 {'/'.join(TEMPLATE_KINDS)}"
        )


def _row_to_entry(row: Any) -> TemplateEntry:
    return TemplateEntry(
        kind=row[0],
        template_id=row[1],
        name=row[2],
        summary=row[3] or "",
        primary_color=row[4],
        canvas_format=row[5],
        page_count=row[6],
        page_types=tuple(_decode_page_types(row[7])),
        root_path=row[8],
    )


def _decode_page_types(raw: Any) -> List[str]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return _str_list(value)


def _load_json_dict(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_frontmatter(path: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _opt_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.strip() else None


def _opt_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):  # noqa: UP038 — py3.8 不支持 X | Y 形式
        return []
    return [str(item) for item in value if str(item).strip()]


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return ""
