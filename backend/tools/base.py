"""
工具系统基类
定义工具的基础接口和数据结构
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy


@dataclass
class ToolSchema:
    """工具 Schema - 定义工具的元数据"""

    name: str  # 工具名称
    description: str  # 工具描述
    parameters: Dict[str, Any] = field(default_factory=dict)  # JSON Schema 格式参数


@dataclass
class ToolResult:
    """工具执行结果"""

    success: bool  # 是否成功
    content: Any = None  # 返回内容
    error: Optional[str] = None  # 错误信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {"success": self.success}
        if self.content is not None:
            result["content"] = self.content
        if self.error is not None:
            result["error"] = self.error
        return result


def _is_safe_path(path: str, allowed_base: str) -> bool:
    """检查路径是否在允许的基础目录内（resolve 后用 relative_to 严格比对）。

    拒绝:
    - 父目录越界 (``..``)
    - 绝对路径在 base 之外
    - 符号链接逃逸（symlink 先 resolve 再比对）

    Args:
        path: 文件路径
        allowed_base: 允许的基础目录

    Returns:
        是否安全
    """
    try:
        file_path = Path(path).expanduser().resolve()
        allowed_path = Path(allowed_base).resolve()
        # 用 relative_to 而非 startswith；后者会让 /foo/bar2 误匹配 /foo/bar
        try:
            file_path.relative_to(allowed_path)
            return True
        except ValueError:
            return False
    except Exception:
        return False


class BaseTool(ABC):
    """
    工具基类

    所有工具必须继承此类并实现:
    - _build_schema(): 返回工具的 Schema
    - execute(): 执行工具逻辑

    M2：构造器接 ``policy`` 注入（缺省 ``ToolPolicy()`` 默认值）。
    M3：构造器接受 ``policy.workspace_root`` 作为安全边界；
        ``_enforce_workspace`` 在 ``execute()`` 入口调用做路径守卫。
    """

    # M3+: flag marking tools that must only be advertised to the LLM
    # when an active ``ToolExecutionContext`` is in scope (e.g. Office
    # document tools, which need a doc-scope to operate). Default False
    # preserves backwards compatibility -- existing tools are not
    # affected. Set on a subclass to opt in.
    requires_tool_context: bool = False

    # A1: 工具风险声明 — 权限引擎（PermissionEngine）据此做模式门禁，
    # 取代按工具名硬编码集合的旧模式。默认 READ（无副作用）；有副作
    # 用的工具必须在子类覆盖（如 WriteFileTool → WRITE_LOCAL、
    # TerminalTool → EXEC、WebSearchTool → EXTERNAL）。注册表在
    # register() 时收集该声明，引擎经 declared_risks 注入。
    #
    # ⚠️ fail-open 警示：注册表无法区分"显式声明 READ"与"继承默认
    # READ"，漏写 risk 的副作用工具会被静默放行。新增工具务必声明
    # risk，并同步扩充 test_risk.py 的内置工具验收表。
    risk: RiskClass = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        self._schema: Optional[ToolSchema] = None
        self._policy = policy or ToolPolicy()

    def _enforce_workspace(self, path: str) -> ToolResult | None:
        """M3: 若 ``policy.workspace_root`` 非空则校验 ``path``。

        返回 ``ToolResult(success=False, ...)`` 表示拒绝（调用方应直接
        return 该结果）；返回 ``None`` 表示放行（继续正常流程）。

        本方法有意不检查 ``path`` 是否存在——只检查路径是否在 workspace
        内；不存在的合法路径（例如写入新文件）应被允许，后续 ``exists /
        is_dir`` 校验再报错。
        """
        root = self._policy.workspace_root
        if not root:
            return None
        if not _is_safe_path(path, root):
            return ToolResult(
                success=False,
                error=f"path_outside_workspace: resolved path is not under {root}",
            )
        return None

    @property
    def schema(self) -> ToolSchema:
        """获取工具 Schema"""
        if self._schema is None:
            self._schema = self._build_schema()
        return self._schema

    @property
    def name(self) -> str:
        """获取工具名称"""
        return self.schema.name

    @property
    def description(self) -> str:
        """获取工具描述"""
        return self.schema.description

    @abstractmethod
    def _build_schema(self) -> ToolSchema:
        """
        构建工具 Schema

        Returns:
            ToolSchema 对象
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            ToolResult 对象
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}'>"
