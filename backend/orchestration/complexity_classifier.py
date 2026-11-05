"""``complexity_classifier`` — 任务复杂度分类器（2026-10-28）。

LLM 驱动的轻量分类器，将用户任务分为三档：

- **simple**：跳过 scout，0 确认点，直接执行（修复 typo、改颜色）
- **medium**：scout_lite（4 轮），1 确认点（整体确认）（加按钮、重构函数）
- **complex**：scout_deep（WikiResearch），N 确认点（关键步骤前暂停）（设计认证系统、性能优化）

分类结果驱动后续调研深度和确认策略，实现"复杂度驱动"的 plan 流程。

降级纪律（硬约束）：分类是增强不是门槛 —— 无 LLM 配置、分类失败、响应解析
失败 → 降级为 medium（保守默认），绝不阻塞编排。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

logger = logging.getLogger(__name__)

#: 复杂度等级
ComplexityLevel = Literal["simple", "medium", "complex"]

#: 匹配 ```json ... ``` / ``` ... ``` 围栏（部分模型会输出）
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass
class ComplexityClassification:
    """复杂度分类结果。"""

    complexity: ComplexityLevel
    research_needed: bool
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "complexity": self.complexity,
            "research_needed": self.research_needed,
            "reasoning": self.reasoning,
        }


#: 分类 prompt —— 单次 LLM 调用同时判定复杂度 + 是否需要调研
_CLASSIFY_PROMPT = """你是任务复杂度分类器。根据用户目标和项目上下文，判断任务复杂度等级。

用户目标: {message}

项目上下文（可选）: {context}

复杂度等级定义:
- **simple**: 单文件、小范围修改、无外部依赖、无需调研。例如：修复 typo、改颜色、重命名变量
- **medium**: 多文件但逻辑清晰、可快速理解、无需深度调研。例如：加按钮、重构函数、修 bug
- **complex**: 跨模块、涉及架构决策、需要外部知识、或用户明确要求深度调研。例如：设计认证系统、性能优化、新子系统

判断规则:
1. 默认倾向 medium（保守默认），除非明显 simple 或明确 complex
2. 涉及文件数 > 5 或需要外部知识 → complex
3. 用户显式标记（如"深度调研"、"详细分析"） → complex
4. 单文件、改动局部、无需理解全局 → simple

只返回 JSON（无 markdown 围栏、无多余文本）:
{{"complexity": "simple|medium|complex", "research_needed": true|false, "reasoning": "一句话说明判断依据"}}

