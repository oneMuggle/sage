# Sage - 技能系统

> **P2 备注（2026-06-06）**：技能系统已纳入六边形架构（`SkillPort` Protocol）。
> 生产 adapter 计划在 PG3 实现；当前业务调用链详见 [`docs/technical/18-hexagonal.md`](./technical/18-hexagonal.md)。

## 7.1 技能系统概述

### 7.1.1 设计理念

技能 (Skills) 是一种高级能力封装，让用户可以通过自然语言触发复杂的多步骤任务。

参考 Hermes Agent 的 `skills/` + agency-agents 架构。

### 7.1.2 技能 vs 工具

| 维度     | 工具 (Tool)  | 技能 (Skill)       |
| -------- | ------------ | ------------------ |
| 粒度     | 单操作       | 多步骤流程         |
| 调用方式 | AI 自动判断  | 关键词/意图触发    |
| 复杂度   | 低           | 高                 |
| 自主性   | AI 决定      | 预设流程           |
| 示例     | 读文件、搜索 | 写文章、做旅行计划 |

---

## 7.2 技能架构

### 7.2.1 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Skill System                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────┐   ┌─────────────────┐                   │
│   │  SkillManager   │   │  SkillStore     │                   │
│   │   (管理器)      │   │   (商店)        │                   │
│   └────────┬────────┘   └────────┬────────┘                   │
│            │                      │                              │
│            ▼                      ▼                              │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                      Skill Registry                       │  │
│   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │  │
│   │  │ search  │ │ writer  │ │  coder  │ │ travel  │ ...   │  │
│   │  └─────────┘ └─────────┘ └─────────┘ └─────────┘     │  │
│   │                                                          │  │
│   │  Skill = Trigger + Execute + Schema                     │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2.2 技能执行流程

```
用户: "帮我规划一个北京三日游"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Intent Detection (意图检测)                                │
│    - 关键词匹配: "规划", "旅游", "游"                       │
│    - 意图分类: travel_planning                              │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Skill Matching (技能匹配)                                  │
│    - 找到: travel_skill                                      │
│    - 检查: 已启用? 权限足够?                                  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Skill Execution (技能执行)                                │
│                                                              │
│    travel_skill.execute(params={                              │
│      "destination": "北京",                                   │
│      "days": 3,                                              │
│      "budget": null                                          │
│    })                                                        │
│                                                              │
│    ┌─────────────────────────────────────────────────────┐  │
│    │ Step 1: 搜索目的地信息                                │  │
│    │ Step 2: 生成每日行程                                   │  │
│    │ Step 3: 推荐餐厅/住宿                                  │  │
│    │ Step 4: 整合输出                                       │  │
│    └─────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
旅行规划已生成:
Day 1: 天安门 → 故宫 → 王府井
Day 2: 长城 → 鸟巢
Day 3: 颐和园 → 北大
```

---

## 7.3 技能定义

### 7.3.1 技能基类

```python
# backend/skills/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json

@dataclass
class SkillSchema:
    """技能 Schema"""
    name: str
    description: str
    triggers: List[str]  # 触发关键词
    parameters: Dict[str, Any]  # JSON Schema
    examples: List[str] = field(default_factory=list)

class BaseSkill(ABC):
    """技能基类"""

    def __init__(self):
        self._schema = self._build_schema()

    @property
    def schema(self) -> SkillSchema:
        return self._schema

    @abstractmethod
    def _build_schema(self) -> SkillSchema:
        """构建技能 Schema"""
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any], context: Dict) -> Dict[str, Any]:
        """
        执行技能

        Args:
            params: 技能参数
            context: 执行上下文 (包含 agent, memory 等)

        Returns:
            执行结果
        """
        pass

    def match(self, text: str) -> bool:
        """检查文本是否匹配技能触发词"""
        text_lower = text.lower()
        for trigger in self.schema.triggers:
            if trigger.lower() in text_lower:
                return True
        return False
```

### 7.3.2 技能注册表

