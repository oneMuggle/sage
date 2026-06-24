"""
写作技能 - 根据要求生成各类文本
"""

from __future__ import annotations

from typing import Any

from ..base import BaseSkill, SkillResult, SkillSchema


class WriterSkill(BaseSkill):
    """写作技能 - 根据要求生成各类文本"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="writer",
            description="帮助用户撰写文章、文案、报告等文本内容",
            triggers=["写", "帮我写", "创作", "write"],
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["article", "email", "report", "social", "other"],
                        "description": "文章类型",
                    },
                    "topic": {"type": "string", "description": "主题或话题"},
                    "style": {
                        "type": "string",
                        "description": "写作风格",
                        "default": "professional",
                    },
                    "length": {
                        "type": "string",
                        "enum": ["short", "medium", "long"],
                        "description": "文章长度",
                        "default": "medium",
                    },
                },
                "required": ["type", "topic"],
            },
            examples=["写一封商务邮件", "帮我写一篇关于 AI 的文章"],
        )

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """执行写作"""
        article_type = params.get("type")
        topic = params.get("topic")
        length = params.get("length", "medium")
        style = params.get("style", "professional")

        # 获取 LLM
        llm = context.get("llm")
        if llm is None:
            # 如果没有 LLM，返回提示信息
            return SkillResult(
                success=True,
                content=self._generate_mock_content(article_type, topic, length, style),
                metadata={
                    "type": article_type,
                    "topic": topic,
                    "length": length,
                    "style": style,
                    "mock": True,
                },
            )

        # 构建写作提示
        prompt = self._build_prompt(article_type, topic, length, style)

        try:
            # 调用 LLM 生成
            result = llm.complete(prompt)

            return SkillResult(
                content=result,
                metadata={"type": article_type, "topic": topic, "length": length, "style": style},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"写作失败: {str(e)}")

    def _build_prompt(self, article_type: str, topic: str, length: str, style: str) -> str:
        """构建写作提示"""
        length_map = {"short": "100-200 字", "medium": "500-800 字", "long": "1500-2000 字"}

        prompts = {
            "article": f"请撰写一篇关于「{topic}」的{length_map[length]}文章，"
            f"语气{style}，结构清晰，有理有据。",
            "email": f"请撰写一封关于「{topic}」的商务邮件，语气{style}，格式规范。",
            "report": f"请撰写一份关于「{topic}」的分析报告，"
            f"约{length_map[length]}，{style}风格，包含数据和结论。",
            "social": f"请为社交媒体撰写一条关于「{topic}」的帖子，"
            f"约100字，语气{style}，有吸引力。",
        }

        return prompts.get(article_type, prompts["article"])

    def _generate_mock_content(self, article_type: str, topic: str, length: str, style: str) -> str:
        """生成模拟内容（当没有 LLM 时）"""
        templates = {
            "article": f"# 关于「{topic}」的文章\n\n这是一篇关于{topic}的专业文章。\n\n## 概述\n{topic}是一个重要的话题，涉及到多个方面...\n\n## 详细内容\n本文将深入探讨{topic}的各个层面...",
            "email": f"主题：关于「{topic}」的商务沟通\n\n尊敬的先生/女士：\n\n我写信是为了与您讨论{topic}相关事宜...\n\n此致敬礼",
            "report": f"# 「{topic}」分析报告\n\n## 一、背景\n{topic}是当前重要议题...\n\n## 二、分析\n通过对{topic}的深入分析...\n\n## 三、结论与建议\n基于以上分析，我们建议...",
            "social": f"📢 {topic}\n\n今天想和大家分享关于{topic}的话题。\n\n#相关话题",
        }
        return templates.get(article_type, templates["article"])
