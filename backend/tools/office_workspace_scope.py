# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office 工具的「服务层 workspace」选取。

Office 工具把 ``file_path`` 交给 ``backend.office.*`` 服务层时，需要一并给出
一个 workspace 作为围栏基座；服务层的 ``resolve_within(workspace, path)`` 会
resolve 双方后严格比对，拒绝任何越界路径。

围栏基座的选择直接决定工具的边界语义（2026-11-02 工作区外文件访问放宽）：

- **输入落在会话绑定工作区内** → 用绑定工作区。保持既有语义：受管文档
  ``<workspace>/office/...`` 与工作区任意子目录都在围栏内，写工具可以把
  产物落到工作区的任何位置。
- **输入在绑定工作区外** → 用输入自身的父目录。读路径据此可以读取任意
  绝对路径（与 ``read_file`` 对齐）；写路径在工作区外时由
  ``backend.tools.permissions.make_office_path_boundary`` 升级为用户审批，
  批准后同一围栏放行。

回退到父目录**不放宽**穿越防护：``resolve_within`` 仍会 resolve 双方，
``..`` 越界与 symlink 逃逸照常被拒；而 ``validate_workspace`` 会直接拒掉
路径里含 ``..`` 段的 workspace。

Public surface:

    workspace_for_input(binding_workspace, input_path) -> Path
    workspace_for_policy(policy, input_path) -> Path
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.tools.base import _is_safe_path


def workspace_for_input(
    binding_workspace: Optional[Path], input_path: Path
) -> Path:
    """按输入路径的位置选出服务层 workspace。

    Args:
        binding_workspace: 会话绑定工作区（``None`` 表示未绑定）。
        input_path: 本次工具调用的输入文件路径。

    Returns:
        绑定工作区（输入在其内时）或输入文件自身的父目录。
    """
    if binding_workspace is not None and _is_safe_path(
        str(input_path), str(binding_workspace)
    ):
        return binding_workspace
    return input_path.parent


def workspace_for_policy(policy: Any, input_path: Path, *extra_paths: Path) -> Path:
    """:func:`workspace_for_input` 的 ``ToolPolicy`` 便捷形态（读工具共用）。

    ``policy.workspace_root`` 为空 / 缺省 → 视为未绑定，回退输入父目录。
    ``extra_paths`` 为同一调用的附加输入（如 tex + pdf）：全部落在绑定
    工作区内才用绑定工作区，任一在外即回退 ``input_path.parent``。
    """
    root = getattr(policy, "workspace_root", None)
    binding = Path(root) if root else None
    if binding is not None:
        inputs = (input_path,) + extra_paths
        if all(_is_safe_path(str(p), str(binding)) for p in inputs):
            return binding
    return input_path.parent


__all__ = ["workspace_for_input", "workspace_for_policy"]
