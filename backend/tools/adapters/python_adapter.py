"""Python 运行时适配器。

负责：

- 发现系统 PATH、常见 conda 环境以及已知 venv 路径下的 CPython 解释器。
- 通过 ``python -V``、``python -c "import sys; ..."`` 等受控调用获取版本
  与能力信息。
- 识别项目里的 ``pyproject.toml`` / ``requirements*.txt`` /
  ``environment.yml`` / ``Pipfile``，并产出诊断。

安全约束：

- 所有子进程都通过 ``safe_run``（来自 AdapterContext）调用，统一
  享受超时、输出上限、进程组回收。
- 不向目标解释器注入未审批的环境变量；由 ``runtime_exec`` 工具统一
  收敛。
- 解析 ``pyproject.toml`` 时拒绝任意 TOML 库依赖；只做最小化字符串解析。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from backend.domain.runtime import (
    Diagnostic,
    DiagnosticLevel,
    DiagnosticSeverity,
    ExecutionRequest,
    ProbeRequest,
    ProjectDiagnosis,
    ProjectManifest,
    RuntimeCapability,
    RuntimeInfo,
    RuntimeSource,
)
from backend.tools.runtime_adapter import (
    AdapterContext,
    CommandRequest,
    RuntimeAdapter,
    classify_python_source,
)


DEFAULT_CONDA_BASE_DIRS: Tuple[str, ...] = (
    "/opt/anaconda3",
    "/opt/miniconda3",
    "/usr/local/anaconda3",
    "/usr/local/miniconda3",
    str(Path.home() / "anaconda3"),
    str(Path.home() / "miniconda3"),
    str(Path.home() / ".conda"),
)
DEFAULT_VENV_HINTS: Tuple[str, ...] = (
    ".venv",
    "venv",
    ".venv-win",
)

CANDIDATE_NAMES: Tuple[str, ...] = (
    "python3",
    "python",
)

_VERSION_RE = re.compile(r"Python\s+(\d+\.\d+(?:\.\d+)?)")


class PythonAdapter:
    """CPython 适配器。"""

    language = "python"

    # ------------------------------------------------------------------ 发现

    def discover(
        self,
        request: ProbeRequest,
        ctx: AdapterContext,
    ) -> List[RuntimeInfo]:
        seen: set[str] = set()
        results: List[RuntimeInfo] = []

        for path in self._candidate_paths(request.include_paths):
            if not path or path in seen:
                continue
            seen.add(path)
            info = self._probe_interpreter(path, ctx)
            if info is not None:
                results.append(info)

        compatible_target = _target_version_meet(request.target_version)
        enriched: List[RuntimeInfo] = []
        any_default = False
        for r in results:
            meet, note = compatible_target(r.version) if compatible_target else (None, "")
            new_is_default = (
                not any_default
                and r.source is RuntimeSource.SYSTEM
                and meet is not False
            )
            any_default = any_default or new_is_default
            enriched.append(
                RuntimeInfo(
                    language=r.language,
                    name=r.name,
                    path=r.path,
                    version=r.version,
                    source=r.source,
                    is_default=new_is_default,
                    is_compatible=meet,
                    compatibility_notes=(note,) if note else (),
                    capabilities=r.capabilities,
                    diagnostics=r.diagnostics,
                    raw=r.raw,
                )
            )
        return enriched

    def _candidate_paths(self, include_paths: Tuple[str, ...]) -> Iterable[str]:
        path_env = os.environ.get("PATH", "")
        for directory in path_env.split(os.pathsep):
            if not directory:
                continue
            for name in CANDIDATE_NAMES:
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate):
                    yield candidate

        for extra in include_paths:
            if os.path.isfile(extra):
                yield extra

        for base in DEFAULT_CONDA_BASE_DIRS:
            if not os.path.isdir(base):
                continue
            envs_dir = os.path.join(base, "envs")
            if os.path.isdir(envs_dir):
                yield os.path.join(base, "bin", "python3")
                try:
                    for entry in sorted(os.listdir(envs_dir)):
                        sub = os.path.join(envs_dir, entry, "bin", "python3")
                        if os.path.isfile(sub):
                            yield sub
                except OSError:
                    continue

        # venv 提示：当前阶段只在 workspace_root 内查找，避免破坏 root 之外的环境
        for hint in DEFAULT_VENV_HINTS:
            sub = Path(hint)
            if not sub.is_dir():
                continue
            for name in CANDIDATE_NAMES:
                for candidate in (
                    sub / "Scripts" / f"{name}.exe",
                    sub / "bin" / name,
                ):
                    if candidate.is_file():
                        yield str(candidate)

    # ------------------------------------------------------------------ 检查

    def inspect(
        self,
        runtime: RuntimeInfo,
        ctx: AdapterContext,
    ) -> RuntimeInfo:
        """通过 ``python -V`` 与 ``python -c "import sys.platform"`` 补充能力。"""

        version_result = ctx.safe_run([runtime.path, "-V"], timeout=5.0)
        version = runtime.version
        if version_result.exit_code == 0:
            match = _VERSION_RE.search(version_result.stdout or version_result.stderr)
            if match:
                version = match.group(1)

        platform_result = ctx.safe_run(
            [
                runtime.path,
                "-c",
                "import json,sys; print(json.dumps({'platform': sys.platform, 'executable': sys.executable}))",
            ],
            timeout=5.0,
        )
        platform_info = _parse_json_line(platform_result.stdout)
        notes: List[str] = list(runtime.compatibility_notes)
        capabilities = RuntimeCapability(
            can_execute=True,
            can_package_check=True,
            supports_stdin_source=True,
            supports_tempfile_source=True,
            notes="",
        )

        source = classify_python_source(
            runtime.path,
            platform_info.get("executable", runtime.path),
        )
        return RuntimeInfo(
            language=runtime.language,
            name=runtime.name,
            path=runtime.path,
            version=version,
            source=source,
            is_default=runtime.is_default,
            is_compatible=runtime.is_compatible,
            compatibility_notes=tuple(notes),
            capabilities=capabilities,
            diagnostics=runtime.diagnostics,
            raw={"platform": platform_info.get("platform")},
        )

    # ------------------------------------------------------------------ 命令

    def build_command(
        self,
        request: ExecutionRequest,
        runtime: RuntimeInfo,
        ctx: AdapterContext,
    ) -> CommandRequest:
        """默认走 stdin，避免临时文件。"""

        return CommandRequest(
            argv=[runtime.path, "-"],
            stdin_payload=request.code,
        )

    # ------------------------------------------------------------------ 项目

    _PYPROJECT_VERSION_RE = re.compile(
        r'^\s*requires-python\s*=\s*["\']([^"\']+)["\']',
        re.MULTILINE,
    )

    def discover_manifests(self, project_root: Path) -> List[ProjectManifest]:
        manifests: List[ProjectManifest] = []
        for filename, kind in (
            ("pyproject.toml", "pyproject"),
            ("requirements.txt", "requirements"),
            ("requirements-dev.txt", "requirements-dev"),
            ("requirements-test.txt", "requirements-test"),
            ("Pipfile", "pipfile"),
            ("environment.yml", "conda-env"),
        ):
            path = project_root / filename
            if path.is_file():
                extras: dict = {}
                requires: Tuple[str, ...] = ()
                if kind == "pyproject":
                    text = path.read_text(encoding="utf-8", errors="replace")
                    match = self._PYPROJECT_VERSION_RE.search(text)
                    if match:
                        extras["requires_python"] = match.group(1).strip()
                elif kind.startswith("requirements"):
                    requires = tuple(
                        line.strip()
                        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                        if line.strip() and not line.strip().startswith("#")
                    )
                manifests.append(
                    ProjectManifest(
                        language=self.language,
                        path=str(path),
                        kind=kind,
                        requires=requires,
                        extras=extras,
                    )
                )
        return manifests

    def diagnose(
        self,
        project_root: Path,
        runtimes: List[RuntimeInfo],
        ctx: AdapterContext,
    ) -> ProjectDiagnosis:
        manifests = self.discover_manifests(project_root)
        diagnostics: List[Diagnostic] = []
        py_versions = [r for r in runtimes if r.language == self.language]
        if manifests and not py_versions:
            diagnostics.append(
                Diagnostic(
                    code="PYTHON_RUNTIME_MISSING",
                    severity=DiagnosticSeverity.ERROR,
                    message="项目包含 Python 清单，但本机未发现 Python 解释器",
                    related_path=str(project_root),
                )
            )
        for manifest in manifests:
            if manifest.kind == "pyproject" and "requires_python" in manifest.extras:
                constraint = manifest.extras["requires_python"]
                best = _pick_best_runtime(py_versions)
                meets = _constraint_matches(best.version, constraint) if best else False
                if not best:
                    diagnostics.append(
                        Diagnostic(
                            code="PYTHON_VERSION_REQUIRED_MISSING",
                            severity=DiagnosticSeverity.ERROR,
                            message=f"pyproject 要求 {constraint}，未找到任何 Python 运行时",
                            related_path=manifest.path,
                        )
                    )
                elif not meets:
                    diagnostics.append(
                        Diagnostic(
                            code="PYTHON_VERSION_MISMATCH",
                            severity=DiagnosticSeverity.ERROR,
                            message=f"pyproject 要求 {constraint}，最佳可用 {best.version}",
                            remediation=f"切换到满足 {constraint} 的解释器后再运行",
                            related_path=manifest.path,
                        )
                    )
                else:
                    diagnostics.append(
                        Diagnostic(
                            code="PYTHON_VERSION_OK",
                            severity=DiagnosticSeverity.INFO,
                            message=f"pyproject 要求 {constraint}，最佳可用 {best.version}",
                            related_path=manifest.path,
                        )
                    )
        level = DiagnosticLevel.SATISFIED
        if any(d.severity is DiagnosticSeverity.ERROR for d in diagnostics):
            level = DiagnosticLevel.UNSATISFIED
        elif any(d.severity is DiagnosticSeverity.WARNING for d in diagnostics):
            level = DiagnosticLevel.PARTIAL

        recommended = _pick_best_runtime(py_versions)
        recommended_path = recommended.path if recommended else None
        return ProjectDiagnosis(
            level=level,
            diagnostics=diagnostics,
            manifests=manifests,
            recommended_runtime=recommended_path,
        )

    # ------------------------------------------------------------------ 私有

    def _probe_interpreter(
        self,
        path: str,
        ctx: AdapterContext,
    ) -> Optional[RuntimeInfo]:
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            return None
        real = os.path.realpath(path)
        if real != path:
            path = real

        version_result = ctx.safe_run([path, "-V"], timeout=5.0)
        if version_result.exit_code != 0:
            return None
        match = _VERSION_RE.search(version_result.stdout or version_result.stderr)
        if not match:
            return None
        version = match.group(1)
        source = classify_python_source(path, path)
        return RuntimeInfo(
            language=self.language,
            name="CPython",
            path=path,
            version=version,
            source=source,
            capabilities=RuntimeCapability(can_execute=True, can_package_check=True),
        )


def _parse_json_line(text: str) -> dict:
    if not text:
        return {}
    text = text.strip().splitlines()
    if not text:
        return {}
    try:
        return json.loads(text[-1])
    except json.JSONDecodeError:
        return {}


def _target_version_meet(target: Optional[str]):
    if not target:
        return None

    op_match = re.match(r"^(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)*)$", target.strip())
    if not op_match:
        return None
    op, ver = op_match.group(1), _parse_version(op_match.group(2))

    def _check(actual: str):
        try:
            actual_v = _parse_version(actual)
        except ValueError:
            return None, f"目标版本 {target} 无法解析当前版本 {actual}"
        ok = _compare(actual_v, ver, op)
        note = "" if ok else f"当前版本 {actual} 不满足 {target}"
        return ok, note

    return _check


def _parse_version(text: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for chunk in text.split("."):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parts.append(int(chunk))
        except ValueError as exc:
            raise ValueError(f"invalid version segment: {chunk}") from exc
    return tuple(parts)


def _compare(actual: Tuple[int, ...], target: Tuple[int, ...], op: str) -> bool:
    a = actual + (0,) * (len(target) - len(actual))
    b = target + (0,) * (len(actual) - len(target))
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    return False


def _pick_best_runtime(runtimes: List[RuntimeInfo]) -> Optional[RuntimeInfo]:
    candidates = [r for r in runtimes if r.is_compatible is not False]
    candidates.sort(key=_runtime_sort_key, reverse=True)
    return candidates[0] if candidates else None


def _runtime_sort_key(r: RuntimeInfo):
    source_order = {
        RuntimeSource.CONDA: 3,
        RuntimeSource.SYSTEM: 2,
        RuntimeSource.TOOLCHAIN: 2,
        RuntimeSource.VENV: 1,
        RuntimeSource.PROJECT: 0,
        RuntimeSource.UNKNOWN: -1,
    }
    try:
        version = _parse_version(r.version)
    except ValueError:
        version = ()
    return (source_order.get(r.source, -1), version)


def _constraint_matches(actual: str, constraint: str) -> bool:
    match = re.match(r"^\s*(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)*)\s*$", constraint)
    if not match:
        return True
    op, ver_text = match.group(1), match.group(2)
    try:
        actual_v = _parse_version(actual)
        target_v = _parse_version(ver_text)
    except ValueError:
        return True
    return _compare(actual_v, target_v, op)
