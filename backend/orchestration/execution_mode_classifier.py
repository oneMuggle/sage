"""``execution_mode_classifier`` — 执行模式分类器（2026-10-28）。

LLM 驱动的轻量分类器，根据 plan.tasks 判断最佳执行模式：

- **single**：单 agent 串行执行（步骤少、强依赖链）
- **multi**：多 agent 并行编排（步骤多、有并行可能）
- **ask_user**：ambiguous 时让用户选择（confidence < 0.7）

分类结果驱动 PlanApprovalBar 的默认推荐，用户可覆盖。

降级纪律（硬约束）：分类是增强不是门槛 —— 无 LLM 配置、分类失败、响应解析
失败 → 降级为 ask_user（保守默认，让用户决定），绝不阻塞编排。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal

logger = logging.getLogger(__name__)

#: 执行模式
ExecutionMode = Literal["single", "multi", "ask_user"]

#: 匹配 ```json ... ``` / ``` ... ``` 围栏（部分模型会输出）
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

#: 计划原文注入 prompt 的截断上限（字符）—— 计划模式产出的是 markdown
#: 全文（目标/分步计划/验收标准/风险），分类只需其中可判定的部分。
MAX_PLAN_TEXT_CHARS = 4000


@dataclass
class ExecutionModeClassification:
    """执行模式分类结果。"""

    mode: ExecutionMode
    confidence: float
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


#: 分类 prompt —— 单次 LLM 调用判定执行模式
_CLASSIFY_PROMPT = """你是执行模式分类器。根据计划的步骤列表，判断最佳执行模式。

计划步骤:
{steps_summary}

执行模式定义:
- **single**: 单 agent 串行执行。适用：步骤少（< 3）、强依赖链（必须串行）、单文件修改
- **multi**: 多 agent 并行编排。适用：步骤多（>= 3）、多文件、有并行可能（独立步骤）
- **ask_user**: ambiguous 时让用户选择。适用：无法确定、用户可能需要特定模式

判断规则:
1. 步骤数 < 3 且无明显并行可能 → single
2. 步骤数 >= 3 且有独立步骤（无依赖或弱依赖） → multi
3. 所有步骤强依赖（长链）→ single
4. 跨文件数 > 5 → multi
5. ambiguous（confidence < 0.7）→ ask_user

只返回 JSON（无 markdown 围栏、无多余文本）:
{{"mode": "single|multi|ask_user", "confidence": 0.0-1.0, "reasoning": "一句话说明判断依据"}}

