# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""专家包导出服务（M1-D，spec §8.3）。

将专家数据打包为 ``.sage`` zip 格式（实际 MIME 为 ``application/zip``，
扩展名 ``.sage`` 仅作标识），包含:

- ``persona.md`` — Markdown frontmatter + 系统提示词正文
- ``avatar.png`` — 头像（可选，≤512KB）
- ``skills/`` — 专家私有技能目录（可选）
- ``knowledge/`` — 专家私有知识目录（可选，≤50MB）

导出逻辑 fail-safe：任何文件缺失/权限错误都降级为空或部分结果，绝不外抛。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict

from backend.skills.specialist_skills import is_agent_id_safe, specialists_root

logger = logging.getLogger(__name__)

#: 头像大小上限（字节）
MAX_AVATAR_BYTES = 512 * 1024  # 512 KB

#: 知识目录总大小上限（字节）
MAX_KNOWLEDGE_BYTES = 50 * 1024 * 1024  # 50 MB


def export_specialist(agent_id: str) -> Path:
    """将专家数据打包为 zip，返回临时文件路径。

    Args:
        agent_id: 专家 ID（必须通过 ``is_agent_id_safe`` 校验）

    Returns:
        临时 zip 文件路径（调用方负责删除）

    Raises:
        ValueError: agent_id 不存在或非法
        FileNotFoundError: 专家数据目录不存在
    """
    if not is_agent_id_safe(agent_id):
        raise ValueError(f"非法 agent_id: {agent_id}")

    agent_dir = specialists_root() / agent_id
    if not agent_dir.is_dir():
        raise FileNotFoundError(f"专家数据目录不存在: {agent_dir}")

    # 读 agents 表元数据（用于 persona.md frontmatter）
    from backend.data.agent_repo import AgentRepository

    row = AgentRepository().get(agent_id)
    if not row:
        raise ValueError(f"agents 表无此专家: {agent_id}")

    # 临时目录构建 zip
    tmp_dir = tempfile.mkdtemp(prefix="sage-export-")
    zip_path = Path(tmp_dir) / f"{agent_id}.sage"

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. persona.md（从 system_prompt 字段生成）
            _write_persona_md(zf, row)

            # 2. avatar.png（如有）
            _write_avatar(zf, agent_dir)

            # 3. skills/（专家私有技能）
            _write_skills(zf, agent_dir / "skills")

            # 4. knowledge/（专家私有知识，≤50MB）
            _write_knowledge(zf, agent_dir / "knowledge")

        logger.info("专家包导出成功: agent_id=%s zip=%s", agent_id, zip_path)
        return zip_path

    except Exception:
        # 构建失败 → 清理临时目录
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def _write_persona_md(zf: zipfile.ZipFile, row: Dict[str, Any]) -> None:
    """生成 persona.md（frontmatter + 系统提示词正文）。"""
    import yaml

    frontmatter = {
        "name": row.get("name") or row.get("id"),
        "version": 1,
        "source": row.get("source") or "user",
    }
    system_prompt = row.get("system_prompt") or ""

    content = (
        f"---\n{yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()}\n---\n\n{system_prompt}\n"
    )
    zf.writestr("persona.md", content.encode("utf-8"))


def _write_avatar(zf: zipfile.ZipFile, agent_dir: Path) -> None:
    """打包 avatar.png（如有，≤512KB）。"""
    avatar_path = agent_dir / "avatar.png"
    if not avatar_path.is_file():
        return
    size = avatar_path.stat().st_size
    if size > MAX_AVATAR_BYTES:
        logger.warning("头像超过 512KB，跳过: %s (%d bytes)", avatar_path, size)
        return
    zf.write(avatar_path, "avatar.png")


def _write_skills(zf: zipfile.ZipFile, skills_dir: Path) -> None:
    """打包 skills/ 目录（专家私有技能）。"""
    if not skills_dir.is_dir():
        return
    for skill_entry in sorted(skills_dir.iterdir()):
        if not skill_entry.is_dir() or skill_entry.name.startswith("."):
            continue
        # 打包技能子目录下的所有文件（SKILL.md、脚本、模板等）
        for sub in sorted(skill_entry.rglob("*")):
            if sub.is_file() and not sub.name.startswith("."):
                rel = sub.relative_to(skills_dir)
                zf.write(sub, f"skills/{rel}")


def _write_knowledge(zf: zipfile.ZipFile, knowledge_dir: Path) -> None:
    """打包 knowledge/ 目录（≤50MB）。"""
    if not knowledge_dir.is_dir():
        return
    total_size = sum(f.stat().st_size for f in knowledge_dir.rglob("*") if f.is_file())
    if total_size > MAX_KNOWLEDGE_BYTES:
        logger.warning(
            "知识目录超过 50MB，跳过: %s (%d bytes)", knowledge_dir, total_size
        )
        return
    for file in sorted(knowledge_dir.rglob("*")):
        if file.is_file() and not file.name.startswith("."):
            rel = file.relative_to(knowledge_dir)
            zf.write(file, f"knowledge/{rel}")


__all__ = ["export_specialist", "MAX_AVATAR_BYTES", "MAX_KNOWLEDGE_BYTES"]
