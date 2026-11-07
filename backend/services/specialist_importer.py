# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""专家包导入服务（M1-D / M4-T1，spec §8.3）。

从用户上传的 ``.sage`` zip 包（或内置模板目录）导入/实例化专家:

1. 解压 zip 到临时目录（zip 入口）或直接读取本地目录（模板入口）
2. 解析 ``persona.md`` frontmatter — v1 只有 ``name/version/source``，
   v2 包含完整 profile（format_version=2，全部 profile 字段）
3. 安全扫描（注入模式 / 密钥正则 / 路径穿越 / 超大文件）
4. 生成新 ``agent_id``（或由调用方显式指定 ``requested_id``）
5. 复制 ``knowledge/``/``skills/``/``avatar.png`` 到
   ``~/.sage/specialists/<new_id>/``（脚本剥离执行位）
6. 构造完整 profile（强制 ``role=specialist``，``full_access`` 降级为
   ``workspace_write``，数组/字典字段经 JSON 安全钳制），
   ``knowledge_bindings`` 仅保留 ``specialist_private`` 并重绑到新 agent_id，
   其余计数计入 ``dropped_bindings``
7. ``AgentRepository().upsert(profile)``；失败时回滚 agent 目录
8. 返回 ``{"id", "name", "dropped_bindings"}``

来源标记:
- 外部导入默认 ``source=imported``（不采信包内 source 字段）
- 模板实例化调用方显式传 ``source_override="builtin"``

