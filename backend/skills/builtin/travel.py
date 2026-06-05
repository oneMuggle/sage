"""
旅行规划技能 - 规划旅行行程、推荐景点餐厅
"""
from typing import Any

from ..base import BaseSkill, SkillResult, SkillSchema


class TravelSkill(BaseSkill):
    """旅行规划技能"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="travel",
            description="规划旅行行程、推荐景点餐厅",
            triggers=["旅行", "旅游", "行程", "travel"],
            parameters={
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "description": "目的地"
                    },
                    "days": {
                        "type": "integer",
                        "description": "天数",
                        "default": 3
                    },
                    "budget": {
                        "type": "string",
                        "description": "预算水平: low, medium, high"
                    },
                    "style": {
                        "type": "string",
                        "description": "旅行风格: sightseeing, foodie, relax, adventure"
                    }
                },
                "required": ["destination"]
            },
            examples=[
                "帮我规划一个北京三日游",
                "去日本旅行有什么推荐"
            ]
        )

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """执行旅行规划"""
        destination = params.get("destination")
        days = params.get("days", 3)
        budget = params.get("budget", "medium")
        style = params.get("style", "sightseeing")

        # 获取 LLM
        llm = context.get("llm")

        # 构建旅行规划提示
        prompt = self._build_prompt(destination, days, budget, style)

        # 如果没有 LLM，使用模拟结果
        if llm is None:
            return SkillResult(
                success=True,
                content=self._generate_mock_travel_plan(destination, days, budget, style),
                metadata={
                    "destination": destination,
                    "days": days,
                    "budget": budget,
                    "style": style,
                    "mock": True
                }
            )

        try:
            result = llm.complete(prompt)
            return SkillResult(
                content=result,
                metadata={
                    "destination": destination,
                    "days": days,
                    "budget": budget,
                    "style": style
                }
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"旅行规划失败: {str(e)}"
            )

    def _build_prompt(self, destination: str, days: int, budget: str, style: str) -> str:
        """构建旅行规划提示"""
        style_map = {
            "sightseeing": "观光游览",
            "foodie": "美食探索",
            "relax": "休闲放松",
            "adventure": "冒险体验"
        }
        budget_map = {
            "low": "经济实惠",
            "medium": "中等消费",
            "high": "高端奢华"
        }

        return f"""请为以下条件规划一份{days}天的{destination}旅行行程:
- 预算: {budget_map.get(budget, '中等消费')}
- 风格: {style_map.get(style, '观光游览')}

请提供:
1. 每日行程安排
2. 推荐景点和餐厅
3. 交通建议
4. 注意事项"""

    def _generate_mock_travel_plan(self, destination: str, days: int, budget: str, style: str) -> str:
        """生成模拟旅行计划（当没有 LLM 时）"""
        plans = {
            1: """
# {destination} 一日游攻略

## 上午
- 抵达{destination}
- 游览市中心标志性景点

## 下午
- 品尝当地特色美食
- 逛一逛传统街区

## 晚上
- 欣赏城市夜景
- 返程
""",
            2: """
# {destination} 两日游攻略

## Day 1
- 上午: 抵达，办理入住
- 下午: 游览主要景点
- 晚上: 特色餐厅晚餐

## Day 2
- 上午: 深度探索
- 下午: 购物或休闲
- 晚上: 返程
""",
            3: """
# {destination} 三日游攻略

## Day 1: 抵达与初探
- 上午: 抵达{destination}，入住酒店
- 下午: 游览城市标志性景点
- 晚上: 在市中心品尝当地美食

## Day 2: 深度体验
- 上午: 前往热门景点游览
- 下午: 探索当地文化/博物馆
- 晚上: 夜市或特色活动

## Day 3: 休闲返程
- 上午: 轻松漫步或购物
- 下午: 整理行装，准备返程

## 预算参考
- 住宿: 根据预算选择经济型/舒适型/高端酒店
- 餐饮: 每天约 100-300 元
- 交通: 市内公共交通或打车约 50-100 元/天
- 门票: 景点门票约 200-500 元/天
"""
        }

        plan = plans.get(days, plans[3])
        return plan.format(destination=destination)
