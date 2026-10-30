"""项目治理 AI 分析引擎（2026-10-27）。

接收 ``CodebaseProfile``，调用 LLM 生成 ``AnalysisReport``（含推荐规则、
治理建议、 sage.md 草稿）。LLM 不可用时走确定性降级：基于技术栈 → 模板映射
生成基础报告，端点始终返回 200。

调用链:
  API route -> ProjectAnalysisAgent.analyze(profile) -> AnalysisReport
  前端 ProjectAnalysisWizard 展示报告 -> 用户采纳规则 -> 写库
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.project_constraint_repo import CONSTRAINT_TEMPLATES
from backend.services.llm_json import parse_json
from backend.services.project_profiler import CodebaseProfile

logger = logging.getLogger(__name__)


# ── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class SuggestedRule:
    """LLM / 降级逻辑推荐的一条治理规则。"""

    template_key: str  # CONSTRAINT_TEMPLATES 中的 key，或 "ai_custom"
    label: str
    reason: str
    confidence: float
    category: str
    content: str
    trigger_pattern: str
    priority: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_key": self.template_key,
            "label": self.label,
            "reason": self.reason,
            "confidence": self.confidence,
            "category": self.category,
            "content": self.content,
            "trigger_pattern": self.trigger_pattern,
            "priority": self.priority,
        }


@dataclass
class DocRef:
    """推荐给用户的文档链接。"""

    title: str
    reason: str
    path: str

    def to_dict(self) -> Dict[str, str]:
        return {"title": self.title, "reason": self.reason, "path": self.path}


@dataclass
class AnalysisReport:
    """项目治理分析报告。"""

    level1_type: str
    sub_type: Optional[str]
    confidence: float
    tech_stack: List[str]
    architecture_summary: str
    suggested_rules: List[SuggestedRule]
    governance_recommendations: List[str]
    stage_recommendation: Optional[str]
    sage_md_draft: str
    docs_refs: List[DocRef]
    llm_available: bool = True
    raw_json: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level1_type": self.level1_type,
            "sub_type": self.sub_type,
            "confidence": self.confidence,
            "tech_stack": list(self.tech_stack),
            "architecture_summary": self.architecture_summary,
            "suggested_rules": [r.to_dict() for r in self.suggested_rules],
            "governance_recommendations": list(self.governance_recommendations),
            "stage_recommendation": self.stage_recommendation,
            "sage_md_draft": self.sage_md_draft,
            "docs_refs": [d.to_dict() for d in self.docs_refs],
            "llm_available": self.llm_available,
        }


# ── 降级规则映射（技术栈 → 模板 key）──────────────────────────────────────

#: tech_stack 命中关键词 → 推荐的 template_key 列表
_TECH_TO_TEMPLATE: Dict[str, List[str]] = {
    "python": ["python_default", "security_basic"],
    "pytest": ["python_default"],
    "fastapi": ["python_default", "architecture_guard"],
    "django": ["python_default", "architecture_guard"],
    "flask": ["python_default"],
    "sqlalchemy": ["security_basic"],
    "react": ["typescript_react", "typescript_strict"],
    "vue": ["typescript_strict"],
    "svelte": ["typescript_strict"],
    "next": ["typescript_react", "architecture_guard"],
    "nuxt": ["architecture_guard"],
    "electron": ["architecture_guard"],
    "tauri": ["architecture_guard"],
    "typescript": ["typescript_strict"],
    "pandas": ["python_default"],
    "numpy": ["python_default"],
    "torch": ["python_default"],
    "tensorflow": ["python_default"],
    "rust": ["security_basic"],
    "go": ["security_basic"],
    "java": ["security_basic"],
    "spring-boot": ["architecture_guard"],
    "pytest-cov": ["python_default"],
}

#: 项目 L1 → 兜底综合模板
_L1_TO_TEMPLATE: Dict[str, str] = {
    "coding": "coding",
    "research": "research",
    "business": "business",
    "personal": "personal",
}


# ── 对外入口 ────────────────────────────────────────────────────────────────


class ProjectAnalysisAgent:
    """项目治理 AI 分析引擎。"""

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
        """LLM 客户端是否可用（False 时走确定性降级）。"""
        return self._llm is not None

    async def analyze(
        self, profile: CodebaseProfile, *, allow_llm: bool = True
    ) -> AnalysisReport:
        """分析项目，返回治理报告。

        LLM 可用时优先 LLM 分析；LLM 不可用、被调用方禁用或调用失败时走
        确定性降级。永不抛出 LLM 相关异常——端点始终返回 200。

        Args:
            profile: ``CodebaseProfile``（来自 ``profile_project``）
            allow_llm: False 时跳过 LLM，直接返回确定性降级报告

        Returns:
            ``AnalysisReport``
        """
        if not allow_llm or not self.available:
            logger.info("LLM unavailable, falling back to deterministic rules")
            return self._fallback_report(profile, reason="llm_unavailable")

        try:
            prompt = self._build_prompt(profile)
            raw_response = await self._llm.complete(prompt)
            return self._parse_response(profile, raw_response)
        except Exception as exc:
            logger.warning(
                "LLM analyze failed, falling back: %s", exc, exc_info=True
            )
            return self._fallback_report(profile, reason="llm_error")

    # ── Prompt 构建 ─────────────────────────────────────────────────────

    def _build_prompt(self, profile: CodebaseProfile) -> str:
        """构造 LLM prompt。"""
        summary = _architecture_summary(profile)
        tech = ", ".join(profile.tech_stack[:30]) or "未识别"
        frameworks = ", ".join(profile.frameworks[:15]) or "无"
        tests = ", ".join(profile.test_frameworks) or "未识别"
        ci = ", ".join(profile.ci_workflows) or "无"
        rules = ", ".join(profile.existing_rule_files) or "无"
        samples_text = "\n\n".join(
            f"# {s.path} ({s.language})\n{s.content}"
            for s in profile.source_samples
        )

        return f"""你是一位资深的软件工程顾问，负责为新项目制定治理方案。

