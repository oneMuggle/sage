"""M7: ScriptRunner 编排。

编排脚本执行的完整流程：
  1. 路径校验（防遍历）
  2. 用户确认（拒绝 → 跳过）
  3. 沙箱执行（结果转换）
  4. 异常收敛（永不抛异常）

设计要点
--------

- ScriptRunner 依赖两个 port: SandboxPort 和 ConfirmationPort
- 路径校验使用 validate_resource_path 复用 v1 的路径遍历防御
- 用户确认通过 ConfirmationPort.confirm() 实现，支持 sync/async
- 沙箱执行通过 SandboxPort.run() 实现，支持超时和资源限制
- 所有异常都收敛为 SkillResult(success=False)，永不向上传播
- metadata 包含完整执行信息（script/exit_code/duration_ms/stderr）
"""

from __future__ import annotations
from typing import List, Optional, Tuple

import logging
from pathlib import Path

from backend.skills.base import SkillResult
from backend.skills.skill_md.confirm import ConfirmationPort
from backend.skills.skill_md.sandbox import SandboxPort, SandboxRequest
from backend.skills.skill_md.skill import SkillMdDocument
from backend.skills.skill_md.validation import validate_base_dir

logger = logging.getLogger(__name__)


class ScriptRunner:
    """脚本执行编排器。

    依赖:
        sandbox: SandboxPort - 沙箱执行端口
        confirmer: ConfirmationPort - 用户确认端口

    流程:
        1. 构造脚本路径并校验（防遍历）
        2. 调用 confirmer.confirm() 获取用户确认
        3. 调用 sandbox.run() 执行脚本
        4. 转换结果为 SkillResult 并返回

    异常处理:
        - 所有异常都收敛为 SkillResult(success=False, error=...)
        - 永不向上传播异常
    """

    def __init__(
        self,
        sandbox: SandboxPort,
        confirmer: ConfirmationPort,
        allowed_roots: Optional[List[Path]] = None,
    ) -> None:
        """初始化 ScriptRunner。

        Args:
            sandbox: 沙箱执行端口
            confirmer: 用户确认端口
            allowed_roots: 允许的根目录列表（路径校验用），默认 []（不允许任何路径）
        """
        self._sandbox = sandbox
        self._confirmer = confirmer
        self._allowed_roots = allowed_roots or []

    async def run_script(  # noqa: PLR0911
        self,
        doc: SkillMdDocument,
        script_name: str,
        args: Tuple[str, ...],
    ) -> SkillResult:
        """执行 SKILL.md 中的脚本。

        Args:
            doc: SKILL.md 文档（包含 base_dir）
            script_name: 脚本名称（相对路径，如 "scripts/test.py"）
            args: 脚本参数

        Returns:
            SkillResult: 执行结果（永不抛异常）
        """
        # 1. 构造脚本路径
        script_path = doc.base_dir / script_name

        # 2. 路径校验（防遍历）
        try:
            validated_path = validate_base_dir(script_path, self._allowed_roots)
        except Exception as exc:
            return self._make_error(f"路径校验失败: {exc}")

        # 3. 检查脚本文件是否存在
        if not validated_path.is_file():
            return self._make_error(f"脚本不存在: {script_name}")

        # 4. 用户确认
        try:
            confirmed = await self._confirmer.confirm(
                skill_name=doc.name,
                script_path=validated_path,
                args=args,
            )
        except Exception as exc:
            return self._make_error(f"用户确认异常: {exc}")

        if not confirmed:
            return self._make_error("用户拒绝执行脚本")

        # 5. 沙箱执行
        sandbox_request = SandboxRequest(
            script_path=validated_path,
            args=args,
        )

        try:
            sandbox_result = await self._sandbox.run(sandbox_request)
        except Exception as exc:
            return self._make_error(f"沙箱执行异常: {exc}")

        # 6. 转换结果
        metadata = {
            "source": "script_execution",
            "script": script_name,
            "exit_code": sandbox_result.exit_code,
            "duration_ms": sandbox_result.duration_ms,
            "stderr": sandbox_result.stderr,
        }

        # 处理失败情况
        if not sandbox_result.success:
            error_msg = (
                f"脚本执行超时: {sandbox_result.error}"
                if sandbox_result.timed_out
                else f"脚本执行失败 (exit_code={sandbox_result.exit_code}): {sandbox_result.error}"
            )
            return SkillResult(
                success=False,
                content=None,
                metadata=metadata,
                error=error_msg,
            )

        return SkillResult(
            success=True,
            content=sandbox_result.stdout,
            metadata=metadata,
            error=None,
        )

    def _make_error(self, error_msg: str) -> SkillResult:
        """创建错误结果（辅助方法，减少重复代码）。"""
        return SkillResult(
            success=False,
            content=None,
            metadata={},
            error=error_msg,
        )