```python
# backend/skills/registry.py
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

class SkillRegistry:
    """技能注册表"""

    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill):
        """注册技能"""
        self._skills[skill.schema.name] = skill
        logger.info(f"注册技能: {skill.schema.name}")

    def unregister(self, name: str):
        """取消注册"""
        if name in self._skills:
            del self._skills[name]

    def get(self, name: str) -> Optional[BaseSkill]:
        """获取技能"""
        return self._skills.get(name)

    def list(self) -> List[SkillSchema]:
        """列出所有技能"""
        return [skill.schema for skill in self._skills.values()]

    def find_matching(self, text: str) -> Optional[BaseSkill]:
        """查找匹配的技能"""
        for skill in self._skills.values():
            if skill.match(text):
                return skill
        return None

    def match_all(self, text: str) -> List[BaseSkill]:
        """查找所有匹配的技能"""
        return [skill for skill in self._skills.values() if skill.match(text)]
```

---

## 7.4 内置技能

### 7.4.1 搜索技能

```python
# backend/skills/builtin/search.py
from typing import Dict, Any, List
from ..base import BaseSkill, SkillSchema

class SearchSkill(BaseSkill):
    """搜索技能 - 网络搜索并整理结果"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="search",
            description="搜索网络信息并整理结果",
            triggers=["搜索", "查一下", "找一下", "search", "lookup"],
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "结果数量",
                        "default": 5
                    }
                },
                "required": ["query"]
            },
            examples=[
                "帮我搜索一下 Python 异步编程",
                "查一下 ChatGPT 最新消息"
            ]
        )

    async def execute(self, params: Dict[str, Any], context: Dict) -> Dict[str, Any]:
        """执行搜索"""
        query = params.get("query")
        limit = params.get("limit", 5)

        # 获取 web_search 工具
        web_search = context.get("tools", {}).get("web_search")
        if not web_search:
            return {"success": False, "error": "搜索工具不可用"}

        # 执行搜索
        result = await web_search.execute(query=query, limit=limit)

        # 格式化结果
        if result.get("success"):
            formatted = self._format_results(result.get("results", []))
            return {
                "success": True,
                "query": query,
                "results": formatted,
                "count": len(result.get("results", []))
            }

        return result

    def _format_results(self, results: List[Dict]) -> str:
        """格式化搜索结果"""
        if not results:
            return "没有找到相关结果。"

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.get('title', '无标题')}**")
            lines.append(f"   {r.get('snippet', '')}")
            lines.append(f"   🔗 {r.get('url', '')}")
            lines.append("")

        return "\n".join(lines)
```

### 7.4.2 写作技能

```python
# backend/skills/builtin/writer.py
from typing import Dict, Any, List
from ..base import BaseSkill, SkillSchema

class WriterSkill(BaseSkill):
    """写作技能 - 根据要求生成各类文本"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="writer",
            description="帮助用户撰写文章、文案、报告等文本内容",
            triggers=["写", "撰写", "编写", "生成文章", "write", "compose"],
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["article", "email", "report", "social", "other"],
                        "description": "文章类型"
                    },
                    "topic": {
                        "type": "string",
                        "description": "主题或话题"
                    },
                    "length": {
                        "type": "string",
                        "enum": ["short", "medium", "long"],
                        "description": "文章长度",
                        "default": "medium"
                    },
                    "tone": {
                        "type": "string",
                        "description": "写作风格/语气",
                        "default": "professional"
                    }
                },
                "required": ["type", "topic"]
            },
            examples=[
                "写一封商务邮件",
                "帮我写一篇关于 AI 的文章"
            ]
        )

    async def execute(self, params: Dict[str, Any], context: Dict) -> Dict[str, Any]:
        """执行写作"""
        article_type = params.get("type")
        topic = params.get("topic")
        length = params.get("length", "medium")
        tone = params.get("tone", "professional")

        # 构建写作提示
        prompt = self._build_prompt(article_type, topic, length, tone)

        # 调用 LLM 生成
        llm = context.get("llm")
        if not llm:
            return {"success": False, "error": "LLM 不可用"}

        result = await llm.complete(prompt)

        return {
            "success": True,
            "type": article_type,
            "topic": topic,
            "content": result,
            "metadata": {
                "length": length,
                "tone": tone
            }
        }

    def _build_prompt(
        self,
        article_type: str,
        topic: str,
        length: str,
        tone: str
    ) -> str:
        """构建写作提示"""
        length_map = {
            "short": "100-200 字",
            "medium": "500-800 字",
            "long": "1500-2000 字"
        }

        prompts = {
            "article": f"请撰写一篇关于「{topic}」的{length_map[length]}文章，"
                      f"语气{tone}，结构清晰，有理有据。",
            "email": f"请撰写一封关于「{topic}」的商务邮件，语气{tone}，格式规范。",
            "report": f"请撰写一份关于「{topic}」的分析报告，"
                     f"约{length_map[length]}，{tone}风格，包含数据和结论。",
            "social": f"请为社交媒体撰写一条关于「{topic}」的帖子，"
                     f"约100字，语气{tone}，有吸引力。",
        }

        return prompts.get(article_type, prompts["article"])
```

