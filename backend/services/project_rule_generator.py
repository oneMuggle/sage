"""项目专属规则生成器（2026-10-27）。

基于 ``CodebaseProfile`` + 用户确认的 ``AnalysisReport``，产出可落库的约束草稿：
- 模板规则：复用 ``CONSTRAINT_TEMPLATES`` 中的既有模板
- 专属规则：LLM 从实际代码风格推导；LLM 不可用时走确定性启发

去重：内容归一化（折叠空白 + 小写）后与项目已有约束比对，重复项跳过。

调用链:
  API route -> ProjectRuleGenerator.generate(profile, report, existing) -> RuleGenerationResult
  前端采纳 -> ProjectConstraintRepository.create()
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from backend.data.project_constraint_repo import CONSTRAINT_TEMPLATES
from backend.services.llm_json import parse_json
from backend.services.project_analysis_agent import AnalysisReport
from backend.services.project_archetype_scaffold import ARCHETYPE_BLUEPRINTS
from backend.services.project_profiler import CodebaseProfile

logger = logging.getLogger(__name__)

#: 单次生成最多产出的专属规则数
MAX_CUSTOM_RULES = 8

#: 规则来源标记
SOURCE_TEMPLATE = "template"
SOURCE_AI_CUSTOM = "ai_custom"


@dataclass
class RuleDraft:
    """一条待落库的约束草稿。"""

    category: str
    content: str
    trigger_pattern: str
    priority: int
    source: str
    template_key: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "content": self.content,
            "trigger_pattern": self.trigger_pattern,
            "priority": self.priority,
            "source": self.source,
            "template_key": self.template_key,
            "reason": self.reason,
        }


@dataclass
class RuleGenerationResult:
    """规则生成结果。"""

    rules: List[RuleDraft] = field(default_factory=list)
    milestones: List[Dict[str, str]] = field(default_factory=list)
    llm_available: bool = True
    skipped_duplicates: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rules": [r.to_dict() for r in self.rules],
            "milestones": [dict(m) for m in self.milestones],
            "llm_available": self.llm_available,
            "skipped_duplicates": self.skipped_duplicates,
        }


class ProjectRuleGenerator:
    """项目专属规则生成器。"""

    def __init__(self, llm_client: Any = None) -> None:
        """初始化。

        Args:
            llm_client: 暴露 ``async complete(prompt) -> str`` 的 LLM 客户端。
                为 None 时从 settings 自动构建。
        """
        if llm_client is not None:
            self._llm: Any = llm_client
        else:
            from backend.orchestration.llm_factory import (
                build_llm_client_from_settings,
            )
            self._llm = build_llm_client_from_settings()

    @property
    def available(self) -> bool:
        """LLM 客户端是否可用。"""
        return self._llm is not None

    async def generate(
        self,
        profile: CodebaseProfile,
        report: AnalysisReport,
        existing_contents: Optional[Iterable[str]] = None,
    ) -> RuleGenerationResult:
        """生成规则草稿。

        Args:
            profile: 代码库画像
            report: 用户已确认的分析报告
            existing_contents: 项目已有约束正文（用于去重）

        Returns:
            ``RuleGenerationResult``；LLM 异常时降级但不抛错
        """
        seen: Set[str] = {
            _normalize(content) for content in (existing_contents or []) if content
        }
        skipped = 0
        rules: List[RuleDraft] = []

        # 1. 模板规则
        for suggested in report.suggested_rules:
            if suggested.template_key == "ai_custom":
                continue
            content = suggested.content or _first_template_content(
                suggested.template_key
            )
            if not content:
                continue
            key = _normalize(content)
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            rules.append(
                RuleDraft(
                    category=suggested.category,
                    content=content,
                    trigger_pattern=suggested.trigger_pattern,
                    priority=suggested.priority,
                    source=SOURCE_TEMPLATE,
                    template_key=suggested.template_key,
                    reason=suggested.reason,
                )
            )

        # 2. 专属规则
        custom_rules: List[RuleDraft] = []
        llm_available = False
        if self.available:
            try:
                custom_rules = await self._generate_custom_rules(profile, report)
                llm_available = True
            except Exception as exc:
                logger.warning(
                    "LLM rule generation failed, falling back: %s",
                    exc,
                    exc_info=True,
                )
                custom_rules = _heuristic_custom_rules(profile)
        else:
            custom_rules = _heuristic_custom_rules(profile)

        for draft in custom_rules[:MAX_CUSTOM_RULES]:
            key = _normalize(draft.content)
            if not key or key in seen:
                skipped += 1
                continue
            seen.add(key)
            rules.append(draft)

        return RuleGenerationResult(
            rules=rules,
            milestones=_recommend_milestones(report, profile),
            llm_available=llm_available,
            skipped_duplicates=skipped,
        )

    # ── LLM 路径 ────────────────────────────────────────────────────────

    async def _generate_custom_rules(
        self, profile: CodebaseProfile, report: AnalysisReport
    ) -> List[RuleDraft]:
        """调用 LLM 生成项目专属规则。"""
        prompt = _build_custom_rules_prompt(profile, report)
        raw = await self._llm.complete(prompt)
        try:
            obj = parse_json(raw)
        except ValueError as exc:
            raise RuntimeError(f"LLM 响应中未找到 JSON: {exc}") from exc

        drafts: List[RuleDraft] = []
        for item in (obj.get("custom_rules") or [])[:MAX_CUSTOM_RULES]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            drafts.append(
                RuleDraft(
                    category=str(item.get("category") or "coding_style"),
                    content=content,
                    trigger_pattern=str(item.get("trigger_pattern") or "always"),
                    priority=_clamp_priority(item.get("priority", 5)),
                    source=SOURCE_AI_CUSTOM,
                    template_key="ai_custom",
                    reason=str(item.get("reason") or ""),
                )
            )
        return drafts


# ── 辅助函数 ────────────────────────────────────────────────────────────────


def _normalize(content: str) -> str:
    """归一化约束正文用于去重（折叠空白 + 小写）。"""
    return re.sub(r"\s+", " ", content).strip().lower()


def _first_template_content(template_key: str) -> str:
    """取模板首条约束正文。"""
    templates = CONSTRAINT_TEMPLATES.get(template_key, [])
    if not templates:
        return ""
    return str(templates[0].get("content", ""))


def _clamp_priority(value: Any) -> int:
    """将 priority 钳位到 [1, 10]。"""
    try:
        i = int(value)
    except (TypeError, ValueError):
        return 5
    return max(1, min(10, i))


def _build_custom_rules_prompt(
    profile: CodebaseProfile, report: AnalysisReport
) -> str:
    """构造专属规则生成 prompt。"""
    samples_text = "\n\n".join(
        f"# {s.path} ({s.language})\n{s.content}" for s in profile.source_samples
    )
    lint = ", ".join(profile.lint_configs) or "无"
    tests = ", ".join(profile.test_frameworks) or "无"
    build = ", ".join(profile.build_commands[:5]) or "无"

    return f"""你是一位代码规范专家。请根据以下项目的**实际代码风格**，推导该项目的专属治理规则。