示例:
- 用户："修复 README 的 typo" → {{"complexity": "simple", "research_needed": false, "reasoning": "单文件局部修改"}}
- 用户："设计一个完整的认证系统" → {{"complexity": "complex", "research_needed": true, "reasoning": "架构决策 + 需要外部最佳实践"}}
"""


class ComplexityClassifier:
    """任务复杂度分类器。

    用法::

        classifier = ComplexityClassifier()
        result = await classifier.classify("修复 README typo", context=None)
        print(result.complexity)  # "simple"
    """

    async def classify(
        self,
        message: str,
        context: Optional[str] = None,
    ) -> ComplexityClassification:
        """分类用户任务复杂度。

        Args:
            message: 用户原始目标。
            context: 可选项目上下文（文件列表、最近修改等）。

        Returns:
            ComplexityClassification：复杂度 + 是否需调研 + 判断依据。

        降级策略：
            - 无 LLM 配置 → 返回 medium（保守默认）
            - LLM 调用失败 → 返回 medium
            - 响应解析失败 → 返回 medium
        """
        try:
            # 惰性导入：llm_factory 读 settings DB，保持与 plan_preflight 同款装配路径
            from backend.orchestration.llm_factory import build_llm_client_from_settings

            client = build_llm_client_from_settings()
            if client is None:
                logger.info("complexity_classifier: 无 LLM 配置，降级为 medium")
                return ComplexityClassification(
                    complexity="medium",
                    research_needed=False,
                    reasoning="无 LLM 配置，降级为 medium",
                )

            # 先替换 {context} 再替换 {message}：反序会让消息体里出现的
            # "{context}" 被二次替换成上下文，形成 prompt 注入面。
            prompt = _CLASSIFY_PROMPT.replace("{context}", context or "无").replace(
                "{message}", message
            )

            try:
                raw = await client.complete(prompt)
            except Exception as exc:  # noqa: BLE001 — 分类失败必须降级，绝不阻塞
                logger.warning(
                    "complexity_classifier LLM 调用失败，降级为 medium: %s", exc
                )
                return ComplexityClassification(
                    complexity="medium",
                    research_needed=False,
                    reasoning="LLM 调用失败，降级为 medium",
                )

            return self._parse_response(raw)

        except Exception:  # noqa: BLE001 — 分类器永不抛错
            logger.warning("complexity_classifier 异常，降级为 medium", exc_info=True)
            return ComplexityClassification(
                complexity="medium",
                research_needed=False,
                reasoning="分类器异常，降级为 medium",
            )

    def _parse_response(self, raw: Any) -> ComplexityClassification:
        """解析 LLM 响应 → ComplexityClassification。

        任何畸形（非 JSON / 字段缺失 / 字段值非法）→ 返回 medium 默认。
        """
        if not isinstance(raw, str) or not raw.strip():
            logger.warning("complexity_classifier: 空响应，降级为 medium")
            return ComplexityClassification(
                complexity="medium",
                research_needed=False,
                reasoning="空响应，降级为 medium",
            )

        # 剥离 markdown 围栏
        text = _CODE_FENCE_RE.sub("", raw.strip()).strip()

        try:
            import json

            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "complexity_classifier: JSON 解析失败，降级为 medium: %s", exc
            )
            return ComplexityClassification(
                complexity="medium",
                research_needed=False,
                reasoning="JSON 解析失败，降级为 medium",
            )

        if not isinstance(data, dict):
            logger.warning("complexity_classifier: 响应非 dict，降级为 medium")
            return ComplexityClassification(
                complexity="medium",
                research_needed=False,
                reasoning="响应非 dict，降级为 medium",
            )

        # 提取字段
        complexity = data.get("complexity")
        research_needed = data.get("research_needed")
        reasoning = data.get("reasoning", "")

        # 校验 complexity
        if complexity not in ("simple", "medium", "complex"):
            logger.warning(
                "complexity_classifier: 非法 complexity=%r，降级为 medium", complexity
            )
            return ComplexityClassification(
                complexity="medium",
                research_needed=False,
                reasoning=f"非法 complexity={complexity!r}，降级为 medium",
            )

        # 校验 research_needed（允许缺失，默认 True if complex else False）
        if not isinstance(research_needed, bool):
            research_needed = complexity == "complex"

        # 校验 reasoning
        if not isinstance(reasoning, str):
            reasoning = str(reasoning) if reasoning else ""

        return ComplexityClassification(
            complexity=complexity,
            research_needed=research_needed,
            reasoning=reasoning,
        )


async def classify_complexity(
    message: str,
    context: Optional[str] = None,
) -> ComplexityClassification:
    """便捷函数：分类任务复杂度。

    与 ``ComplexityClassifier().classify()`` 等价，适合一次性调用。
    """
    classifier = ComplexityClassifier()
    return await classifier.classify(message, context)


# ---------------------------------------------------------------------------
# 迭代预算分级（M4 · W4, 2026-11-05）
# ---------------------------------------------------------------------------

#: 预算档位 —— 与 ``iteration_budget.BudgetLevel`` 同构，但此处用字符串常量
#: 避免从 ``backend.core.legacy`` 反向导入（orchestration → core/legacy 依赖方向）。
BudgetLevelStr = Literal["simple", "medium", "complex", "long"]

#: 预算分级 prompt —— 专注于「迭代步数」估算，与 classify 的「调研深度」分离。
_BUDGET_ESTIMATE_PROMPT = """你是迭代预算估算器。根据用户任务估算需要的迭代步数档位。

用户目标: {message}

上下文信号:
{context_signals}

