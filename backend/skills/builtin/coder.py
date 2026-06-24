"""
编程技能 - 代码编写、调试、解释
"""

from __future__ import annotations

from typing import Any

from ..base import BaseSkill, SkillResult, SkillSchema


class CoderSkill(BaseSkill):
    """编程技能 - 代码编写、调试、解释"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="coder",
            description="帮助编写、调试、解释代码",
            triggers=["写代码", "帮我写程序", "code"],
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["write", "explain", "debug", "review", "refactor"],
                        "description": "操作类型",
                    },
                    "language": {
                        "type": "string",
                        "description": "编程语言，如 python, javascript",
                    },
                    "code": {
                        "type": "string",
                        "description": "代码内容 (explain/debug/review 时需要)",
                    },
                    "requirement": {"type": "string", "description": "需求描述 (write 时需要)"},
                },
                "required": ["action"],
            },
            examples=["帮我写一个 Python 快速排序", "解释一下这段代码", "debug 这段 JavaScript"],
        )

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """执行编程任务"""
        action = params.get("action")
        language = params.get("language", "python")
        code = params.get("code", "")
        requirement = params.get("requirement", "")

        # 获取 LLM
        llm = context.get("llm")

        # 构建代码任务提示
        if action == "write":
            prompt = f"请用 {language} 实现以下功能:\n{requirement}"
        elif action == "explain":
            prompt = f"请解释以下 {language} 代码:\n```{language}\n{code}\n```"
        elif action == "debug":
            prompt = f"请找出并修复以下 {language} 代码的问题:\n```{language}\n{code}\n```"
        elif action == "review":
            prompt = f"请审查以下 {language} 代码并提出改进建议:\n```{language}\n{code}\n```"
        elif action == "refactor":
            prompt = f"请重构以下 {language} 代码:\n```{language}\n{code}\n```"
        else:
            return SkillResult(success=False, error=f"未知操作: {action}")

        # 如果没有 LLM，使用模拟结果
        if llm is None:
            return SkillResult(
                success=True,
                content=self._generate_mock_result(action, language, code, requirement),
                metadata={"action": action, "language": language, "mock": True},
            )

        try:
            result = llm.complete(prompt)
            return SkillResult(content=result, metadata={"action": action, "language": language})
        except Exception as e:
            return SkillResult(success=False, error=f"代码生成失败: {str(e)}")

    def _generate_mock_result(self, action: str, language: str, code: str, requirement: str) -> str:
        """生成模拟结果（当没有 LLM 时）"""
        templates = {
            "write": f"```{language}\n# {language} 代码示例\n# 根据需求: {requirement}\n\ndef example_function():\n    pass\n```",
            "explain": f"这段 {language} 代码的主要功能是...\n它包含以下部分:\n1. 函数定义\n2. 业务逻辑\n3. 返回值处理",
            "debug": "代码检查结果:\n- 语法正确\n- 请检查边界条件\n- 建议添加错误处理",
            "review": f"{language} 代码审查建议:\n1. 代码结构良好\n2. 建议添加注释\n3. 可以考虑性能优化",
            "refactor": f"重构后的 {language} 代码:\n```\n# 重构版本\n# 更清晰的结构和命名\n```",
        }
        return templates.get(action, templates["write"])