## 项目概况
- L1 类型: {profile.level1_type or '未识别'}
- L2 子类型: {profile.sub_type or '未识别'}
- 技术栈: {tech}
- 框架: {frameworks}
- 测试框架: {tests}
- CI: {ci}
- 已有 AI 规则文件: {rules}

## 架构摘要
{summary}

## 源码采样
{samples_text or '（无可采样源码）'}

## 任务
请基于上述画像，输出治理方案 JSON。要求：
1. ``suggested_rules`` 给出 5-10 条推荐规则，每条含：
   - ``template_key``：优先复用现有模板（coding / research / business / personal / python_default / typescript_react / typescript_strict / security_basic / academic_writing / architecture_guard / contract_review / document_format / concise_note_taking / citation_strict 等）；若无匹配填 "ai_custom"
   - ``label``：简短中文标签（≤20 字）
   - ``reason``：引用具体检测信号（如"检测到 pytest + 无 CI → 建议补充 GitHub Actions 门禁"）
   - ``confidence``：0.0-1.0
   - ``category``：coding_style / architecture / security / testing / academic_writing / document_format / note_structure / citation_integrity / legal_compliance 之一
   - ``content``：规则正文（template_key 非 ai_custom 时可留空字符串，由系统填入模板内容）
   - ``trigger_pattern``：触发 glob 或 "always"
   - ``priority``：1-10 整数
2. ``architecture_summary``：一句话架构总结（≤50 字）
3. ``governance_recommendations``：3-5 条治理建议（中文，可操作）
4. ``stage_recommendation``：建议的项目阶段（initiation / development / stabilization / maintenance）
5. ``sage_md_draft``：给该项目的 SAGE.md / CLAUDE.md 草稿（markdown 格式，含角色、约束、工作流）
6. ``docs_refs``：0-3 条相关文档引用，每条含 title / reason / path（path 为 docs/technical/ 下的相对路径）

## 输出格式（严格 JSON）
{{
  "architecture_summary": "...",
  "suggested_rules": [ ... ],
  "governance_recommendations": [ ... ],
  "stage_recommendation": "...",
  "sage_md_draft": "...",
  "docs_refs": [ ... ]
}}

