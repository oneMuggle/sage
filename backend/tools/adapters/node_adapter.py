"""Node.js 运行时适配器。

负责：

- 发现本机 Node.js（node）与常见包管理器（npm / pnpm / yarn / bun）。
- 通过 ``node -v`` 解析版本，识别 ``package.json`` 与 ``tsconfig.json``。
- 不进行依赖安装；只汇报发现到的工具链。
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
)

NODE_CANDIDATE_NAMES: Tuple[str, ...] = ("node",)
TOOL_CANDIDATE_NAMES: Tuple[str, ...] = ("npm", "pnpm", "yarn", "bun")
VERSION_RE = re.compile(r"v?(\d+\.\d+(?:\.\d+)?)")


class NodeAdapter:
    """Node.js 适配器。"""

    language = "javascript"

    def discover(
        self,
        request: ProbeRequest,
        ctx: AdapterContext,
    ) -> List[RuntimeInfo]:
        results: List[RuntimeInfo] = []
        seen: set[str] = set()

        for path in self._candidate_paths(NODE_CANDIDATE_NAMES, request.include_paths):
            info = self._probe_node(path, ctx)
            if info is None or info.path in seen:
                continue
            seen.add(info.path)
            results.append(info)

        if request.include_tools:
            for tool in TOOL_CANDIDATE_NAMES:
                for path in self._candidate_paths((tool,), request.include_paths):
                    info = self._probe_tool(path, tool, ctx)
                    if info is None or info.path in seen:
                        continue
                    seen.add(info.path)
                    results.append(info)

        return _mark_default(results)

    def inspect(
        self,
        runtime: RuntimeInfo,
        ctx: AdapterContext,
    ) -> RuntimeInfo:
        """对 Node.js 运行时额外读取 platform/exec。"""

        result = ctx.safe_run(
            [runtime.path, "-e", "console.log(JSON.stringify({platform: process.platform}))"],
            timeout=5.0,
        )
        info: dict = {}
        if result.exit_code == 0 and result.stdout:
            try:
                info = json.loads(result.stdout.strip().splitlines()[-1])
            except json.JSONDecodeError:
                info = {}
        raw = dict(runtime.raw)
        raw["platform"] = info.get("platform")
        return RuntimeInfo(
            language=runtime.language,
            name=runtime.name,
            path=runtime.path,
            version=runtime.version,
            source=runtime.source,
            is_default=runtime.is_default,
            is_compatible=runtime.is_compatible,
            compatibility_notes=runtime.compatibility_notes,
            capabilities=runtime.capabilities,
            diagnostics=runtime.diagnostics,
            raw=raw,
        )

    def build_command(
        self,
        request: ExecutionRequest,
        runtime: RuntimeInfo,
        ctx: AdapterContext,
    ) -> CommandRequest:
        return CommandRequest(
            argv=[runtime.path, "-"],
            stdin_payload=request.code,
        )

    # ------------------------------------------------------------------ 项目

    def discover_manifests(self, project_root: Path) -> List[ProjectManifest]:
        manifests: List[ProjectManifest] = []
        package_json = project_root / "package.json"
        if package_json.is_file():
            extras: dict = {}
            requires: Tuple[str, ...] = ()
            try:
                data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                data = {}
            engines = data.get("engines") if isinstance(data, dict) else None
            if isinstance(engines, dict):
                node_engine = engines.get("node")
                if isinstance(node_engine, str):
                    extras["engines_node"] = node_engine.strip()
            scripts = data.get("scripts") if isinstance(data, dict) else None
            if isinstance(scripts, dict):
                requires = tuple(sorted(scripts.keys()))
            manifests.append(
                ProjectManifest(
                    language=self.language,
                    path=str(package_json),
                    kind="package.json",
                    requires=requires,
                    extras=extras,
                )
            )
        tsconfig = project_root / "tsconfig.json"
        if tsconfig.is_file():
            manifests.append(
                ProjectManifest(
                    language="typescript",
                    path=str(tsconfig),
                    kind="tsconfig",
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
        nodes = [r for r in runtimes if r.language == self.language and r.name == "Node.js"]

        if any(m.kind == "package.json" for m in manifests) and not nodes:
            diagnostics.append(
                Diagnostic(
                    code="NODE_RUNTIME_MISSING",
                    severity=DiagnosticSeverity.ERROR,
                    message="项目包含 package.json，但本机未发现 Node.js",
                    related_path=str(project_root),
                )
            )

        level = DiagnosticLevel.SATISFIED
        if any(d.severity is DiagnosticSeverity.ERROR for d in diagnostics):
            level = DiagnosticLevel.UNSATISFIED
        elif any(d.severity is DiagnosticSeverity.WARNING for d in diagnostics):
            level = DiagnosticLevel.PARTIAL

        recommended = _pick_default(nodes)
        recommended_path = recommended.path if recommended else None
        return ProjectDiagnosis(
            level=level,
            diagnostics=diagnostics,
            manifests=manifests,
            recommended_runtime=recommended_path,
        )

    # ------------------------------------------------------------------ 私有

    def _candidate_paths(
        self,
        names: Tuple[str, ...],
        include_paths: Tuple[str, ...],
    ) -> Iterable[str]:
        path_env = os.environ.get("PATH", "")
        for directory in path_env.split(os.pathsep):
            if not directory:
                continue
            for name in names:
                for suffix in ("", ".exe", ".cmd"):
                    candidate = os.path.join(directory, name + suffix)
                    if Path(candidate).is_file():
                        yield candidate
        for extra in include_paths:
            if Path(extra).is_file():
                yield extra

    def _probe_node(self, path: str, ctx: AdapterContext) -> Optional[RuntimeInfo]:
        if not (Path(path).is_file() and os.access(path, os.X_OK)):
            return None
        result = ctx.safe_run([path, "-v"], timeout=5.0)
        if result.exit_code != 0:
            return None
        match = VERSION_RE.search(result.stdout or "")
        if not match:
            return None
        return RuntimeInfo(
            language=self.language,
            name="Node.js",
            path=path,
            version=match.group(1),
            source=RuntimeSource.SYSTEM,
            capabilities=RuntimeCapability(can_execute=True),
        )

    def _probe_tool(self, path: str, tool: str, ctx: AdapterContext) -> Optional[RuntimeInfo]:
        if not (Path(path).is_file() and os.access(path, os.X_OK)):
            return None
        result = ctx.safe_run([path, "--version"], timeout=5.0)
        if result.exit_code != 0:
            return None
        match = VERSION_RE.search(result.stdout or "")
        version = match.group(1) if match else "unknown"
        return RuntimeInfo(
            language=self.language,
            name=tool,
            path=path,
            version=version,
            source=RuntimeSource.TOOLCHAIN,
            capabilities=RuntimeCapability(can_execute=False, can_package_check=True),
        )


def _mark_default(results: List[RuntimeInfo]) -> List[RuntimeInfo]:
    """选择第一个 Node.js 作为默认；同名工具只保留一份。"""
    seen_kind: set[str] = set()
    default_set = False
    new_results: List[RuntimeInfo] = []
    for r in results:
        if r.name in seen_kind:
            continue
        seen_kind.add(r.name)
        new_results.append(
            RuntimeInfo(
                language=r.language,
                name=r.name,
                path=r.path,
                version=r.version,
                source=r.source,
                is_default=r.name == "Node.js" and not default_set,
                is_compatible=r.is_compatible,
                compatibility_notes=r.compatibility_notes,
                capabilities=r.capabilities,
                diagnostics=r.diagnostics,
                raw=r.raw,
            )
        )
        if r.name == "Node.js":
            default_set = True
    return new_results


def _pick_default(runtimes: List[RuntimeInfo]) -> Optional[RuntimeInfo]:
    for r in runtimes:
        if r.is_default:
            return r
    return runtimes[0] if runtimes else None
