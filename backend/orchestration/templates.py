"""``templates`` — 确定性编排模板（P2-8）。

``orchestration_mode="template:<id>"`` 走模板拆解：阶段 goal 可含 ``{request}``
占位符，运行时 ``str.replace`` 替换（同 classify 模式，防 .format() 抛错）。
**review 不进模板** —— 现有 P0-2 验证环自动兜底，模板含 review stage 会双重评审。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TemplateStage:
    id: str            # t1..tN（模板内序号，depends_on 引用它）
    agent_id: str      # 建议角色（需可派发，否则 planner 回退 primary）
    goal: str          # 可含 {request} 占位符
    depends_on: List[str] = field(default_factory=list)


@dataclass
class OrchestrationTemplate:
    id: str
    name: str
    description: str
    stages: List[TemplateStage]


BUILTIN_TEMPLATES: Dict[str, OrchestrationTemplate] = {
    "research-write": OrchestrationTemplate(
        id="research-write",
        name="调研与写作",
        description="researcher 调研 → writer 成文（两阶段串行）",
        stages=[
            TemplateStage(
                id="t1",
                agent_id="researcher",
                goal="调研 {request}，收集事实与数据，产出结构化要点",
            ),
            TemplateStage(
                id="t2",
                agent_id="writer",
                goal="基于调研要点撰写完整成文：{request}",
                depends_on=["t1"],
            ),
        ],
    ),
    "gather-analyze-report": OrchestrationTemplate(
        id="gather-analyze-report",
        name="收集-分析-报告",
        description="researcher 收集 → researcher 分析 → writer 报告（三阶段串行）",
        stages=[
            TemplateStage(
                id="t1",
                agent_id="researcher",
                goal="收集与 {request} 相关的资料、数据与引用",
            ),
            TemplateStage(
                id="t2",
                agent_id="researcher",
                goal="分析已收集资料，提炼洞察与结论：{request}",
                depends_on=["t1"],
            ),
            TemplateStage(
                id="t3",
                agent_id="writer",
                goal="将分析结论整理成结构化报告：{request}",
                depends_on=["t1", "t2"],
            ),
        ],
    ),
}


def get_template(template_id: str) -> Optional[OrchestrationTemplate]:
    return BUILTIN_TEMPLATES.get(template_id)


def list_templates() -> List[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "stages": [s.id for s in t.stages],
        }
        for t in BUILTIN_TEMPLATES.values()
    ]
