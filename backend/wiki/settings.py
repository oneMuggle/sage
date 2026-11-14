"""Wiki 项目设置持久化。

每个 wiki 项目独立的配置（任务路由、推理模式等），存储在 .llm-wiki/settings.json。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"


@dataclass
class TaskRoutingConfig:
    """按任务类型路由到不同 LLM 模型。

    None 表示使用全局默认模型。
    """

    chat_model: Optional[str] = None
    ingest_model: Optional[str] = None
    research_model: Optional[str] = None


@dataclass
class ReasoningConfig:
    """推理模式配置。

    chat_mode: 聊天时的推理模式（默认 auto）
    ingest_mode: ingest 时的推理模式（默认 off，避免空内容）
    """

    chat_mode: str = "auto"
    ingest_mode: str = "off"


@dataclass
class WikiSettings:
    """Wiki 项目设置。"""

    task_routing: TaskRoutingConfig = field(default_factory=TaskRoutingConfig)
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> WikiSettings:
        tr = data.get("task_routing", {})
        r = data.get("reasoning", {})
        return cls(
            task_routing=TaskRoutingConfig(
                chat_model=tr.get("chat_model"),
                ingest_model=tr.get("ingest_model"),
                research_model=tr.get("research_model"),
            ),
            reasoning=ReasoningConfig(
                chat_mode=r.get("chat_mode", "auto"),
                ingest_mode=r.get("ingest_mode", "off"),
            ),
        )


def _settings_path(project_root: Path) -> Path:
    return project_root / ".llm-wiki" / SETTINGS_FILENAME


def load_settings(project_root: Path) -> WikiSettings:
    """加载项目设置，不存在则返回默认值。"""
    path = _settings_path(project_root)
    if not path.exists():
        return WikiSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WikiSettings.from_dict(data)
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
        logger.warning("加载 wiki 设置失败: %s", exc)
        return WikiSettings()


def save_settings(project_root: Path, settings: WikiSettings) -> None:
    """原子保存项目设置。"""
    path = _settings_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def resolve_model_for_task(settings: WikiSettings, task: str, default_model: str) -> str:
    """根据任务类型解析模型。

    Args:
        settings: 项目设置
        task: 任务类型（chat/ingest/research）
        default_model: 全局默认模型

    Returns:
        解析后的模型名称
    """
    mapping = {
        "chat": settings.task_routing.chat_model,
        "ingest": settings.task_routing.ingest_model,
        "research": settings.task_routing.research_model,
    }
    return mapping.get(task) or default_model
