"""子代理档案文件化（CA1-CA2, round9）—— .sage/agents/*.md 导入与导出。

对标 Claude Code 的 ``.claude/agents/*.md``：子代理 = frontmatter（元数据）
+ markdown 正文（system prompt），随项目走、可 review、可进 git。Sage 的
档案此前是纯 DB 资产（种子 + REST/UI 管理），本模块补上"文件 ↔ DB"双通道：

- **导入**（``import_agents_from_files``）：扫描 ``.sage/agents/*.md``，
  逐字段与 DB 现值比对，有差异才 upsert；``enabled`` 开关态保留 DB 现值
  （文件不覆盖用户开关）。解析失败计入 errors，绝不中断其余文件、绝不抛出。
- **导出**（``export_agent_to_file``）：以 DB 现值写 ``<dir>/<agent_id>.md``
  （覆盖写，"导出即固化"），目录不存在自动创建。

frontmatter 为 stdlib-only 解析（key: value 行，逗号分隔列表）——与
doctor checks 的 stdlib 纪律一致，不引入 yaml 依赖。

发现目录优先级：env ``SAGE_AGENTS_DIR`` > ``<cwd>/.sage/agents``。
文件名（去扩展名）经 ``[a-z0-9_-]`` 清洗小写后作为 agent_id。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AGENTS_DIR_ENV = "SAGE_AGENTS_DIR"
AGENTS_PROJECT_SUBDIR = os.path.join(".sage", "agents")

#: agent_id 清洗：文件名 stem → [a-z0-9_-] 小写
_AGENT_ID_RE = re.compile(r"[^a-z0-9_-]+")

#: frontmatter 支持的键（其余键忽略，容错向前兼容）
_SUPPORTED_KEYS = (
    "name",
    "role",
    "description",
    "tools",
    "memory_access",
    "max_iterations",
    "enabled",
    "model",
    "temperature",
    "max_tokens",
)

#: 导入时参与差异比对的档案字段（不含 enabled —— 保留 DB 开关态）
_COMPARE_FIELDS = (
    "name",
    "role",
    "description",
    "system_prompt",
    "tools",
    "memory_access",
    "max_iterations",
    "model_config",
)


class AgentsFileError(ValueError):
    """档案文件解析失败（path 上下文由调用方拼接）。"""


def sanitize_agent_id(stem: str) -> str:
    """文件名 stem → 合法 agent_id（小写、[a-z0-9_-]），空则回退 'agent'。"""
    cleaned = _AGENT_ID_RE.sub("-", (stem or "").strip().lower()).strip("-")
    return cleaned or "agent"


def agents_dir() -> Path:
    """档案目录：env SAGE_AGENTS_DIR > <cwd>/.sage/agents。"""
    env = os.environ.get(AGENTS_DIR_ENV, "").strip()
    if env:
        return Path(env)
    return Path.cwd() / AGENTS_PROJECT_SUBDIR


def _parse_scalar(key: str, raw: str) -> Any:
    """frontmatter 标量解析：bool/int/float/逗号列表/字符串。"""
    value = raw.strip()
    if key in ("tools", "memory_access"):
        return [item.strip() for item in value.split(",") if item.strip()]
    if key == "enabled":
        return value.lower() in ("true", "1", "yes", "on")
    if key == "max_iterations":
        return max(1, int(value))
    if key == "temperature":
        return float(value)
    if key == "max_tokens":
        return int(value)
    return value


def _split_frontmatter(text: str) -> tuple:
    """拆 (frontmatter 文本 or None, 正文)。首行 ``---`` 至下一 ``---`` 之间。"""
    lines = text.splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        return None, "\n".join(lines[start:]).strip()
    end = None
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        raise AgentsFileError("frontmatter 未闭合（缺少第二个 ---）")
    return "\n".join(lines[start + 1 : end]), "\n".join(lines[end + 1 :]).strip()


def _parse_frontmatter(raw: str) -> Dict[str, Any]:
    """逐行 key: value 解析；未知键忽略（容错向前兼容）。"""
    meta: Dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            raise AgentsFileError(f"frontmatter 行缺少冒号: {line.strip()!r}")
        key, _, raw_value = line.partition(":")
        key = key.strip().lower()
        if key not in _SUPPORTED_KEYS:
            continue
        try:
            meta[key] = _parse_scalar(key, raw_value)
        except (ValueError, TypeError) as exc:
            raise AgentsFileError(f"frontmatter 字段 {key} 非法: {raw_value!r} ({exc})")
    return meta


def parse_agent_file(path: Path) -> Dict[str, Any]:
    """解析单个档案文件为 AgentRepository.upsert 形状的 dict。

    Raises:
        AgentsFileError: frontmatter/结构非法（调用方捕获计入 errors）。
    """
    text = path.read_text(encoding="utf-8")
    raw_meta, body = _split_frontmatter(text)
    meta = _parse_frontmatter(raw_meta) if raw_meta is not None else {}
    agent_id = sanitize_agent_id(path.stem)
    if not body:
        raise AgentsFileError("system prompt 正文为空")
    model_config = {
        "model": str(meta.get("model", "gpt-3.5-turbo")),
        "temperature": float(meta.get("temperature", 0.7)),
        "max_tokens": int(meta.get("max_tokens", 4096)),
    }
    return {
        "id": agent_id,
        "name": str(meta.get("name") or path.stem),
        "role": str(meta.get("role") or "researcher"),
        "description": str(meta.get("description") or ""),
        "system_prompt": body,
        "tools": list(meta.get("tools") or []),
        "memory_access": list(
            meta.get("memory_access") or ["working", "episodic", "semantic"]
        ),
        "max_iterations": int(meta.get("max_iterations", 10)),
        "enabled": bool(meta.get("enabled", True)),
        "model_config": model_config,
    }


def _profile_from_repo_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """DB 行 → 与 parse_agent_file 同形状（供差异比对）。"""
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "role": row.get("role"),
        "description": row.get("description") or "",
        "system_prompt": row.get("system_prompt") or "",
        "tools": list(row.get("tools") or []),
        "memory_access": list(row.get("memory_access") or []),
        "max_iterations": row.get("max_iterations", 10),
        "enabled": bool(row.get("enabled", True)),
        "model_config": row.get("model_config")
        or {"model": "gpt-3.5-turbo", "temperature": 0.7, "max_tokens": 4096},
    }


def import_agents_from_files(directory: Optional[Path] = None) -> Dict[str, List[str]]:
    """扫描目录导入档案。返回 ``{"imported", "unchanged", "errors"}``。

    语义：
    - 目录不存在 → 全空结果（不告警，项目没有文件化档案是常态）；
    - 逐字段比对，有差异才 upsert（enabled 保留 DB 现值）；
    - 单文件解析失败计 errors，不中断其余文件、绝不抛出。
    """
    result: Dict[str, List[str]] = {"imported": [], "unchanged": [], "errors": []}
    target = Path(directory) if directory else agents_dir()
    if not target.is_dir():
        return result
    # 延迟 import：agents(应用层) → data 层与 profiles.py 同款纪律
    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()
    for path in sorted(target.glob("*.md")):
        try:
            profile = parse_agent_file(path)
        except (AgentsFileError, OSError, UnicodeDecodeError) as exc:
            result["errors"].append(f"{path.name}: {exc}")
            continue
        agent_id = profile["id"]
        existing = repo.get(agent_id)
        if existing is not None:
            profile["enabled"] = bool(existing.get("enabled", True))
        current = _profile_from_repo_row(existing) if existing else None
        differs = current is None or any(
            current.get(field) != profile.get(field) for field in _COMPARE_FIELDS
        )
        if not differs:
            result["unchanged"].append(agent_id)
            continue
        repo.upsert(profile)
        result["imported"].append(agent_id)
        logger.info("agents-files: 导入档案 %s（来自 %s）", agent_id, path.name)
    return result


def export_agent_to_file(agent_id: str, directory: Optional[Path] = None) -> Path:
    """把 DB 档案导出为 markdown 文件（覆盖写），返回文件路径。

    Raises:
        LookupError: agent_id 不存在。
    """
    from backend.data.agent_repo import AgentRepository

    row = AgentRepository().get(agent_id)
    if row is None:
        raise LookupError(f"agent {agent_id!r} 不存在")
    profile = _profile_from_repo_row(row)
    model_cfg = profile["model_config"] or {}
    meta_lines = [
        f"name: {profile['name']}",
        f"role: {profile['role']}",
        f"description: {profile['description']}",
        f"tools: {', '.join(profile['tools'])}",
        f"memory_access: {', '.join(profile['memory_access'])}",
        f"max_iterations: {profile['max_iterations']}",
        f"model: {model_cfg.get('model', 'gpt-3.5-turbo')}",
        f"temperature: {model_cfg.get('temperature', 0.7)}",
        f"max_tokens: {model_cfg.get('max_tokens', 4096)}",
    ]
    content = (
        "---\n" + "\n".join(meta_lines) + "\n---\n\n" + (profile["system_prompt"] or "") + "\n"
    )
    target = Path(directory) if directory else agents_dir()
    target.mkdir(parents=True, exist_ok=True)
    out_path = target / f"{sanitize_agent_id(agent_id)}.md"
    out_path.write_text(content, encoding="utf-8")
    logger.info("agents-files: 导出档案 %s → %s", agent_id, out_path)
    return out_path
