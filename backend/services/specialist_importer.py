# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""专家包导入服务（M1-D，spec §8.3）。

从用户上传的 ``.sage`` zip 包导入专家:

1. 解压 zip 到临时目录
2. 解析 ``persona.md`` frontmatter（name, tagline, version, source）
3. 安全扫描（注入模式 / 密钥正则 / 禁止自动执行脚本）
4. 生成新 ``agent_id``（避免与现有专家冲突）
5. 复制 ``knowledge/`` → ``~/.sage/specialists/<new_id>/knowledge/``
6. 复制 ``skills/`` → ``~/.sage/specialists/<new_id>/skills/``（不执行脚本）
7. 写入 ``agents`` 表
8. 返回新 ``agent_id`` 和 ``name``

安全约束:
- 脚本文件（``skills/*/scripts/*.py``）仅复制，不标记可执行
- ``persona.md`` 正文扫描注入模式（"ignore previous instructions" 等）
- 全 zip 扫描密钥模式（``API_KEY``, ``SECRET``, ``TOKEN``）
- 总大小上限 50MB，单文件上限 10MB
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from backend.services.specialist_exporter import MAX_KNOWLEDGE_BYTES
from backend.skills.specialist_skills import is_agent_id_safe, specialists_root

logger = logging.getLogger(__name__)

#: 单文件大小上限（字节）
MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

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


def import_specialist(zip_path: Path) -> Dict[str, Any]:
    """从 zip 包导入专家。

    Args:
        zip_path: 上传的 zip 文件路径

    Returns:
        ``{"id": <new_agent_id>, "name": <display_name>}``

    Raises:
        ValueError: zip 格式非法 / persona.md 缺失 / 安全扫描失败
    """
    tmp_dir = tempfile.mkdtemp(prefix="sage-import-")
    try:
        # 1. 解压
        extract_dir = Path(tmp_dir) / "extracted"
        _extract_zip(zip_path, extract_dir)

        # 2. 解析 persona.md
        persona_md = extract_dir / "persona.md"
        if not persona_md.is_file():
            raise ValueError("zip 包缺少 persona.md")
        metadata, body = _parse_persona_md(persona_md)

        # 3. 安全扫描
        _scan_injection(body, persona_md)
        _scan_secrets(extract_dir)

        # 4. 生成新 agent_id
        new_id = _generate_unique_agent_id(metadata.get("name") or "specialist")

        # 5-6. 复制文件
        agent_dir = specialists_root() / new_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        _copy_knowledge(extract_dir / "knowledge", agent_dir / "knowledge")
        _copy_skills(extract_dir / "skills", agent_dir / "skills")

        # 7. 写 agents 表（upsert，完整 profile dict）
        from backend.data.agent_repo import AgentRepository

        profile = {
            "id": new_id,
            "name": metadata.get("name") or new_id,
            "role": "specialist",
            "system_prompt": body,
            "source": metadata.get("source") or "user",
            "version": int(metadata.get("version") or 1),
            "enabled": True,
        }
        AgentRepository().upsert(profile)

        logger.info("专家导入成功: new_id=%s name=%s", new_id, metadata.get("name"))
        return {"id": new_id, "name": metadata.get("name") or new_id}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract_zip(zip_path: Path, dest: Path) -> None:
    """安全解压：拒绝绝对路径 / 路径穿越 / 超大文件。"""
    dest.mkdir(parents=True, exist_ok=True)
    total_size = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # 路径穿越检查
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"zip 路径穿越: {info.filename}")
            # 单文件大小检查
            if info.file_size > MAX_SINGLE_FILE_BYTES:
                raise ValueError(
                    f"文件过大 ({info.file_size} bytes): {info.filename}"
                )
            total_size += info.file_size
        # 总大小检查
        if total_size > MAX_KNOWLEDGE_BYTES:
            raise ValueError(f"zip 总大小超过 50MB: {total_size} bytes")
        zf.extractall(dest)


def _parse_persona_md(path: Path) -> Tuple[Dict[str, Any], str]:
    """解析 persona.md frontmatter + 正文。"""
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


def _scan_secrets(extract_dir: Path) -> None:
    """扫描全 zip 文件的密钥模式。"""
    for file in extract_dir.rglob("*"):
        if not file.is_file() or file.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
            continue
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise ValueError(
                    f"文件包含可疑密钥模式 (匹配 {pattern.pattern!r}): {file.relative_to(extract_dir)}"
                )


def _generate_unique_agent_id(base_name: str) -> str:
    """生成唯一 agent_id（base_name + 短 UUID）。"""
    # 清理 base_name 为合法 agent_id 字符
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", base_name).lower()[:32]
    if not safe or not is_agent_id_safe(safe):
        safe = "specialist"
    # 追加短 UUID 避免冲突
    suffix = uuid.uuid4().hex[:8]
    return f"{safe}-{suffix}"


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
    # 确保脚本不可执行（移除执行权限）
    for script in dest.rglob("scripts/*.py"):
        if script.is_file():
            mode = script.stat().st_mode
            script.chmod(mode & ~0o111)  # 移除所有执行位


__all__ = [
    "import_specialist",
    "INJECTION_PATTERNS",
    "SECRET_PATTERNS",
    "MAX_SINGLE_FILE_BYTES",
]
