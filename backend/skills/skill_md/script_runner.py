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

import hashlib
import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from backend.skills.base import SkillResult
from backend.skills.skill_md.confirm import ConfirmationPort
from backend.skills.skill_md.resources import ALLOWED_RESOURCE_DIRS
from backend.skills.skill_md.sandbox import SandboxPort, SandboxRequest
from backend.skills.skill_md.skill import SkillMdDocument
from backend.skills.skill_md.validation import validate_base_dir

logger = logging.getLogger(__name__)


def _has_symlink_component(path: Path) -> bool:
    """拒绝脚本路径自身或已有父级路径组件中的符号链接。"""
    current = path.absolute()
    for component in (current,) + tuple(current.parents):
        try:
            if component.is_symlink():
                return True
        except OSError:
            return True
    return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.8 的 Path.is_relative_to。"""
    try:
        return path.is_relative_to(parent)  # py38: guarded py38-ok AttributeError 守卫 + relative_to 降级已覆盖
    except AttributeError:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False


def _read_bound_regular_file(path: Path) -> Tuple[bytes, Tuple[int, int], bytes]:
    """通过不跟随链接的 fd 读取文件，并校验 fd 始终绑定同一普通文件。

    这里不回退到 ``Path.read_bytes``：没有 ``O_NOFOLLOW`` 的平台无法提供
    所需的路径到 fd 绑定保证，必须拒绝执行（尤其是 Windows）。
    """
    if os.name == "nt":
        # R32 切片 B：Windows 走原生 reparse-safe 绑定读取
        # （卷序号 + 文件索引等价 (st_dev, st_ino)，消费方只做相等比较）。
        from backend.tools.win_reparse_io import read_file_bound_reparse_safe

        data, win_identity = read_file_bound_reparse_safe(str(path))
        return data, win_identity, hashlib.sha256(data).digest()

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("安全读取需要 O_NOFOLLOW；当前平台不支持")

    path_stat = os.lstat(str(path))
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError("脚本不是普通文件")
    identity = (path_stat.st_dev, path_stat.st_ino)
    flags = os.O_RDONLY | nofollow
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    fd = os.open(str(path), flags)
    try:
        opened_stat = os.fstat(fd)
        opened_identity = (opened_stat.st_dev, opened_stat.st_ino)
        if opened_identity != identity or not stat.S_ISREG(opened_stat.st_mode):
            raise OSError("脚本路径在打开时发生变化")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final_stat = os.fstat(fd)
        final_identity = (final_stat.st_dev, final_stat.st_ino)
        if final_identity != identity or not stat.S_ISREG(final_stat.st_mode):
            raise OSError("脚本 inode 在读取期间发生变化")
        path_final_stat = os.lstat(str(path))
        path_final_identity = (path_final_stat.st_dev, path_final_stat.st_ino)
        if path_final_identity != identity or not stat.S_ISREG(path_final_stat.st_mode):
            raise OSError("脚本路径在读取期间发生变化")
        content = b"".join(chunks)
        return content, identity, hashlib.sha256(content).digest()
    finally:
        if fd != -1:
            os.close(fd)


def _validate_script_path(
    doc: SkillMdDocument, script_name: str, allowed_roots: List[Path]
) -> Path:
    """将脚本限制在当前技能目录，并拒绝遍历及符号链接。"""
    if not isinstance(script_name, str):
        raise TypeError("script_name must be a string")
    relative_path = Path(script_name)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(
            "script_name must be a relative path without '..'; "
            "not under any allowed root"
        )

    base_dir = doc.base_dir
    script_path = base_dir / relative_path
    if _has_symlink_component(base_dir) or _has_symlink_component(script_path):
        raise ValueError("script path or parent contains symlink")

    resolved_base = base_dir.resolve(strict=False)
    resolved_script = script_path.resolve(strict=False)
    if not _is_relative_to(resolved_script, resolved_base):
        raise ValueError("script path is outside the skill base directory")

    # 保留公共根目录策略，同时增加当前技能目录边界。
    validate_base_dir(script_path, allowed_roots)
    return resolved_script


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
        # 1. 校验调用参数；边界输入异常必须收敛为结果。
        try:
            if not isinstance(args, tuple) or any(
                not isinstance(argument, str) for argument in args
            ):
                raise TypeError("args must be a tuple of strings")
        except Exception as exc:
            return self._make_error(f"脚本请求无效: {exc}")

        # 2. 路径校验（防遍历）
        try:
            validated_path = _validate_script_path(doc, script_name, self._allowed_roots)
        except Exception as exc:
            return self._make_error(f"路径校验失败: {exc}")

        # 3. 检查脚本文件是否存在
        try:
            if not validated_path.is_file():
                return self._make_error(f"脚本不存在: {script_name}")
        except OSError as exc:
            return self._make_error(f"脚本状态检查失败: {exc}")

        # 3. 读取确认前快照；hash 绑定用户实际确认的内容。
        try:
            _original_content, original_identity, original_hash = _read_bound_regular_file(
                validated_path
            )
        except OSError as exc:
            return self._make_error(f"脚本内容读取失败: {exc}")

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

        # 确认后以同一普通文件重新读取并比较 hash，再创建受控快照。
        snapshot_path: Optional[Path] = None
        try:
            if _has_symlink_component(validated_path):
                raise ValueError("script path or parent contains symlink")
            current_content, current_identity, current_hash = _read_bound_regular_file(
                validated_path
            )
            if current_identity != original_identity or current_hash != original_hash:
                raise ValueError("script identity or content changed after confirmation")
            snapshot_path = self._create_snapshot(
                validated_path, current_content, base_dir=doc.base_dir
            )
        except Exception as exc:
            return self._make_error(f"确认后脚本快照失败: {exc}")

        # 5. 沙箱执行；cwd 改为快照内对应目录，让脚本 dirname(__file__) / ".."
        #    相对路径能正确找到镜像到快照中的 assets / references 等资源。
        sandbox_request = SandboxRequest(
            script_path=snapshot_path,
            args=args,
            cwd=snapshot_path.parent,
        )

        try:
            sandbox_result = await self._sandbox.run(sandbox_request)
        except Exception as exc:
            return self._make_error(f"沙箱执行异常: {exc}")
        finally:
            if snapshot_path is not None:
                self._cleanup_snapshot(snapshot_path)

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

    def _create_snapshot(
        self, validated_path: Path, content: bytes, base_dir: Path
    ) -> Path:
        """创建 0700 临时目录并镜像 base_dir 白名单资源子目录，返回脚本在快照中的路径。

        布局（镜像 doc.base_dir 结构）::

            <tmp>/sage-skill-XXXX/
            ├── scripts/
            │   ├── build_report.py       ← 已确认字节
            │   └── scan.py               ← 安全读取副本
            ├── assets/
            │   └── report_template.html  ← 安全读取副本
            ├── references/...
            └── templates/...

        脚本文件用已确认的 ``content`` 写入；其余白名单文件逐一走
        ``_read_bound_regular_file`` 读取后复制。符号链接 / 重解析点一律跳过。

        Windows：``os.fchmod`` 不存在、目录 ACL 与 POSIX 位模型不同 ——
        mkdtemp 默认已为当前用户私有（%TEMP% 每用户目录），文件以 0600
        等价创建后跳过位调整；快照目录本身每用户隔离，安全语义等价。
        """
        snapshot_root = Path(tempfile.mkdtemp(prefix="sage-skill-"))
        try:
            if os.name == "posix":
                snapshot_root.chmod(stat.S_IRWXU)

            # 计算脚本在 base_dir 下的相对路径
            try:
                script_rel = validated_path.resolve().relative_to(
                    base_dir.resolve()
                )
            except ValueError as exc:
                raise ValueError("script not under base_dir") from exc

            # 镜像每个白名单子目录，但跳过脚本自身（稍后用确认字节写入）
            skip_resolved = validated_path.resolve()
            for subdir_name in sorted(ALLOWED_RESOURCE_DIRS):
                source_subdir = base_dir / subdir_name
                try:
                    if source_subdir.is_symlink():
                        continue
                    if _has_symlink_component(source_subdir):
                        continue
                    if not source_subdir.is_dir():
                        continue
                except OSError:
                    continue
                target_subdir = snapshot_root / subdir_name
                self._mirror_subdir(
                    source_subdir, target_subdir, base_dir, skip_resolved
                )

            # 用已确认内容写入脚本的镜像位置
            snapshot_script = snapshot_root / script_rel
            snapshot_script.parent.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                # 确保脚本父目录权限为 0700（_mirror_subdir 已处理则幂等）
                for ancestor in (snapshot_script.parent, snapshot_root):
                    try:
                        if stat.S_IMODE(ancestor.stat().st_mode) != 0o700:
                            ancestor.chmod(stat.S_IRWXU)
                    except OSError:
                        pass
            self._write_snapshot_file(snapshot_script, content)

            return snapshot_script
        except Exception:
            shutil.rmtree(str(snapshot_root), ignore_errors=True)
            raise

    def _mirror_subdir(
        self,
        source_subdir: Path,
        target_subdir: Path,
        base_dir: Path,
        skip_resolved: Path,
    ) -> None:
        """递归镜像一个白名单资源子目录到快照，跳过符号链接和 ``skip_resolved``。"""
        target_subdir.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            target_subdir.chmod(stat.S_IRWXU)

        try:
            entries = list(source_subdir.iterdir())
        except OSError:
            return

        for entry in entries:
            try:
                name = entry.name
                if name.startswith("."):
                    continue
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if _has_symlink_component(entry):
                        continue
                    self._mirror_subdir(
                        entry, target_subdir / name, base_dir, skip_resolved
                    )
                elif entry.is_file():
                    resolved_entry = entry.resolve()
                    if resolved_entry == skip_resolved:
                        continue  # 脚本本身稍后用已确认字节写入
                    if _has_symlink_component(entry):
                        continue
                    # 边界校验：必须仍在 base_dir 下
                    try:
                        resolved_entry.relative_to(base_dir.resolve())
                    except (ValueError, OSError):
                        continue
                    data, _identity, _hash = _read_bound_regular_file(entry)
                    target_file = target_subdir / name
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    self._write_snapshot_file(target_file, data)
            except OSError:
                continue

    @staticmethod
    def _write_snapshot_file(path: Path, content: bytes) -> None:
        """原子创建 0600 文件写入 ``content``；已存在则先删除再创建。"""
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(str(path), flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as snapshot_file:
                fd = -1
                snapshot_file.write(content)
                snapshot_file.flush()
                if os.name == "posix":
                    os.fchmod(snapshot_file.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        finally:
            if fd != -1:
                os.close(fd)

    @staticmethod
    def _cleanup_snapshot(snapshot_path: Path) -> None:
        """尽力清理快照；沿父级向上查找 ``sage-skill-*`` 临时目录并整棵删除。

        镜像布局下 ``snapshot_path`` 可能是 ``<tmp>/sage-skill-XXXX/scripts/foo.py``，
        必须向上找到 ``sage-skill-XXXX`` 才是 mkdtemp 创建的快照根。
        清理失败只记录日志，不改变执行结果。

        安全约束：匹配的祖先目录必须直接位于 ``tempfile.gettempdir()`` 之下，
        避免把技能自身以 ``sage-skill-*`` 命名的 ``base_dir`` 误判为快照根。
        """
        import tempfile

        temp_root = Path(tempfile.gettempdir()).resolve()
        root: Optional[Path] = None
        for ancestor in snapshot_path.parents:
            if (
                ancestor.name.startswith("sage-skill-")
                and ancestor.parent.resolve() == temp_root
            ):
                root = ancestor
                break
        if root is None:
            # 兜底：按旧布局尝试 snapshot_path.parent
            root = snapshot_path.parent
        try:
            shutil.rmtree(str(root))
        except OSError as exc:
            logger.warning("skill script snapshot cleanup failed: %s", exc)

    def _make_error(self, error_msg: str) -> SkillResult:
        """创建错误结果（辅助方法，减少重复代码）。"""
        return SkillResult(
            success=False,
            content=None,
            metadata={},
            error=error_msg,
        )