### 7.4.3 编程技能

````python
# backend/skills/builtin/coder.py
from typing import Dict, Any, List
from ..base import BaseSkill, SkillSchema

class CoderSkill(BaseSkill):
    """编程技能 - 代码编写、调试、解释"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="coder",
            description="帮助编写、调试、解释代码",
            triggers=["写代码", "编程", "debug", "代码", "program"],
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["write", "explain", "debug", "review", "refactor"],
                        "description": "操作类型"
                    },
                    "language": {
                        "type": "string",
                        "description": "编程语言，如 python, javascript"
                    },
                    "code": {
                        "type": "string",
                        "description": "代码内容 (debug/review 时需要)"
                    },
                    "requirement": {
                        "type": "string",
                        "description": "需求描述 (write 时需要)"
                    }
                },
                "required": ["action"]
            },
            examples=[
                "帮我写一个 Python 快速排序",
                "解释一下这段代码",
                "debug 这段 JavaScript"
            ]
        )

    async def execute(self, params: Dict[str, Any], context: Dict) -> Dict[str, Any]:
        """执行编程任务"""
        action = params.get("action")
        language = params.get("language", "python")
        code = params.get("code", "")
        requirement = params.get("requirement", "")

        llm = context.get("llm")
        if not llm:
            return {"success": False, "error": "LLM 不可用"}

        # 构建提示
        if action == "write":
            prompt = f"请用 {language} 实现以下功能:\n{requirement}"
        elif action == "explain":
            prompt = f"请解释以下 {language} 代码:\n```\n{code}\n```"
        elif action == "debug":
            prompt = f"请找出并修复以下 {language} 代码的问题:\n```\n{code}\n```"
        elif action == "review":
            prompt = f"请审查以下 {language} 代码并提出改进建议:\n```\n{code}\n```"
        elif action == "refactor":
            prompt = f"请重构以下 {language} 代码:\n```\n{code}\n```"
        else:
            return {"success": False, "error": f"未知操作: {action}"}

        result = await llm.complete(prompt)

        return {
            "success": True,
            "action": action,
            "language": language,
            "content": result
        }
````

### 7.4.4 旅行规划技能

```python
# backend/skills/builtin/travel.py
from typing import Dict, Any, List
from ..base import BaseSkill, SkillSchema

class TravelSkill(BaseSkill):
    """旅行规划技能"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="travel",
            description="规划旅行行程、推荐景点餐厅",
            triggers=["旅行", "旅游", "规划行程", "去哪玩", "travel", "trip"],
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
                "去上海玩两天，有什么推荐"
            ]
        )

    async def execute(self, params: Dict[str, Any], context: Dict) -> Dict[str, Any]:
        """执行旅行规划"""
        destination = params.get("destination")
        days = params.get("days", 3)
        budget = params.get("budget", "medium")
        style = params.get("style", "sightseeing")

        llm = context.get("llm")
        web_search = context.get("tools", {}).get("web_search")

        # 1. 搜索目的地信息
        attractions = []
        if web_search:
            result = await web_search.execute(
                query=f"{destination} 必游景点 {days}天",
                limit=10
            )
            if result.get("success"):
                attractions = result.get("results", [])

        # 2. 生成行程
        if llm:
            prompt = f"""请为 {destination} 规划一个 {days} 天的旅行行程。

预算: {budget}
风格: {style}

请按天输出，包含:
1. 每日景点安排
2. 推荐餐厅
3. 住宿建议
4. 交通提示

格式清晰，适合直接使用。"""

            itinerary = await llm.complete(prompt)
        else:
            itinerary = f"目的地: {destination}\n天数: {days}\n(LLM 不可用，仅提供基本信息)"

        return {
            "success": True,
            "destination": destination,
            "days": days,
            "budget": budget,
            "style": style,
            "itinerary": itinerary,
            "attractions": attractions
        }
```

---

## 7.5 技能管理器

### 7.5.1 SkillManager

```python
# backend/skills/manager.py
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

