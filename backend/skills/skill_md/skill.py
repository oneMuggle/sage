"""SKILL.md 文档数据类 + BaseSkill 包装。

设计要点
--------

- ``SkillMdDocument`` 是不可变的 dataclass, 承载一份 SKILL.md 文件解析后的全部信息。
  字段除 ``name`` / ``description`` 外都有默认值, 方便从部分 frontmatter 构造。
- ``SkillMdSkill`` 是 ``BaseSkill`` 的具体实现, 把 ``SkillMdDocument`` 暴露成
  注册表能识别的技能对象。它**不**调用任何 LLM / 工具 —— ``execute()`` 只是
  把 body 字符串和元数据原样返回, 由聊天层决定怎么拼到 system prompt。
  这是 v1 范围内"无副作用"的设计选择: 技能层只产提示词模板, 不消费 LLM quota。
- 镜像 ``backend/mcp/tool.py::McpTool`` 的"单资源包装类"模式 —— 一个
  ``SkillMdSkill`` 实例对应一个 SKILL.md 文件, 由 ``loader.py`` 负责批量构造。
- ``__repr__`` 沿用 ``BaseSkill.__repr__`` 的默认实现 (会输出 name + triggers),
  无需重写。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..base import BaseSkill, SkillResult, SkillSchema


@dataclass(frozen=True)
class RequiresSpec:
    """技能执行前置条件规格（v2）。"""
    bins: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    config: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DispatchMode:
    """调度控制元数据（v2）。"""
    disable_model_invocation: bool = False
    user_invocable: bool = False
    user_invocable_name: str | None = None
    command_dispatch: str = "auto"


@dataclass
class SkillMdDocument:
    """一份 SKILL.md 文件解析后的全部内容。"""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    base_dir: Path | None = None
    version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)

    # v2 新增字段（向后兼容）
    requires: RequiresSpec = field(default_factory=RequiresSpec)
    os: list[str] = field(default_factory=list)  # 平台过滤
    always: bool = False  # 跳过条件加载
    dispatch: DispatchMode = field(default_factory=DispatchMode)
    resources: Any | None = None  # ResourceIndex，由 loader 构建


class SkillMdSkill(BaseSkill):
    """包装 ``SkillMdDocument`` 为 ``BaseSkill`` 实例。

    - schema 由 frontmatter 推导: ``name`` / ``description`` / ``triggers`` 直读,
      未声明 ``triggers`` 时默认 ``[name.lower()]`` (单触发词, 大小写不敏感)。
    - execute 返回的 ``SkillResult``:
      - ``success=True``
      - ``content`` 是 markdown body 字符串
      - ``metadata`` 包含 ``source="skillmd"`` / ``name`` / ``version`` /
        ``frontmatter`` (原始字典, 供聊天层做高级处理)
    """

    def __init__(self, doc: SkillMdDocument, base_dir: Path | None = None) -> None:
        # 必须先 super().__init__(), 让 BaseSkill 初始化 _schema cache
        super().__init__()
        self._doc = doc
        # 若 doc.base_dir 没传, 用传入的; 都没有就 None
        if base_dir is not None:
            self._doc.base_dir = base_dir

    def _build_schema(self) -> SkillSchema:
        triggers = self._doc.triggers if self._doc.triggers else [self._doc.name.lower()]
        return SkillSchema(
            name=self._doc.name,
            description=self._doc.description,
            triggers=triggers,
            parameters={"type": "object", "properties": {}},
            examples=[],
        )

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """返回 body + 元数据, 不消费 params/context (v1 设计)。

        v1 决策: SKILL.md 技能**不**调 LLM / 工具, 只产提示词模板。
        聊天层拿到 ``content`` 后自行组装到 system prompt。
        这样保持技能层的纯净, 也避免双倍 LLM 调用 (写 builtin + 跑 skill)。
        """
        return SkillResult(
            success=True,
            content=self._doc.body,
            metadata={
                "source": "skillmd",
                "name": self._doc.name,
                "version": self._doc.version,
                "frontmatter": dict(self._doc.raw_frontmatter),
            },
        )