注意：
- 只输出 JSON，不要额外说明
- suggested_rules 按 priority 降序"""

    # ── LLM 响应解析 ────────────────────────────────────────────────────

    def _parse_response(
        self, profile: CodebaseProfile, raw: str
    ) -> AnalysisReport:
        """解析 LLM 输出为 AnalysisReport。"""
        try:
            obj = parse_json(raw)
        except ValueError as exc:
            raise RuntimeError(
                f"LLM 响应中未找到 JSON: {exc}"
            ) from exc

        # 基础字段（来自 profile 的确定性部分）
        level1 = obj.get("level1_type") or profile.level1_type or "coding"
        sub_type = obj.get("sub_type") or profile.sub_type
        confidence = _clamp_confidence(obj.get("confidence", 0.75))
        tech_stack = list(obj.get("tech_stack") or profile.tech_stack)
        architecture_summary = str(
            obj.get("architecture_summary") or _architecture_summary(profile)
        )

        # 推荐规则
        rules_raw = obj.get("suggested_rules") or []
        suggested_rules = []
        for item in rules_raw[:15]:
            if not isinstance(item, dict):
                continue
            template_key = str(item.get("template_key") or "ai_custom")
            template_content = _lookup_template_content(template_key)
            content = str(item.get("content") or "") or template_content
            suggested_rules.append(
                SuggestedRule(
                    template_key=template_key,
                    label=str(item.get("label") or template_key),
                    reason=str(item.get("reason") or ""),
                    confidence=_clamp_confidence(item.get("confidence", 0.7)),
                    category=str(item.get("category") or "coding_style"),
                    content=content,
                    trigger_pattern=str(item.get("trigger_pattern") or "always"),
                    priority=_clamp_priority(item.get("priority", 5)),
                )
            )

        # 治理建议
        recs_raw = obj.get("governance_recommendations") or []
        governance_recommendations = [
            str(r) for r in recs_raw[:8] if isinstance(r, str) and r.strip()
        ]

        stage = obj.get("stage_recommendation")
        stage_recommendation = (
            str(stage)
            if stage in ("initiation", "development", "stabilization", "maintenance")
            else None
        )

        sage_md_draft = str(
            obj.get("sage_md_draft") or _default_sage_md_draft(profile)
        )

        # 文档引用
        docs_raw = obj.get("docs_refs") or []
        docs_refs = []
        for item in docs_raw[:5]:
            if not isinstance(item, dict):
                continue
            docs_refs.append(
                DocRef(
                    title=str(item.get("title") or ""),
                    reason=str(item.get("reason") or ""),
                    path=str(item.get("path") or ""),
                )
            )

        return AnalysisReport(
            level1_type=level1,
            sub_type=sub_type,
            confidence=confidence,
            tech_stack=tech_stack,
            architecture_summary=architecture_summary,
            suggested_rules=suggested_rules,
            governance_recommendations=governance_recommendations,
            stage_recommendation=stage_recommendation,
            sage_md_draft=sage_md_draft,
            docs_refs=docs_refs,
            llm_available=True,
            raw_json=raw,
        )

    # ── 确定性降级 ──────────────────────────────────────────────────────

    def _fallback_report(
        self, profile: CodebaseProfile, *, reason: str
    ) -> AnalysisReport:
        """LLM 不可用时的降级报告。

        规则映射来自 ``_TECH_TO_TEMPLATE`` + ``_L1_TO_TEMPLATE``，去重后组装。
        """
        level1 = profile.level1_type or "coding"
        sub_type = profile.sub_type
        tech_stack = list(profile.tech_stack)

        # 收集推荐模板 key（去重、按优先级截断）
        template_keys: List[str] = []
        for tech in tech_stack:
            for key in _TECH_TO_TEMPLATE.get(tech.lower(), []):
                if key not in template_keys:
                    template_keys.append(key)
        l1_fallback = _L1_TO_TEMPLATE.get(level1)
        if l1_fallback and l1_fallback not in template_keys:
            template_keys.insert(0, l1_fallback)

        # 构建 SuggestedRule 列表
        suggested_rules: List[SuggestedRule] = []
        for key in template_keys[:8]:
            templates = CONSTRAINT_TEMPLATES.get(key, [])
            for template in templates[:3]:
                suggested_rules.append(
                    SuggestedRule(
                        template_key=key,
                        label=_rule_label_for_template(key),
                        reason=(
                            f"基于文件特征推荐（{reason}）；"
                            f"技术栈信号: {_relevant_tech(tech_stack, key)}"
                        ),
                        confidence=0.55,
                        category=str(template.get("category", "coding_style")),
                        content=str(template.get("content", "")),
                        trigger_pattern=str(template.get("trigger_pattern", "always")),
                        priority=_clamp_priority(template.get("priority", 5)),
                    )
                )
        # 截断到 15 条
        suggested_rules = suggested_rules[:15]

        # 治理建议（确定性启发）
        governance_recommendations = _heuristic_recommendations(profile)

        # 阶段推荐
        stage_recommendation = _heuristic_stage(profile)

        # sage.md 草稿（默认模板填充）
        sage_md_draft = _default_sage_md_draft(profile)

        # 文档引用
        docs_refs = _heuristic_docs_refs(profile)

        return AnalysisReport(
            level1_type=level1,
            sub_type=sub_type,
            confidence=0.5,
            tech_stack=tech_stack,
            architecture_summary=_architecture_summary(profile),
            suggested_rules=suggested_rules,
            governance_recommendations=governance_recommendations,
            stage_recommendation=stage_recommendation,
            sage_md_draft=sage_md_draft,
            docs_refs=docs_refs,
            llm_available=False,
            raw_json=None,
        )


# ── 辅助函数 ────────────────────────────────────────────────────────────────


def _architecture_summary(profile: CodebaseProfile) -> str:
    """基于 profile 生成一句话架构摘要（LLM 与降级都可用）。"""
    frameworks = profile.frameworks[:3]
    lang_hints = {
        "python": "Python",
        "typescript": "TypeScript",
        "javascript": "JavaScript",
        "rust": "Rust",
        "go": "Go",
        "java": "Java",
        "kotlin": "Kotlin",
        "csharp": "C#",
        "ruby": "Ruby",
        "swift": "Swift",
        "php": "PHP",
    }
    langs = []
    stack_lower = {t.lower() for t in profile.tech_stack}
    for key, display in lang_hints.items():
        if key in stack_lower:
            langs.append(display)
    lang_text = " + ".join(langs[:3]) or "未知语言"
    framework_text = (
        f"，主框架 {', '.join(frameworks)}" if frameworks else ""
    )
    ci_text = (
        f"，含 {len(profile.ci_workflows)} 条 CI 流水线"
        if profile.ci_workflows
        else ""
    )
    test_text = (
        f"，测试框架 {', '.join(profile.test_frameworks[:3])}"
        if profile.test_frameworks
        else ""
    )
    return f"{lang_text} 项目{framework_text}{test_text}{ci_text}"


def _lookup_template_content(template_key: str) -> str:
    """查找模板 key 对应的首条约束正文（用于 LLM 未给 content 时填充）。"""
    templates = CONSTRAINT_TEMPLATES.get(template_key, [])
    if not templates:
        return ""
    return str(templates[0].get("content", ""))


def _rule_label_for_template(template_key: str) -> str:
    """为 template_key 生成友好标签。"""
    labels = {
        "python_default": "Python 默认规范",
        "typescript_react": "TypeScript/React 规范",
        "typescript_strict": "TypeScript 严格类型",
        "security_basic": "基础安全护栏",
        "academic_writing": "学术写作规范",
        "citation_strict": "零幻觉引用",
        "architecture_guard": "架构分层守护",
        "document_format": "文档版式规范",
        "contract_review": "合同审查规范",
        "concise_note_taking": "简明笔记法",
        "coding": "通用编码规范",
        "research": "科研写作规范",
        "business": "商务文档规范",
        "personal": "个人笔记规范",
        "grant_proposal": "课题申报书规范",
        "archive_dossier_cn": "中文归档案卷规范",
        "nsfc_grant_style": "国自然基金申请规范",
        "citation_zero_hallucination": "零幻觉引用铁律",
        "contract_compliance": "合同合规规范",
    }
    return labels.get(template_key, template_key.replace("_", " ").title())


def _relevant_tech(tech_stack: List[str], template_key: str) -> str:
    """为降级原因字段生成"相关技术栈"描述。"""
    related: Dict[str, List[str]] = {
        "python_default": ["python", "pytest", "fastapi", "django", "flask"],
        "typescript_react": ["react", "typescript", "next", "vite"],
        "typescript_strict": ["typescript", "vue", "svelte"],
        "security_basic": ["sqlalchemy", "python", "rust", "go", "java"],
        "academic_writing": ["pandoc", "latex", "jupyter"],
        "architecture_guard": [
            "react",
            "vue",
            "svelte",
            "fastapi",
            "django",
            "spring-boot",
            "electron",
        ],
    }
    keywords = related.get(template_key, [])
    hits = [t for t in tech_stack if t.lower() in keywords]
    return ", ".join(hits[:3]) if hits else "通用"


def _heuristic_recommendations(profile: CodebaseProfile) -> List[str]:
    """基于 profile 的确定性治理建议。"""
    recs: List[str] = []
    if not profile.ci_workflows:
        recs.append("建议补充 CI 流水线（GitHub Actions / GitLab CI），至少覆盖 lint + 测试")
    if not profile.test_frameworks and profile.level1_type == "coding":
        recs.append("未检测到测试框架，建议引入 pytest / vitest 并补充单元测试")
    if not profile.existing_rule_files:
        recs.append("建议创建 SAGE.md 或 CLAUDE.md 记录项目专属约束，便于 AI 协作")
    if profile.git_stats.dirty_files > 0:
        recs.append(
            f"当前有 {profile.git_stats.dirty_files} 个未提交改动，建议及时 commit 或 stash"
        )
    if not profile.lint_configs:
        recs.append("建议引入 linter（ruff / eslint / biome）统一代码风格")
    return recs[:5]


def _heuristic_stage(profile: CodebaseProfile) -> str:
    """基于 profile 的项目阶段推荐。"""
    commits = profile.git_stats.commit_count
    if commits == 0:
        return "initiation"
    if commits < 10:
        return "initiation"
    if commits < 50:
        return "development"
    return "stabilization"


def _heuristic_docs_refs(profile: CodebaseProfile) -> List[DocRef]:
    """基于 profile 的文档引用。"""
    refs: List[DocRef] = []
    tech_lower = {t.lower() for t in profile.tech_stack}

    if "python" in tech_lower:
        refs.append(
            DocRef(
                title="Python 项目规范",
                reason="检测到 Python 技术栈",
                path="docs/technical/44-python-code-protection.md",
            )
        )
    if "electron" in tech_lower:
        refs.append(
            DocRef(
                title="Electron 集成指南",
                reason="检测到 Electron 框架",
                path="docs/technical/20-electron.md",
            )
        )
    if profile.test_frameworks:
        refs.append(
            DocRef(
                title="前端质量门禁",
                reason="建议补充测试覆盖与质量检查",
                path="docs/technical/17-frontend-quality.md",
            )
        )
    if any(key in tech_lower for key in ("fastapi", "django", "flask")):
        refs.append(
            DocRef(
                title="Hexagonal Architecture",
                reason="后端项目建议参考六边形架构约束",
                path="docs/technical/18-hexagonal.md",
            )
        )
    if any(key in tech_lower for key in ("react", "vue", "svelte", "next", "nuxt")):
        refs.append(
            DocRef(
                title="质量门禁",
                reason="前端项目建议设置质量门禁",
                path="docs/technical/15-quality-gates.md",
            )
        )
    return refs[:3]


def _default_sage_md_draft(profile: CodebaseProfile) -> str:
    """生成默认 SAGE.md / CLAUDE.md 骨架（LLM 不可用时）。"""
    level1 = profile.level1_type or "coding"
    tech = ", ".join(profile.tech_stack[:10]) or "未知"
    frameworks = ", ".join(profile.frameworks[:5]) or "无"
    tests = ", ".join(profile.test_frameworks) or "未设置"

    project_role = {
        "coding": "软件开发",
        "research": "科研写作",
        "business": "商务文档",
        "personal": "个人知识管理",
    }.get(level1, "软件工程")

    constraints = {
        "coding": (
            "- 代码遵循 PEP 8 / Airbnb JS Style\n"
            "- 函数不超过 50 行，文件不超过 800 行\n"
            "- 禁止硬编码密钥\n"
            "- 所有输入必须校验\n"
        ),
        "research": (
            "- 严禁虚构参考文献\n"
            "- 使用 APA/IEEE/GB-T7714 引用格式\n"
            "- 实验记录含日期、方法、结果、分析\n"
        ),
        "business": (
            "- 文档遵循标准版式\n"
            "- 案卷须标注保密等级\n"
            "- 金额/日期大小写一致\n"
        ),
        "personal": (
            "- 笔记结论先行、一卡一概念\n"
            "- 隐私信息脱敏\n"
            "- 待办标注优先级与下一步动作\n"
        ),
    }.get(level1, "- 遵循通用软件工程最佳实践\n")

    return f"""# 项目约定

## 项目角色
本项目为 **{project_role}** 类型。

## 技术栈
- 语言: {tech}
- 框架: {frameworks}
- 测试: {tests}

## 核心约束
{constraints}
## 工作流
1. 修改代码前先阅读相关模块
2. 重大改动先编写计划（docs/plans/）
3. 写完代码后补充测试
4. 提交前跑 lint + test
5. commit message 遵循 Conventional Commits

## 文件组织
- `src/` — 主源码
- `tests/` — 测试
- `docs/` — 文档
"""


def _clamp_confidence(value: Any) -> float:
    """将 confidence 钳位到 [0.0, 1.0]。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, f))


def _clamp_priority(value: Any) -> int:
    """将 priority 钳位到 [1, 10]。"""
    try:
        i = int(value)
    except (TypeError, ValueError):
        return 5
    return max(1, min(10, i))


__all__ = [
    "AnalysisReport",
    "DocRef",
    "ProjectAnalysisAgent",
    "SuggestedRule",
]