档位定义（每档对应一个迭代步数上限）:
- **simple**: ≤20 步。单文件小改、typo、改颜色、重命名变量、加一行配置
- **medium**: ≤80 步。多文件但逻辑清晰、修 bug、加按钮、重构单个函数
- **complex**: ≤200 步。跨模块重构、涉及架构决策、新子系统、性能优化
- **long**: ≤400 步。端到端大规模任务、批量处理、跨文件迁移、需要反复验证

判断规则:
1. 默认倾向 medium（保守默认），除非有明确信号指向其他档位
2. 涉及文件数 > 5 或需要多轮验证 → complex 或 long
3. 用户显式标记"长任务"/"批量"/"端到端" → long
4. 单文件局部修改、无外部依赖 → simple

只返回 JSON（无 markdown 围栏、无多余文本）:
{{"level": "simple|medium|complex|long", "reasoning": "一句话说明判断依据"}}
"""


async def estimate_budget_level(
    message: str,
    *,
    context_signals: Optional[str] = None,
    timeout_s: float = 8.0,
) -> Optional[tuple]:
    """LLM 预估任务复杂度 → 预算档位。

    与 ``classify_complexity`` 的区别：后者驱动 plan/scout 调研深度，本函数
    驱动迭代预算初始值。两者使用独立 prompt，降级互不影响。

    Args:
        message: 用户原始目标。
        context_signals: 可选上下文信号（多行文本），喂给 LLM 作为辅助判断。
            例如 ``"- 已绑定到项目工作区\\n- 用户提供了附件"``。
        timeout_s: LLM 调用超时（秒）。超时 → 返回 None（回落启发式）。

    Returns:
        ``(level, reasoning)`` 其中 level ∈ ``{"simple","medium","complex","long"}``。
        失败（无 LLM / 超时 / 解析错误 / 异常）→ 返回 None，调用方回落启发式。
    """
    import asyncio

    from backend.utils.py_compat import TIMEOUT_ERRORS

    try:
        from backend.orchestration.llm_factory import build_llm_client_from_settings

        client = build_llm_client_from_settings()
        if client is None:
            logger.info("estimate_budget_level: 无 LLM 配置，回落启发式")
            return None

        prompt = _BUDGET_ESTIMATE_PROMPT.replace(
            "{context_signals}", context_signals or "无特殊信号"
        ).replace("{message}", message)

        try:
            raw = await asyncio.wait_for(client.complete(prompt), timeout=timeout_s)
        except TIMEOUT_ERRORS:
            logger.warning(
                "estimate_budget_level: LLM 超时（%ss），回落启发式", timeout_s
            )
            return None
        except Exception as exc:  # noqa: BLE001 — 分类失败必须降级，绝不阻塞
            logger.warning(
                "estimate_budget_level: LLM 调用失败，回落启发式: %s", exc
            )
            return None

        return _parse_budget_response(raw)

    except Exception:  # noqa: BLE001 — 分类器永不抛错
        logger.warning(
            "estimate_budget_level 异常，回落启发式", exc_info=True
        )
        return None


def _parse_budget_response(raw: Any) -> Optional[tuple]:
    """解析 LLM 响应 → (level, reasoning)。失败返回 None。"""
    if not isinstance(raw, str) or not raw.strip():
        logger.warning("estimate_budget_level: 空响应，回落启发式")
        return None

    text = _CODE_FENCE_RE.sub("", raw.strip()).strip()

    try:
        import json

        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "estimate_budget_level: JSON 解析失败，回落启发式: %s", exc
        )
        return None

    if not isinstance(data, dict):
        logger.warning("estimate_budget_level: 响应非 dict，回落启发式")
        return None

    level = data.get("level")
    reasoning = data.get("reasoning", "")

    if level not in ("simple", "medium", "complex", "long"):
        logger.warning(
            "estimate_budget_level: 非法 level=%r，回落启发式", level
        )
        return None

    if not isinstance(reasoning, str):
        reasoning = str(reasoning) if reasoning else ""

    return (level, reasoning)
