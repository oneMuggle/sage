"""AI 智能任务分解引擎（M1）。

将用户的自然语言需求拆解为里程碑树（milestone tree），利用 LLM
理解项目上下文（类型/阶段/描述/现有里程碑/约束）并生成结构化分解。

设计参考:
- Cursor Projects 的 coordinator 规划模式
- Jooj 的 PRD → Epic → Story 分解
- Bito 的 Epic 分解 + 置信度评分

调用链:
  API route → ProjectTaskDecomposer.decompose() → LLM → 结构化 JSON
           → ProjectMilestoneRepository.create_batch()
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DecomposedMilestone:
    """LLM 输出的单个里程碑分解结果。"""

    title: str
    description: Optional[str] = None
    stage: Optional[str] = None
    due_date: Optional[str] = None
    estimated_days: Optional[float] = None
    sort_order: int = 0
    _ref: Optional[str] = None
    parent_ref: Optional[str] = None
    children: List["DecomposedMilestone"] = field(default_factory=list)

    def to_create_dict(self) -> dict:
        """转为 create_batch() 接受的 dict 格式。"""
        d: Dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "stage": self.stage,
            "due_date": self.due_date,
            "estimated_days": self.estimated_days,
            "sort_order": self.sort_order,
        }
        if self._ref:
            d["_ref"] = self._ref
        if self.parent_ref:
            d["parent_id"] = self.parent_ref
        return d


@dataclass
class DecompositionResult:
    """任务分解结果。"""

    milestones: List[DecomposedMilestone]
    reasoning: str = ""
    tokens_used: int = 0
    raw_json: Optional[str] = None

    def to_create_items(self) -> List[dict]:
        """展平为 create_batch() 接受的 item 列表（DFS 序）。"""
        items: List[dict] = []

        def _flatten(ms: DecomposedMilestone, idx: int) -> None:
            d = ms.to_create_dict()
            d["sort_order"] = idx
            items.append(d)
            for child_idx, child in enumerate(ms.children):
                _flatten(child, child_idx)

        for i, ms in enumerate(self.milestones):
            _flatten(ms, i)
        return items

    def to_preview(self) -> List[dict]:
        """转为前端预览用的嵌套 dict 列表。"""
        def _to_dict(ms: DecomposedMilestone) -> dict:
            return {
                "title": ms.title,
                "description": ms.description,
                "stage": ms.stage,
                "due_date": ms.due_date,
                "estimated_days": ms.estimated_days,
                "children": [_to_dict(c) for c in ms.children],
            }
        return [_to_dict(ms) for ms in self.milestones]


class ProjectTaskDecomposer:
    """AI 任务分解引擎。

    使用方式::

        decomposer = ProjectTaskDecomposer()
        result = await decomposer.decompose(
            project_id="uuid-xxx",
            requirement="添加用户认证系统",
        )
        # result.milestones → [DecomposedMilestone, ...]
        # result.to_create_items() → 展平的 dict 列表
    """

    def __init__(self, llm_client: Any = None) -> None:
        """初始化分解器。

        Args:
            llm_client: LLM 客户端（暴露 async complete(prompt) -> str）。
                为 None 时自动从 settings 构建（可能返回 None → 降级）。
        """
        if llm_client is not None:
            self._llm = llm_client
        else:
            from backend.orchestration.llm_factory import (
                build_llm_client_from_settings,
            )
            self._llm = build_llm_client_from_settings()

    @property
    def available(self) -> bool:
        """LLM 客户端是否可用。"""
        return self._llm is not None

    async def decompose(
        self,
        project_id: str,
        requirement: str,
        context: Optional[str] = None,
    ) -> DecompositionResult:
        """将需求分解为里程碑树。

        Args:
            project_id: 项目 ID
            requirement: 用户自然语言需求
            context: 可选的补充上下文

        Returns:
            DecompositionResult，包含里程碑列表和推理说明。

        Raises:
            ValueError: 项目不存在
            RuntimeError: LLM 不可用
        """
        if not self.available:
            raise RuntimeError(
                "LLM 客户端不可用，请在设置中配置 AI 端点"
            )

        project = self._load_project(project_id)
        existing_titles = self._get_existing_milestone_titles(project_id)
        stage_enum = self._get_stage_enum(project)

        prompt = self._build_prompt(
            project=project,
            requirement=requirement,
            existing_titles=existing_titles,
            stage_enum=stage_enum,
            context=context,
        )

        try:
            raw_response = await self._llm.complete(prompt)
        except Exception as exc:
            logger.error("ProjectTaskDecomposer: LLM call failed: %s", exc)
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc

        parsed = self._parse_response(raw_response)
        parsed.raw_json = raw_response
        return parsed

    def _load_project(self, project_id: str) -> Any:
        """加载项目信息。"""
        from backend.data.project_repo import ProjectRepository

        repo = ProjectRepository()
        project = repo.get(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")
        return project

    def _get_existing_milestone_titles(self, project_id: str) -> List[str]:
        """获取项目现有里程碑标题（用于去重提示）。"""
        from backend.data.project_milestone_repo import ProjectMilestoneRepository

        repo = ProjectMilestoneRepository()
        milestones = repo.list_by_project(project_id)
        return [m.title for m in milestones if m.status != "completed"]

    def _get_stage_enum(self, project: Any) -> Optional[List[str]]:
        """获取项目的阶段枚举。"""
        from backend.data.project_milestone_repo import PROJECT_STAGE_ENUM

        ptype = getattr(project, "project_type", None) or getattr(
            project, "detected_type", None
        )
        if ptype and ptype in PROJECT_STAGE_ENUM:
            return PROJECT_STAGE_ENUM[ptype]
        return None

    def _build_prompt(
        self,
        project: Any,
        requirement: str,
        existing_titles: List[str],
        stage_enum: Optional[List[str]],
        context: Optional[str],
    ) -> str:
        """构建分解 prompt。"""
        project_type = getattr(project, "project_type", None) or "coding"
        project_desc = getattr(project, "description", None) or "未描述"
        current_stage = getattr(project, "project_stage", None) or "未设定"

        sections: List[str] = []

        # System 指令
        sections.append(
            "你是一个专业的项目管理 AI 助手。根据用户提供的需求描述，"
            "将其拆解为结构化的里程碑（milestone）树。每个里程碑可以"
            "有子里程碑（sub-milestones）。\n\n"
            "你必须严格以 JSON 格式输出，不要包含任何非 JSON 内容。"
        )

        # 项目上下文
        sections.append(
            f"## 项目信息\n"
            f"- 类型: {project_type}\n"
            f"- 当前阶段: {current_stage}\n"
            f"- 描述: {project_desc}"
        )

        if stage_enum:
            sections.append(
                f"## 可用阶段\n"
                f"{' → '.join(stage_enum)}"
            )

        # 现有里程碑（去重提示）
        if existing_titles:
            existing_str = "\n".join(f"- {t}" for t in existing_titles[:20])
            sections.append(
                f"## 现有里程碑（避免重复创建）\n{existing_str}"
            )

        # 需求
        sections.append(f"## 需要分解的需求\n{requirement}")

        if context:
            sections.append(f"## 补充上下文\n{context}")

        # 输出格式
        stage_options = ", ".join(stage_enum) if stage_enum else "可留空"
        sections.append(
            "## 输出格式\n"
            "严格输出以下 JSON 结构（不要 markdown 代码块包裹）：\n"
            "{\n"
            '  "reasoning": "简要说明分解思路（1-2句话）",\n'
            '  "milestones": [\n'
            "    {\n"
            '      "_ref": "m1",\n'
            '      "title": "里程碑标题（简洁，不超过20字）",\n'
            '      "description": "详细描述（1-3句话）",\n'
            f'      "stage": "阶段（{stage_options}）",\n'
            '      "due_date": "到期日 YYYY-MM-DD 或 null",\n'
            '      "estimated_days": 估算天数（数字，可为 null）,\n'
            '      "children": [\n'
            "        {\n"
            '          "_ref": "m1_1",\n'
            '          "parent_ref": "m1",\n'
            '          "title": "子任务标题",\n'
            '          "description": "...",\n'
            '          "estimated_days": 1\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "规则：\n"
            "1. 里程碑数量 2-8 个，每个子任务 1-5 个\n"
            "2. title 必须简洁可执行"
            "（如「实现 JWT 签发」而非「认证相关的工作」）\n"
            "3. estimated_days 给出合理估算（0.5-30 天）\n"
            "4. 不要与现有里程碑重复\n"
            "5. 子任务的 stage 可留空（继承父里程碑的阶段）"
        )

        return "\n\n".join(sections)

    def _parse_response(self, raw: str) -> DecompositionResult:
        """解析 LLM 的 JSON 响应。"""
        if not raw or not isinstance(raw, str):
            return DecompositionResult(
                milestones=[], reasoning="LLM 返回空响应"
            )

        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        json_str = raw.strip()
        code_block_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?\s*```", json_str, re.DOTALL
        )
        if code_block_match:
            json_str = code_block_match.group(1).strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试从字符串中找到第一个 { 和最后一个 }
            start = json_str.find("{")
            end = json_str.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(json_str[start : end + 1])
                except json.JSONDecodeError:
                    logger.warning(
                        "ProjectTaskDecomposer: JSON parse failed"
                    )
                    return DecompositionResult(
                        milestones=[],
                        reasoning="LLM 输出格式错误，无法解析",
                        raw_json=raw,
                    )
            else:
                return DecompositionResult(
                    milestones=[],
                    reasoning="LLM 输出格式错误，无有效 JSON",
                    raw_json=raw,
                )

        reasoning = data.get("reasoning", "")
        raw_milestones = data.get("milestones", [])

        if not isinstance(raw_milestones, list):
            return DecompositionResult(
                milestones=[],
                reasoning="milestones 不是列表",
                raw_json=raw,
            )

        milestones = []
        for item in raw_milestones:
            ms = self._parse_milestone(item)
            if ms:
                milestones.append(ms)

        return DecompositionResult(
            milestones=milestones,
            reasoning=reasoning,
            raw_json=raw,
        )

    def _parse_milestone(
        self, data: dict
    ) -> Optional[DecomposedMilestone]:
        """解析单个里程碑 dict。"""
        if not isinstance(data, dict):
            return None
        title = data.get("title")
        if not title or not isinstance(title, str):
            return None

        children = []
        for child_data in data.get("children", []):
            child = self._parse_milestone(child_data)
            if child:
                # 自动设置 parent_ref
                parent_ref = data.get("_ref") or data.get("title", "")
                child.parent_ref = parent_ref
                children.append(child)

        return DecomposedMilestone(
            title=title.strip(),
            description=data.get("description"),
            stage=data.get("stage"),
            due_date=data.get("due_date"),
            estimated_days=_safe_float(data.get("estimated_days")),
            sort_order=int(data.get("sort_order", 0)),
            _ref=data.get("_ref"),
            parent_ref=data.get("parent_ref"),
            children=children,
        )


def _safe_float(val: Any) -> Optional[float]:
    """安全转换 float，失败返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


__all__ = [
    "DecomposedMilestone",
    "DecompositionResult",
    "ProjectTaskDecomposer",
]