示例:
- 3 个步骤，强依赖链 → {{"mode": "single", "confidence": 0.9, "reasoning": "步骤强依赖，必须串行"}}
- 5 个步骤，2 个独立 → {{"mode": "multi", "confidence": 0.85, "reasoning": "有独立步骤可并行"}}
"""


class ExecutionModeClassifier:
    """执行模式分类器。

    用法::

        classifier = ExecutionModeClassifier()
        result = await classifier.classify(plan)
        print(result.mode)  # "single" | "multi" | "ask_user"
    """

    async def classify(self, plan: Any) -> ExecutionModeClassification:
        """分类执行模式。

        Args:
            plan: Plan 对象（包含 tasks 列表）。

        Returns:
            ExecutionModeClassification：模式 + 置信度 + 判断依据。

        降级策略：
            - 无 LLM 配置 → 返回 ask_user（保守默认）
            - LLM 调用失败 → 返回 ask_user
            - 响应解析失败 → 返回 ask_user
        """
        try:
            # 惰性导入：llm_factory 读 settings DB，保持与 plan_preflight 同款装配路径
            from backend.orchestration.llm_factory import build_llm_client_from_settings

            client = build_llm_client_from_settings()
            if client is None:
                logger.info("execution_mode_classifier: 无 LLM 配置，降级为 ask_user")
                return ExecutionModeClassification(
                    mode="ask_user",
                    confidence=0.0,
                    reasoning="无 LLM 配置，降级为 ask_user",
                )

            # 提取步骤摘要
            steps_summary = self._extract_steps_summary(plan)

            prompt = _CLASSIFY_PROMPT.replace("{steps_summary}", steps_summary)

            try:
                raw = await client.complete(prompt)
            except Exception as exc:  # noqa: BLE001 — 分类失败必须降级，绝不阻塞
                logger.warning(
                    "execution_mode_classifier LLM 调用失败，降级为 ask_user: %s", exc
                )
                return ExecutionModeClassification(
                    mode="ask_user",
                    confidence=0.0,
                    reasoning="LLM 调用失败，降级为 ask_user",
                )

            return self._parse_response(raw)

        except Exception:  # noqa: BLE001 — 分类器永不抛错
            logger.warning(
                "execution_mode_classifier 异常，降级为 ask_user", exc_info=True
            )
            return self._default_classification()

    def _extract_steps_summary(self, plan: Any) -> str:
        """提取步骤摘要。

        支持两种输入：
        - **Plan 对象**（含 ``.tasks``）—— 编排拆解路径，列出每步名称与依赖。
        - **计划原文**（str）—— 计划模式路径产出的是 markdown 全文，直接截断
          注入（分类只需读"分步计划"段落即可判定步骤数与依赖形态）。
        """
        try:
            if isinstance(plan, str):
                text = plan.strip()
                if not text:
                    return "无步骤"
                return text[:MAX_PLAN_TEXT_CHARS]

            tasks = plan.tasks if hasattr(plan, "tasks") else []
            if not tasks:
                return "无步骤"

            lines: List[str] = []
            for i, task in enumerate(tasks, 1):
                name = task.name if hasattr(task, "name") else f"Task {i}"
                blocked_by = task.blocked_by if hasattr(task, "blocked_by") else []
                dep_info = f" (依赖: {', '.join(blocked_by)})" if blocked_by else ""
                lines.append(f"{i}. {name}{dep_info}")

            return "\n".join(lines)
        except Exception:
            logger.warning("execution_mode_classifier: 提取步骤摘要失败", exc_info=True)
            return "步骤提取失败"

    def _parse_response(self, raw: Any) -> ExecutionModeClassification:
        """解析 LLM 响应 → ExecutionModeClassification。

        任何畸形（非 JSON / 字段缺失 / 字段值非法）→ 返回 ask_user 默认。
        """
        if not isinstance(raw, str) or not raw.strip():
            logger.warning("execution_mode_classifier: 空响应，降级为 ask_user")
            return ExecutionModeClassification(
                mode="ask_user",
                confidence=0.0,
                reasoning="空响应，降级为 ask_user",
            )

        # 剥离 markdown 围栏
        text = _CODE_FENCE_RE.sub("", raw.strip()).strip()

        try:
            import json

            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "execution_mode_classifier: JSON 解析失败，降级为 ask_user: %s", exc
            )
            return ExecutionModeClassification(
                mode="ask_user",
                confidence=0.0,
                reasoning="JSON 解析失败，降级为 ask_user",
            )

        if not isinstance(data, dict):
            logger.warning("execution_mode_classifier: 响应非 dict，降级为 ask_user")
            return ExecutionModeClassification(
                mode="ask_user",
                confidence=0.0,
                reasoning="响应非 dict，降级为 ask_user",
            )

        # 提取字段
        mode = data.get("mode")
        confidence = data.get("confidence")
        reasoning = data.get("reasoning", "")

        # 校验 mode
        if mode not in ("single", "multi", "ask_user"):
            logger.warning(
                "execution_mode_classifier: 非法 mode=%r，降级为 ask_user", mode
            )
            return ExecutionModeClassification(
                mode="ask_user",
                confidence=0.0,
                reasoning=f"非法 mode={mode!r}，降级为 ask_user",
            )

        # 校验 confidence（允许缺失，默认 0.5）
        # noqa UP038: py38 LTS 无法在运行期求值 PEP 604，必须保留 tuple 形式
        if not isinstance(confidence, (int, float)):  # noqa: UP038
            confidence = 0.5
        else:
            confidence = float(confidence)
            confidence = max(0.0, min(1.0, confidence))  # clamp to [0, 1]

        # 校验 reasoning
        if not isinstance(reasoning, str):
            reasoning = str(reasoning) if reasoning else ""

        return ExecutionModeClassification(
            mode=mode,
            confidence=confidence,
            reasoning=reasoning,
        )

    def _default_classification(self) -> ExecutionModeClassification:
        """保守默认：ask_user + confidence=0.0。"""
        return ExecutionModeClassification(
            mode="ask_user",
            confidence=0.0,
            reasoning="分类器降级为保守默认（ask_user）",
        )


async def classify_execution_mode(plan: Any) -> ExecutionModeClassification:
    """便捷函数：分类执行模式。

    与 ``ExecutionModeClassifier().classify()`` 等价，适合一次性调用。
    """
    classifier = ExecutionModeClassifier()
    return await classifier.classify(plan)
