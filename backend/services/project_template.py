"""项目模板系统（P1 of 2026-11-05 项目管理增强设计）。

提供通用的项目结构模板，支持三个来源按优先级加载：

    ① 内置模板（由现有 ``ARCHETYPE_BLUEPRINTS`` 泛化生成）
    ② 全局用户库（``~/.sage/templates/*.json``）
    ③ 项目内自描述（``<project>/.sage/template.json``）

优先级：项目内 > 全局库 > 内置。

模板是**纯 JSON 文件**，不存入数据库，因此可以随项目一起 git 管理、
在团队间共享。

模板的两个应用入口：

- **新建项目时选模板** → 完整生成目录结构 + 初始文件 + ``.sage/template.json``
- **现有项目套用模板** → 只补齐**缺失**的目录/文件（``overwrite: false``）

设计要点：

- 每个目录可声明 ``role: "project" | "folder"``。``role == "project"`` 的
  目录会被后续 ``workspace_scanner``（P2）识别为子项目。
- 模板变量仅支持白名单（``{{project_name}}`` / ``{{date}}`` /
  ``{{datetime}}`` / ``{{user}}``），不引入表达式引擎，杜绝代码注入。
- 文件生成幂等：``overwrite: false``（默认）时不覆盖已存在文件；``true``
  时强制覆盖（模板作者显式承担风险）。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TemplateDirectory:
    """模板中的单个目录声明。

    Attributes:
        path: 相对于项目根的路径，用 ``/`` 分隔（写入时按系统路径分隔符处理）。
        desc: 人类可读的描述，写入 ``SAGE.md`` 或 UI 展示。
        role: ``"project"`` 表示子项目（P2 扫描器识别）；``"folder"`` 为普通目录。
    """

    path: str
    desc: str = ""
    role: str = "folder"

    def __post_init__(self) -> None:
        if not self.path or ".." in Path(self.path).parts:
            raise ValueError(f"TemplateDirectory.path is unsafe: {self.path!r}")
        if self.role not in ("project", "folder"):
            raise ValueError(
                f"TemplateDirectory.role must be 'project' or 'folder', got {self.role!r}"
            )


@dataclass(frozen=True)
class TemplateFile:
    """模板中的单个文件声明。

    Attributes:
        path: 相对于项目根的路径。
        content: 文件内容（可含模板变量 ``{{name}}``）。
        template: 内置内容模板名（与 ``content`` 二选一）。``"$SELF"`` 表示写入
                  模板自身内容（项目内 ``.sage/template.json`` 的特殊值）。
        overwrite: 目标已存在时是否覆盖。默认 ``False``（幂等补齐）。
    """

    path: str
    content: str = ""
    template: Optional[str] = None
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not self.path or ".." in Path(self.path).parts:
            raise ValueError(f"TemplateFile.path is unsafe: {self.path!r}")
        if self.content and self.template is not None:
            raise ValueError(
                "TemplateFile: 'content' and 'template' are mutually exclusive"
            )


@dataclass(frozen=True)
class ProjectTemplate:
    """项目模板定义。

    Attributes:
        name: 模板显示名（如 "CFD 计算项目"、"代码工程"）。
        description: 一句话说明模板用途。
        version: 模板版本（整数，便于未来迁移）。
        directories: 模板声明的目录列表。
        files: 模板声明的文件列表。
        built_in: 是否为内置模板（内置模板 ``source == "built_in"``）。
        source: 来源标识，``"built_in"`` / ``"global"`` / ``"project"``。
    """

    name: str
    description: str = ""
    version: int = 1
    directories: List[TemplateDirectory] = field(default_factory=list)
    files: List[TemplateFile] = field(default_factory=list)
    built_in: bool = False
    source: str = "built_in"

    # ── 序列化 ────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """转为 JSON-serializable dict（不含 ``built_in`` / ``source`` 元信息）。"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "directories": [
                {"path": d.path, "desc": d.desc, "role": d.role} for d in self.directories
            ],
            "files": [
                {
                    "path": f.path,
                    "content": f.content,
                    "template": f.template,
                    "overwrite": f.overwrite,
                }
                for f in self.files
            ],
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        built_in: bool = False,
        source: str = "built_in",
    ) -> "ProjectTemplate":
        """从 dict 构造模板。

        宽容解析：缺失的可选字段使用默认值，多余字段忽略。
        """
        dirs_raw = data.get("directories") or []
        files_raw = data.get("files") or []
        dirs: List[TemplateDirectory] = []
        for d in dirs_raw:
            if isinstance(d, dict) and "path" in d:
                dirs.append(
                    TemplateDirectory(
                        path=d["path"],
                        desc=d.get("desc", ""),
                        role=d.get("role", "folder"),
                    )
                )
        files: List[TemplateFile] = []
        for f in files_raw:
            if isinstance(f, dict) and "path" in f:
                files.append(
                    TemplateFile(
                        path=f["path"],
                        content=f.get("content", ""),
                        template=f.get("template"),
                        overwrite=bool(f.get("overwrite", False)),
                    )
                )
        return cls(
            name=data.get("name") or "Untitled",
            description=data.get("description", ""),
            version=int(data.get("version", 1)),
            directories=dirs,
            files=files,
            built_in=built_in,
            source=source,
        )

    @classmethod
    def from_json(
        cls,
        text: str,
        *,
        built_in: bool = False,
        source: str = "built_in",
    ) -> "ProjectTemplate":
        """从 JSON 字符串加载模板（失败抛 ``ValueError``）。"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid template JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Template JSON root must be an object")
        return cls.from_dict(data, built_in=built_in, source=source)

    # ── 变量替换 ───────────────────────────────────────────────────

    def render_content(self, raw: str, project_name: str) -> str:
        """把模板内容中的白名单变量替换为实际值。

        白名单（不引入表达式引擎，杜绝注入）：

        - ``{{project_name}}``：项目名（来自参数）
        - ``{{date}}``：当日日期（YYYY-MM-DD）
        - ``{{datetime}}``：当前日期时间（YYYY-MM-DD HH:MM:SS）
        - ``{{user}}``：当前系统用户名（``getpass.getuser()``，失败回退 ``"user"``）
        """
        now = datetime.now()
        replacements = {
            "{{project_name}}": project_name,
            "{{date}}": now.strftime("%Y-%m-%d"),
            "{{datetime}}": now.strftime("%Y-%m-%d %H:%M:%S"),
            "{{user}}": _get_user(),
        }
        result = raw
        for key, value in replacements.items():
            result = result.replace(key, value)
        return result


def _get_user() -> str:
    """返回当前系统用户名；取不到时回退 ``"user"``（容错）。"""
    try:
        import getpass

        return getpass.getuser() or "user"
    except Exception:  # noqa: BLE001
        return "user"


# ─────────────────────────────────────────────────────────────────────
# 加载：三来源
# ─────────────────────────────────────────────────────────────────────


#: 全局模板库位置（XDG 兼容，简化为 ~/.sage/templates）。
GLOBAL_TEMPLATE_DIR = Path.home() / ".sage" / "templates"


def load_global_templates() -> List[ProjectTemplate]:
    """从 ``~/.sage/templates/*.json`` 加载全局用户模板。

    失败的文件（JSON 语法错误、字段缺失）被跳过并 log 警告；不会抛异常。
    目录不存在时返回空列表。
    """
    if not GLOBAL_TEMPLATE_DIR.is_dir():
        return []
    templates: List[ProjectTemplate] = []
    for path in sorted(GLOBAL_TEMPLATE_DIR.glob("*.json")):
        if not path.is_file():
            continue
        try:
            tpl = ProjectTemplate.from_json(path.read_text(encoding="utf-8"), source="global")
            templates.append(tpl)
        except (ValueError, OSError) as exc:
            logger.warning("Skipping invalid global template %s: %s", path, exc)
    return templates


def load_project_template(project_root: Path) -> Optional[ProjectTemplate]:
    """从项目内 ``<project>/.sage/template.json`` 加载模板。

    不存在或解析失败返回 ``None``（调用方按"无项目级模板"处理）。
    """
    path = Path(project_root) / ".sage" / "template.json"
    if not path.is_file():
        return None
    try:
        return ProjectTemplate.from_json(path.read_text(encoding="utf-8"), source="project")
    except (ValueError, OSError) as exc:
        logger.warning("Project template at %s is invalid: %s", path, exc)
        return None


def save_project_template(project_root: Path, template: ProjectTemplate) -> Path:
    """把模板写入项目内 ``.sage/template.json``（项目自描述）。

    目录不存在自动创建；返回写入路径。
    """
    target = Path(project_root) / ".sage" / "template.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(template.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


# ─────────────────────────────────────────────────────────────────────
# 内置模板：泛化自 ARCHETYPE_BLUEPRINTS
# ─────────────────────────────────────────────────────────────────────


def _blueprint_to_template(blueprint: Any) -> ProjectTemplate:
    """把 ``ArchetypeBlueprint``（既有数据模型）转换为 ``ProjectTemplate``。

    转换规则：

    - ``blueprint.directories`` 的每一项 → ``TemplateDirectory(role="folder")``
    - ``blueprint.sage_md_template`` → ``TemplateFile(path="SAGE.md", template="sage_md")``
    - coding 类型额外生成 ``.sage/hooks.json`` 默认内容

    保持 ``ARCHETYPE_BLUEPRINTS`` 原样不动（向后兼容），只在模板系统入口处
    做一次性转换。
    """
    dirs = [TemplateDirectory(path=p, desc="", role="folder") for p in blueprint.directories]
    files: List[TemplateFile] = []
    if blueprint.sage_md_template:
        files.append(
            TemplateFile(path="SAGE.md", content=blueprint.sage_md_template, overwrite=False)
        )
    # coding 类型的默认 hooks 配置
    if blueprint.project_type == "coding":
        files.append(
            TemplateFile(
                path=".sage/hooks.json",
                content='{\n  "hooks": []\n}\n',
                overwrite=False,
            )
        )
    return ProjectTemplate(
        name=blueprint.label_zh,
        description=f"Built-in: {blueprint.label_en}",
        version=1,
        directories=dirs,
        files=files,
        built_in=True,
        source="built_in",
    )


def get_built_in_templates() -> Dict[str, ProjectTemplate]:
    """返回所有内置模板（键 = project_type）。

    每次调用都重新构造（开销极小），这样 ``ARCHETYPE_BLUEPRINTS`` 的任何运行时
    修改都能被反映（测试/扩展场景）。
    """
    from backend.services.project_archetype_scaffold import ARCHETYPE_BLUEPRINTS

    return {
        project_type: _blueprint_to_template(bp)
        for project_type, bp in ARCHETYPE_BLUEPRINTS.items()
    }


def resolve_template(
    project_type: Optional[str],
    project_root: Optional[Path] = None,
    template_name: Optional[str] = None,
) -> ProjectTemplate:
    """解析最终生效的模板（按优先级：项目内 > 全局 > 内置）。

    Args:
        project_type: 项目类型（``"coding"`` / ``"research"`` 等），用于回退内置模板。
        project_root: 项目根目录，用于加载项目内模板（缺失则跳过该层）。
        template_name: 用户显式指定的全局模板名（优先级高于内置）。

    优先级顺序（高 → 低）：

    1. 项目内 ``.sage/template.json``（最强约束：项目已声明结构）
    2. 用户指定的 ``template_name``（全局库匹配）
    3. 按 ``project_type`` 查找内置模板
    4. 兜底 ``business`` 内置模板（最小假设）
    """
    # ① 项目内
    if project_root is not None:
        project_tpl = load_project_template(Path(project_root))
        if project_tpl is not None:
            return project_tpl

    # ② 用户指定
    if template_name:
        for tpl in load_global_templates():
            if tpl.name == template_name:
                return tpl

    # ③ 按 project_type 查内置
    built_in = get_built_in_templates()
    key = (project_type or "").strip().lower()
    if key and key in built_in:
        return built_in[key]

    # ④ 兜底
    return built_in.get("business") or next(iter(built_in.values()))


# ─────────────────────────────────────────────────────────────────────
# 脚手架执行
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ScaffoldResult:
    """模板脚手架执行结果。

    Attributes:
        template_name: 实际使用的模板名。
        created_directories: 本次新建的目录相对路径列表。
        created_files: 本次新建的文件相对路径列表。
        skipped_directories: 已存在故跳过的目录。
        skipped_files: 因 ``overwrite=False`` 跳过的文件。
        dry_run: 是否为试运行（未实际写入）。
    """

    template_name: str
    created_directories: List[str] = field(default_factory=list)
    created_files: List[str] = field(default_factory=list)
    skipped_directories: List[str] = field(default_factory=list)
    skipped_files: List[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_name": self.template_name,
            "created_directories": list(self.created_directories),
            "created_files": list(self.created_files),
            "skipped_directories": list(self.skipped_directories),
            "skipped_files": list(self.skipped_files),
            "dry_run": self.dry_run,
        }


# 路径中的危险模式：``..`` 段、绝对路径、符号链接（resolve 后逃出项目根）
_PATH_ESCAPE_RE = re.compile(r"(^|/)\.\.(/|$)")


def _is_safe_relative(rel_path: str) -> bool:
    """判断相对路径不含路径逃逸（``..`` 段 / 绝对路径）。"""
    if not rel_path or _PATH_ESCAPE_RE.search(rel_path):
        return False
    if os.path.isabs(rel_path):
        return False
    return True


def scaffold_project(
    template: ProjectTemplate,
    project_root: Path,
    project_name: str,
    *,
    dry_run: bool = False,
    write_project_template: bool = True,
) -> ScaffoldResult:
    """按模板在项目根目录下创建目录结构并生成初始文件。

    执行规则：

    - 目录：不存在则创建；已存在则跳过（计入 ``skipped_directories``）。
    - 文件：``overwrite=False`` 时存在即跳过；``overwrite=True`` 强制覆盖。
    - 文件内容中的模板变量（``{{project_name}}`` 等）会被替换。
    - ``dry_run=True`` 时只计算结果不实际写入，可用于前端预览。

    Args:
        template: 要执行的模板。
        project_root: 项目根目录（必须存在；不存在由调用方先 ``mkdir``）。
        project_name: 用于模板变量替换的项目名。
        dry_run: 试运行模式（不写入）。
        write_project_template: 是否把模板本身写入 ``.sage/template.json``
            （让项目具备自描述能力；默认 True，但已有同名文件时不覆盖）。

    Returns:
        执行结果（含新建 / 跳过的目录文件列表）。

    Raises:
        ValueError: ``project_root`` 不存在或不安全路径。
    """
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError(f"project_root does not exist: {root}")

    result = ScaffoldResult(template_name=template.name, dry_run=dry_run)

    # 创建目录
    for dir_spec in template.directories:
        if not _is_safe_relative(dir_spec.path):
            logger.warning("Skipping unsafe directory: %r", dir_spec.path)
            continue
        target = root / dir_spec.path
        if target.exists():
            result.skipped_directories.append(dir_spec.path)
            continue
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
        result.created_directories.append(dir_spec.path)

    # 创建文件
    for file_spec in template.files:
        if not _is_safe_relative(file_spec.path):
            logger.warning("Skipping unsafe file: %r", file_spec.path)
            continue
        target = root / file_spec.path
        if target.exists() and not file_spec.overwrite:
            result.skipped_files.append(file_spec.path)
            continue
        # 内容来源：content 字段或内置 template 名（未来扩展）
        raw_content = file_spec.content
        if file_spec.template and not raw_content:
            raw_content = _render_builtin_template(file_spec.template, project_name)
        rendered = template.render_content(raw_content, project_name)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
        result.created_files.append(file_spec.path)

    # 写入项目自描述模板（幂等，不覆盖）
    if write_project_template:
        tpl_path = root / ".sage" / "template.json"
        if tpl_path.exists():
            result.skipped_files.append(".sage/template.json")
        else:
            if not dry_run:
                save_project_template(root, template)
            result.created_files.append(".sage/template.json")

    return result


def _render_builtin_template(template_name: str, project_name: str) -> str:
    """渲染内置模板内容（目前仅 ``"$SELF"`` 特殊值；保留扩展点）。

    未来可在此处登记 ``sage_md`` / ``cfd_project`` 等名称对应的内容生成器。
    当前仅原样返回空字符串，由调用方按 ``file_spec.content`` 兜底。
    """
    if template_name == "$SELF":
        return ""
    return ""


__all__ = [
    "GLOBAL_TEMPLATE_DIR",
    "ProjectTemplate",
    "ScaffoldResult",
    "TemplateDirectory",
    "TemplateFile",
    "get_built_in_templates",
    "load_global_templates",
    "load_project_template",
    "resolve_template",
    "save_project_template",
    "scaffold_project",
]
