# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""
工具系统基类
定义工具的基础接口和数据结构
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
    # ``output``: Task 2 起新增的字段,承载"业务层主返回"(如记忆 ID、
    # 文件路径等),与 ``content``(结构化 dict)解耦。``InprocToolAdapter``
    # 转发到 ``domain.tool.ToolResult.output``。新字段可选,旧工具不受影响。
    output: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {"success": self.success}
        if self.content is not None:
            result["content"] = self.content
        if self.error is not None:
            result["error"] = self.error
        if self.output is not None:
            result["output"] = self.output
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
    # TerminalTool → EXEC（历史命名）、BashTool → EXEC（当前实现）、
    # WebSearchTool → EXTERNAL）。注册表在 register() 时收集该声明，
    # 引擎经 declared_risks 注入。
    #
    # ⚠️ fail-open 警示：注册表无法区分"显式声明 READ"与"继承默认
    # READ"，漏写 risk 的副作用工具会被静默放行。新增工具务必声明
    # risk，并同步扩充 test_risk.py 的内置工具验收表。
    risk: RiskClass = RiskClass.READ

    # DSH 对标 R3 (B2): 并发安全自声明 —— True 显式声明可与任意工具并发
    # 执行（rolling pool），False 显式压制（即使 risk==READ 也不进并发池，
    # 如依赖共享游标/临时态的 READ 工具）；None 缺省回落 risk==READ 判定
    # （与既有批级并行同口径，存量工具零注册成本）。对齐 deepseek-harness
    # 的 isConcurrencySafe 声明式调度。
    concurrency_safe: Optional[bool] = None

    # 阻塞型工具声明：execute() 可能长时间不返回（bash 默认超时 120s、
    # 上限 600s；repl 同量级）。run_loop 分发点据此把这类工具卸载到
    # executor 线程执行，避免一条慢命令卡死整个 asyncio 事件循环
    # （健康检查、看板轮询、其他并发会话）。快操作工具（bash_output /
    # kill_shell 等）保持 False，内联执行零额外开销。
    is_blocking: bool = False

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        self._schema: Optional[ToolSchema] = None
        self._policy = policy or ToolPolicy()

    def _enforce_workspace(self, path: str) -> ToolResult | None:
        """M3: 若 ``policy.workspace_root`` 非空则校验 ``path``。

        返回 ``ToolResult(success=False, ...)`` 表示拒绝（调用方应直接
        return 该结果）；返回 ``None`` 表示放行（继续正常流程）。

        五层判定（由内到外）：

        1. 路径在 ``workspace_root`` 内 → 放行；
        2. 路径命中当前 session 绑定项目的 ``allowed_paths`` 白名单 → 放行
           （用户显式授权的额外路径，如 ``~/Documents/**``）；
        3. **仅 READ**：路径落在当前项目已登记的 ``file_references`` 目标内
           → 放行（P5 文件引用，v1 只读；写入仍被拒绝）；
        4. 路径落在当前调用的已审批路径作用域内 → 放行（用户刚刚批准过
           的工作区外写入；由 ``backend.tools.context.set_approved_paths``
           在调用外层注入）；
        5. 其余 → 拒绝。

        本方法有意不检查 ``path`` 是否存在——只检查路径是否在 workspace
        内；不存在的合法路径（例如写入新文件）应被允许，后续 ``exists /
        is_dir`` 校验再报错。
        """
        root = self._policy.workspace_root
        if not root:
            return None
        if _is_safe_path(path, root):
            return None
        # 工作区外：用户显式授权的项目白名单（allowed_paths）优先放行。
        if self._is_path_allowed(path, root):
            return None
        # P5 文件引用第 3 层：已登记引用目标放行读取（写入不在此列）。
        if self.risk == RiskClass.READ and self._is_path_reference_readable(path):
            return None
        # 工作区外 + 不在白名单：刚被用户批准的写入（per-call scope）放行。
        if self._is_path_approved(path):
            return None
        return ToolResult(
            success=False,
            error=f"path_outside_workspace: resolved path is not under {root}",
        )

    @staticmethod
    def _translate_virtual_path(path: str) -> Tuple[str, bool]:
        """把项目内虚拟路径翻译为最近引用目标下的真实路径。

        Returns:
            ``(路径, 是否命中引用)``。未命中 / 无项目 / 解析失败 → 原样返回
            ``(path, False)``，由既有权限层级决定放行或拒绝（fail-closed）。
        """
        try:
            from backend.services.virtual_fs import (
                current_project_id,
                resolve_virtual,
            )

            project_id = current_project_id()
            if not project_id:
                return path, False
            resolved, hit = resolve_virtual(project_id, path)
            if hit is None:
                return path, False
            return str(resolved), True
        except Exception:  # noqa: BLE001 — 翻译失败退回原路径
            return path, False

    @staticmethod
    def _is_path_reference_readable(path: str) -> bool:
        """路径是否落在当前项目已登记的文件引用目标内（第 3 层，只读）。"""
        try:
            from backend.services.virtual_fs import (
                current_project_id,
                resolve_virtual,
            )

            project_id = current_project_id()
            if not project_id:
                return False
            _, hit = resolve_virtual(project_id, path)
            return hit is not None
        except Exception:  # noqa: BLE001 — 查询失败按未授权处理
            return False

    @staticmethod
    def _is_path_approved(path: str) -> bool:
        """路径是否落在当前调用的已审批路径作用域内。

        ``set_approved_paths`` 在审批通过后由 agent 写入；路径 ``resolve``
        后必须等于或为任一已审批路径的后代才放行。空作用域 / 解析失败
        → False（fail-closed）。
        """
        from backend.tools.context import current_approved_paths

        approved = current_approved_paths()
        if not approved:
            return False
        try:
            resolved = Path(path).expanduser().resolve()
        except Exception:
            return False
        for anchor in approved:
            try:
                anchor_resolved = Path(anchor).resolve()
            except Exception:
                continue
            # 精确相等或后代（用 relative_to 严格比对，避免字符串前缀碰撞）
            if resolved == anchor_resolved:
                return True
            try:
                resolved.relative_to(anchor_resolved)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _is_path_allowed(path: str, project_root: Optional[str] = None) -> bool:
        """路径是否命中当前 session 绑定项目的 ``allowed_paths`` 白名单。

        无活动 ToolExecutionContext / 项目未绑定 / 查询失败 / 未命中 → False
        （fail-closed）。延迟 import 避免 ``backend.tools`` → ``backend.office``
        的导入环。
        """
        try:
            from backend.office.allowed_paths import (
                get_session_allowed_paths,
                is_allowed,
            )
            from backend.tools.context import current_tool_context

            ctx = current_tool_context()
            session_id = ctx.session_id if ctx is not None else None
            allowed_paths = get_session_allowed_paths(session_id)
            if not allowed_paths:
                return False
            return is_allowed(path, allowed_paths, project_root=project_root)
        except Exception:  # noqa: BLE001 — 白名单查询失败一律按未授权处理
            return False

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