## 项目类型
{report.level1_type} / {report.sub_type or '未识别'}

## 技术栈
{', '.join(profile.tech_stack[:20])}

## 现有规范配置
- lint: {lint}
- 测试: {tests}
- 构建: {build}

## 架构摘要
{report.architecture_summary}

## 源码采样
{samples_text or '（无可采样源码）'}

## 任务
生成 3-6 条**项目专属**规则（不是通用模板，而是从上述代码特征推导出的具体约束）。
每条含：category / content（中文，一句话可执行）/ trigger_pattern / priority（1-10）/ reason（说明依据哪个检测信号）

## 输出格式（严格 JSON）
{{
  "custom_rules": [
    {{
      "category": "coding_style",
      "content": "...",
      "trigger_pattern": "*.py",
      "priority": 6,
      "reason": "..."
    }}
  ]
}}

注意：
- 只输出 JSON
- 规则之间不得重复
- content 必须能从源码特征中找到依据，不要泛泛而谈"""


def _heuristic_custom_rules(profile: CodebaseProfile) -> List[RuleDraft]:
    """确定性专属规则（LLM 不可用时）。"""
    drafts: List[RuleDraft] = []
    stack = {item.lower() for item in profile.tech_stack}
    has_tsx = any(
        sample.path.endswith((".tsx", ".ts")) for sample in profile.source_samples
    )

    if "python" in stack:
        drafts.append(
            RuleDraft(
                category="coding_style",
                content="Python 公共函数与类必须带类型注解与 docstring，遵守 PEP 8",
                trigger_pattern="*.py",
                priority=6,
                source=SOURCE_AI_CUSTOM,
                template_key="ai_custom",
                reason="检测到 Python 技术栈",
            )
        )
    if "typescript" in stack or has_tsx:
        drafts.append(
            RuleDraft(
                category="coding_style",
                content="TypeScript 禁止使用裸 any，组件 Props 必须显式声明 interface",
                trigger_pattern="*.ts*",
                priority=7,
                source=SOURCE_AI_CUSTOM,
                template_key="ai_custom",
                reason="检测到 TypeScript 源码",
            )
        )
    if "react" in stack:
        drafts.append(
            RuleDraft(
                category="architecture",
                content="前端组件遵循 pages -> widgets -> features -> shared 单向依赖，禁止跨层逆向导入",
                trigger_pattern="src/**",
                priority=8,
                source=SOURCE_AI_CUSTOM,
                template_key="ai_custom",
                reason="检测到 React 前端工程",
            )
        )
    if profile.lint_configs:
        lint_name = profile.lint_configs[0]
        drafts.append(
            RuleDraft(
                category="coding_style",
                content=f"提交前必须通过 {lint_name} 校验，不得以禁用规则方式绕过检查",
                trigger_pattern="always",
                priority=7,
                source=SOURCE_AI_CUSTOM,
                template_key="ai_custom",
                reason=f"检测到既有规范配置 {lint_name}",
            )
        )
    if profile.test_frameworks and not profile.ci_workflows:
        drafts.append(
            RuleDraft(
                category="testing",
                content="新增或修改核心逻辑必须补充单元测试，并在提交前本地跑通测试套件",
                trigger_pattern="always",
                priority=8,
                source=SOURCE_AI_CUSTOM,
                template_key="ai_custom",
                reason="检测到测试框架但无 CI 流水线",
            )
        )
    if profile.existing_rule_files:
        drafts.append(
            RuleDraft(
                category="architecture",
                content=(
                    f"与项目内既有规则文件（{profile.existing_rule_files[0]}）保持一致，"
                    "修改约束前先阅读该文件"
                ),
                trigger_pattern="always",
                priority=6,
                source=SOURCE_AI_CUSTOM,
                template_key="ai_custom",
                reason=f"检测到已有规则文件 {profile.existing_rule_files[0]}",
            )
        )
    return drafts[:MAX_CUSTOM_RULES]


def _recommend_milestones(
    report: AnalysisReport, profile: CodebaseProfile
) -> List[Dict[str, str]]:
    """推荐初始里程碑（复用 archetype blueprint）。"""
    key = report.level1_type if report.level1_type in ARCHETYPE_BLUEPRINTS else None
    if key is None:
        return []
    blueprint = ARCHETYPE_BLUEPRINTS[key]
    return [dict(item) for item in blueprint.default_milestones]


__all__ = [
    "MAX_CUSTOM_RULES",
    "ProjectRuleGenerator",
    "RuleDraft",
    "RuleGenerationResult",
    "SOURCE_AI_CUSTOM",
    "SOURCE_TEMPLATE",
]