安全约束:
- zip 路径穿越检查 + 单文件 10MB + 总 50MB
- persona.md 正文扫描注入模式（"ignore previous instructions" 等）
- 全 zip 扫描密钥模式（API_KEY / SECRET / TOKEN）
- scripts/*.py 仅复制，剥离 0o111 执行位
- 字符串数组去重且限量（skills ≤ 64 / tools ≤ 128 / memory_access ≤ 16）
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.specialist_exporter import MAX_AVATAR_BYTES, MAX_KNOWLEDGE_BYTES
from backend.skills.specialist_skills import is_agent_id_safe, specialists_root

logger = logging.getLogger(__name__)

#: 单文件大小上限（字节）
MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

#: 允许的权限模式（与 legacy_agent_routes 白名单同步）
_VALID_PERMISSION_MODES = {"read_only", "workspace_write", "prompt", "full_access"}

#: 字符串数组长度上限（防恶意膨胀）
_SKILLS_LIMIT = 64
_TOOLS_LIMIT = 128
_MEMORY_ACCESS_LIMIT = 16
_BINDINGS_LIMIT = 256

#: 注入模式（persona.md 正文扫描）
INJECTION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(DAN|an?\s+unrestricted)", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(your|the)\s+(rules|guidelines)", re.IGNORECASE),
]

#: 密钥模式（全 zip 文件内容扫描）
SECRET_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\b[A-Z_]*(API_KEY|APIKEY|API_SECRET)[A-Z_]*\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"\b[A-Z_]*(SECRET_KEY|SECRET)[A-Z_]*\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"\b[A-Z_]*(ACCESS_TOKEN|AUTH_TOKEN)[A-Z_]*\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),  # OpenAI-style key
    re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"),  # GitHub PAT
]


# --------------------------------------------------------------------------- #
# Public
# --------------------------------------------------------------------------- #


def import_specialist(
    zip_path: Path,
    *,
    requested_id: Optional[str] = None,
    source_override: Optional[str] = None,
) -> Dict[str, Any]:
    """从 zip 包导入专家。

    Args:
        zip_path: 上传的 zip 文件路径
        requested_id: 显式指定 agent_id（模板实例化使用；外部导入默认 None 自动生成）
        source_override: 覆盖 source 字段（模板传 ``"builtin"``；外部导入默认 ``"imported"``）

    Returns:
        ``{"id": <new_agent_id>, "name": <display_name>, "dropped_bindings": <int>}``

    Raises:
        ValueError: zip 格式非法 / persona.md 缺失 / 安全扫描失败 /
                    requested_id 非法或已存在
    """
    tmp_dir = tempfile.mkdtemp(prefix="sage-import-")
    try:
        extract_dir = Path(tmp_dir) / "extracted"
        _extract_zip(zip_path, extract_dir)
        return install_specialist_from_dir(
            extract_dir,
            requested_id=requested_id,
            source_override=source_override,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def install_specialist_from_dir(
    source_dir: Path,
    *,
    requested_id: Optional[str] = None,
    source_override: Optional[str] = None,
) -> Dict[str, Any]:
    """从本地目录物化专家（与 ``import_specialist`` 共享核心管线）。

    与 zip 入口的差异:
    - 不做 zip 解压与路径穿越检查（由模板数据源自行保证）
    - 仍执行注入/密钥扫描（模板数据本身不可信度低于外部 zip，但为保守起见保留）
    - ``requested_id`` 默认 None（模板实例化传显式 id）
    """
    persona_md = source_dir / "persona.md"
    if not persona_md.is_file():
        raise ValueError("缺少 persona.md")

    metadata, body = _parse_persona_md(persona_md)
    _scan_injection(body, persona_md)
    _scan_secrets(source_dir)

    # 决定 id
    if requested_id is not None:
        if not is_agent_id_safe(requested_id):
            raise ValueError(f"非法 agent_id: {requested_id}")
        from backend.data.agent_repo import AgentRepository

        if AgentRepository().get(requested_id):
            raise ValueError(f"agent_id 已存在: {requested_id}")
        new_id = requested_id
    else:
        new_id = _generate_unique_agent_id(metadata.get("name") or "specialist")

    # 复制文件（失败回滚）
    agent_dir = specialists_root() / new_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    try:
        _copy_knowledge(source_dir / "knowledge", agent_dir / "knowledge")
        _copy_skills(source_dir / "skills", agent_dir / "skills")
        _copy_avatar(source_dir / "avatar.png", agent_dir / "avatar.png")

        # 构造 profile
        profile, dropped = _build_profile(metadata, body, new_id, source_override)

        # 写 agents 表
        from backend.data.agent_repo import AgentRepository

        AgentRepository().upsert(profile)
        logger.info(
            "专家物化成功: new_id=%s name=%s dropped=%d",
            new_id,
            profile.get("name"),
            dropped,
        )
        return {
            "id": new_id,
            "name": profile.get("name") or new_id,
            "dropped_bindings": dropped,
        }
    except Exception:
        shutil.rmtree(agent_dir, ignore_errors=True)
        raise


# --------------------------------------------------------------------------- #
# 解压 / 扫描
# --------------------------------------------------------------------------- #


def _extract_zip(zip_path: Path, dest: Path) -> None:
    """安全解压：拒绝绝对路径 / 路径穿越 / 超大文件。"""
    dest.mkdir(parents=True, exist_ok=True)
    total_size = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"zip 路径穿越: {info.filename}")
            if info.file_size > MAX_SINGLE_FILE_BYTES:
                raise ValueError(
                    f"文件过大 ({info.file_size} bytes): {info.filename}"
                )
            total_size += info.file_size
        if total_size > MAX_KNOWLEDGE_BYTES:
            raise ValueError(f"zip 总大小超过 50MB: {total_size} bytes")
        zf.extractall(dest)


def _parse_persona_md(path: Path) -> Tuple[Dict[str, Any], str]:
    """解析 persona.md frontmatter + 正文（v1/v2 兼容）。"""
    import yaml

    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError("persona.md 缺少 frontmatter（必须以 --- 开头）")
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("persona.md frontmatter 格式错误")
    try:
        metadata = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"persona.md frontmatter YAML 解析失败: {exc}") from exc
    body = parts[2].strip()
    if not isinstance(metadata, dict):
        raise ValueError("persona.md frontmatter 必须是 YAML 字典")
    return metadata, body


def _scan_injection(body: str, path: Path) -> None:
    """扫描 persona.md 正文的注入模式。"""
    for pattern in INJECTION_PATTERNS:
        if pattern.search(body):
            raise ValueError(
                f"persona.md 包含可疑注入模式 (匹配 {pattern.pattern!r}): {path}"
            )


def _scan_secrets(src: Path) -> None:
    """扫描全部文本文件的密钥模式。"""
    for file in src.rglob("*"):
        if not file.is_file() or file.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
            continue
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise ValueError(
                    f"文件包含可疑密钥模式 (匹配 {pattern.pattern!r}): {file.relative_to(src)}"
                )


def _generate_unique_agent_id(base_name: str) -> str:
    """生成唯一 agent_id（base_name + 短 UUID）。"""
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", base_name).lower()[:32]
    if not safe or not is_agent_id_safe(safe):
        safe = "specialist"
    suffix = uuid.uuid4().hex[:8]
    return f"{safe}-{suffix}"


# --------------------------------------------------------------------------- #
# 文件复制
# --------------------------------------------------------------------------- #


def _copy_knowledge(src: Path, dest: Path) -> None:
    """复制 knowledge/ 目录（≤50MB）。"""
    if not src.is_dir():
        return
    total_size = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
    if total_size > MAX_KNOWLEDGE_BYTES:
        raise ValueError(f"knowledge/ 超过 50MB: {total_size} bytes")
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _copy_skills(src: Path, dest: Path) -> None:
    """复制 skills/ 目录（不执行脚本）。"""
    if not src.is_dir():
        return
    shutil.copytree(src, dest, dirs_exist_ok=True)
    for script in dest.rglob("scripts/*.py"):
        if script.is_file():
            mode = script.stat().st_mode
            script.chmod(mode & ~0o111)


def _copy_avatar(src: Path, dest: Path) -> None:
    """复制 avatar.png（≤512KB）。"""
    if not src.is_file():
        return
    if src.stat().st_size > MAX_AVATAR_BYTES:
        logger.warning("头像超过 512KB，跳过: %s (%d bytes)", src, src.stat().st_size)
        return
    shutil.copyfile(src, dest)


# --------------------------------------------------------------------------- #
# Profile 构造 + 安全钳制
# --------------------------------------------------------------------------- #


def _build_profile(
    metadata: Dict[str, Any],
    body: str,
    new_id: str,
    source_override: Optional[str],
) -> Tuple[Dict[str, Any], int]:
    """从 frontmatter metadata 构造 AgentProfile 字典，并钳制边界。

    Returns:
        (profile, dropped_bindings_count)
    """
    # 来源：显式覆盖 > "imported"（外部导入不采信包内 source）
    source = source_override or "imported"

    # 字符串标量字段
    name = _coerce_str(metadata.get("name"), default=new_id, max_len=128)
    description = _coerce_str(metadata.get("description"), max_len=2048)
    system_prompt = body or _coerce_str(metadata.get("system_prompt"), max_len=200_000)

    # 整数 / 布尔字段
    version = _coerce_int(metadata.get("version"), default=1, minimum=1, maximum=9999)
    enabled = bool(metadata.get("enabled", True))
    max_iterations = _coerce_int(
        metadata.get("max_iterations"), default=10, minimum=1, maximum=50
    )

    # 权限模式
    perm = _coerce_str(
        metadata.get("permission_mode"), default="workspace_write", max_len=64
    )
    if perm not in _VALID_PERMISSION_MODES:
        perm = "workspace_write"
    elif perm == "full_access":
        # 强制降级
        perm = "workspace_write"

    # 字符串数组字段
    skills = _sanitize_string_list(metadata.get("skills"), limit=_SKILLS_LIMIT)
    tools = _sanitize_string_list(metadata.get("tools"), limit=_TOOLS_LIMIT)
    memory_access = _sanitize_string_list(
        metadata.get("memory_access"),
        limit=_MEMORY_ACCESS_LIMIT,
        whitelist=("user", "project", "specialist"),
    )

    # 映射字段（JSON 安全递归清洗）
    model_config = _sanitize_mapping(metadata.get("model_config"))
    memory_policy = _sanitize_mapping(metadata.get("memory_policy"))
    persona_ui = _sanitize_mapping(metadata.get("persona_ui"))
    # 把 frontmatter 顶层 tagline/avatar 合并进 persona_ui（缺失字段回填）
    tagline = _coerce_str(metadata.get("tagline"), max_len=256)
    avatar = _coerce_str(metadata.get("avatar"), max_len=16)
    if tagline and "tagline" not in persona_ui:
        persona_ui["tagline"] = tagline
    if avatar and "avatar" not in persona_ui:
        persona_ui["avatar"] = avatar

    # 知识绑定：仅保留 specialist_private，重绑到新 agent_id
    bindings, dropped = _sanitize_bindings(metadata.get("knowledge_bindings"), new_id)

    profile: Dict[str, Any] = {
        "id": new_id,
        "name": name,
        "role": "specialist",  # 强制
        "system_prompt": system_prompt,
        "description": description,
        "source": source,
        "version": version,
        "enabled": enabled,
        "max_iterations": max_iterations,
        "permission_mode": perm,
        "skills": skills,
        "tools": tools,
        "memory_access": memory_access,
        "model_config": model_config,
        "memory_policy": memory_policy,
        "persona_ui": persona_ui,
        "knowledge_bindings": bindings,
    }
    return profile, dropped


def _sanitize_bindings(
    raw_bindings: Any, new_id: str
) -> Tuple[List[Dict[str, Any]], int]:
    """保留 specialist_private 并重绑；其余丢弃并计数。"""
    raw = raw_bindings if isinstance(raw_bindings, list) else []
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for entry in raw[:_BINDINGS_LIMIT]:
        if not isinstance(entry, dict):
            dropped += 1
            continue
        if entry.get("source_type") != "specialist_private":
            dropped += 1
            continue
        kept.append(
            {
                "id": _coerce_str(entry.get("id"), default=str(uuid.uuid4())[:8], max_len=64),
                "agent_id": new_id,
                "source_type": "specialist_private",
                "source_id": new_id,  # specialist_private 定位 = agent_id
                "name": _coerce_str(entry.get("name"), max_len=128) or "specialist_private",
                "filters": _sanitize_mapping(entry.get("filters")),
                "created_at": _coerce_int(entry.get("created_at"), default=0, minimum=0, maximum=9_999_999_999),
            }
        )
    return kept, dropped


def _sanitize_string_list(
    raw: Any, *, limit: int, whitelist: Optional[Tuple[str, ...]] = None
) -> List[str]:
    """强制字符串数组：过滤非 str、去重、限量、可选白名单。"""
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen: set = set()
    for raw_item in raw:
        if not isinstance(raw_item, str):
            continue
        item = raw_item.strip()
        if not item:
            continue
        if whitelist is not None and item not in whitelist:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _sanitize_mapping(raw: Any) -> Dict[str, Any]:
    """递归清洗映射为 JSON 安全值（保留 dict/list/str/int/float/bool/None）。"""
    if not isinstance(raw, dict):
        return {}

    def _clean(obj: Any) -> Any:
<<<<<<< HEAD
        if obj is None or isinstance(obj, (bool, int, float, str)):
=======
        if obj is None or isinstance(obj, (bool, int, float, str)):  # noqa: UP038 — py38 运行时不支持 PEP 604 isinstance
>>>>>>> origin/main
            return obj
        if isinstance(obj, dict):
            out: Dict[str, Any] = {}
            for k, v in obj.items():
                if not isinstance(k, str):
                    continue
                cleaned = _clean(v)
                if cleaned is not None:
                    out[k] = cleaned
            return out
        if isinstance(obj, list):
            cleaned_list = [_clean(v) for v in obj]
            return [v for v in cleaned_list if v is not None]
        # 非 JSON 安全类型（bytes / set / 自定义对象）→ 丢弃
        return None

    return _clean(raw)


def _coerce_str(value: Any, *, default: str = "", max_len: int = 1024) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    if not value:
        return default
    return value[:max_len]


def _coerce_int(
    value: Any, *, default: int, minimum: int, maximum: int
) -> int:
<<<<<<< HEAD
    if isinstance(value, bool) or not isinstance(value, (int, float)):
=======
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # noqa: UP038 — py38 运行时
>>>>>>> origin/main
        return default
    v = int(value)
    if v < minimum:
        return minimum
    if v > maximum:
        return maximum
    return v


__all__ = [
    "import_specialist",
    "install_specialist_from_dir",
    "INJECTION_PATTERNS",
    "SECRET_PATTERNS",
    "MAX_SINGLE_FILE_BYTES",
]
