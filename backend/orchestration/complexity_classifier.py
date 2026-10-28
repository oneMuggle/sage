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