class SkillManager:
    """技能管理器"""

    def __init__(self, registry, skill_db):
        self.registry = registry
        self.db = skill_db  # SQLite 连接

    async def execute_skill(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Dict
    ) -> Dict[str, Any]:
        """执行技能"""
        skill = self.registry.get(skill_name)
        if not skill:
            return {"success": False, "error": f"技能不存在: {skill_name}"}

        # 检查是否启用
        if not self.is_enabled(skill_name):
            return {"success": False, "error": f"技能未启用: {skill_name}"}

        try:
            result = await skill.execute(params, context)

            # 更新使用统计
            self._update_usage(skill_name, result.get("success", True))

            return result

        except Exception as e:
            logger.error(f"技能执行失败: {skill_name}, {e}")
            self._update_usage(skill_name, False)
            return {"success": False, "error": str(e)}

    def is_enabled(self, skill_name: str) -> bool:
        """检查技能是否启用"""
        cursor = self.db.cursor()
        cursor.execute(
            "SELECT is_enabled FROM skills WHERE name = ?",
            (skill_name,)
        )
        row = cursor.fetchone()
        return row and row[0] == 1

    def enable(self, skill_name: str):
        """启用技能"""
        cursor = self.db.cursor()
        cursor.execute(
            "UPDATE skills SET is_enabled = 1 WHERE name = ?",
            (skill_name,)
        )
        self.db.commit()

    def disable(self, skill_name: str):
        """禁用技能"""
        cursor = self.db.cursor()
        cursor.execute(
            "UPDATE skills SET is_enabled = 0 WHERE name = ?",
            (skill_name,)
        )
        self.db.commit()

    def _update_usage(self, skill_name: str, success: bool):
        """更新使用统计"""
        cursor = self.db.cursor()
        cursor.execute("""
            UPDATE skills
            SET usage_count = usage_count + 1,
                success_count = success_count + ?,
                last_used_at = ?
            WHERE name = ?
        """, (1 if success else 0, int(time.time()), skill_name))
        self.db.commit()

    async def find_and_execute(self, text: str, context: Dict) -> Optional[Dict]:
        """查找匹配的技能并执行"""
        skill = self.registry.find_matching(text)
        if not skill:
            return None

        # 从文本中提取参数 (简化实现)
        params = self._extract_params(skill, text)

        return await self.execute_skill(skill.schema.name, params, context)

    def _extract_params(self, skill: BaseSkill, text: str) -> Dict[str, Any]:
        """从文本中提取参数 (简化实现)"""
        # TODO: 使用 LLM 或规则提取参数
        return {}
```

---

## 7.6 技能商店

### 7.6.1 商店设计

```python
# backend/skills/store.py
from typing import List, Dict, Any
import json

class SkillStore:
    """技能商店 - 第三方技能安装"""

    def __init__(self, store_url: str = None):
        self.store_url = store_url or "https://sage-skill-store.example.com"

    async def list_skills(self) -> List[Dict[str, Any]]:
        """获取商店技能列表"""
        # TODO: 从商店 API 获取
        return [
            {
                "name": "image_generator",
                "description": "AI 图片生成技能",
                "author": "Sage Team",
                "version": "1.0.0",
                "downloads": 1234,
                "rating": 4.5
            },
            {
                "name": "data_analyst",
                "description": "数据分析技能",
                "author": "Community",
                "version": "1.2.0",
                "downloads": 856,
                "rating": 4.2
            }
        ]

    async def install_skill(self, skill_name: str) -> bool:
        """安装技能"""
        # TODO: 下载技能代码，保存到数据库
        logger.info(f"安装技能: {skill_name}")
        return True

    async def uninstall_skill(self, skill_name: str) -> bool:
        """卸载技能"""
        # TODO: 从数据库删除
        logger.info(f"卸载技能: {skill_name}")
        return True
```

---

## 7.7 配置

### 7.7.1 技能配置

```yaml
# backend/config.yaml
skills:
  enabled_by_default: true

  builtin:
    - search
    - writer
    - coder
    - travel

  store:
    enabled: true
    url: 'https://sage-skill-store.example.com'
    auto_update: false
```

---

## 7.8 Hermes Skills 参考

### 7.8.1 Hermes 技能结构

```python
# Hermes skills/ 结构
skills/
├── README.md
├── skill_commands.py      # /skill 命令处理
├── skill_utils.py         # 技能工具函数
├── calculator/
│   ├── skill.md
│   └── execute.py
├── summarize/
│   ├── skill.md
│   └── execute.py
└── ...
```

---

_文档版本: v1.0_
