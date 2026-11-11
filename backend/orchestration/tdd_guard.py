"""TddGuard — TDD workflow enforcement via tool-call observation.

Design: docs/superpowers/specs/2026-11-11-tdd-subagent-workflow-design.md §4

This module tracks test/impl writes and test runs per lane, generates nudges
when TDD order is violated (non-blocking), and extracts evidence for the
task-level reviewer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Recognition patterns
# ---------------------------------------------------------------------------

# Test file patterns (conservative — unrecognized defaults to non-test)
_TEST_PATH_PATTERNS = [
    # Python: test_*.py, *_test.py, tests/**, conftest.py
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)[^/]+_test\.py$"),
    re.compile(r"(^|/)tests/"),
    re.compile(r"(^|/)conftest\.py$"),
    # TS/JS: *.test.ts(x), *.spec.ts(x), __tests__/**
    re.compile(r"\.test\.tsx?$"),
    re.compile(r"\.spec\.tsx?$"),
    re.compile(r"(^|/)__tests__/"),
    # Go: *_test.go
    re.compile(r"_test\.go$"),
]

# Test command tokens (after splitting on && ; |)
_TEST_COMMAND_TOKENS = {
    "pytest",
    "vitest",
    "jest",
    "mocha",
    "unittest",
    "go",
    "cargo",
    "mvn",
    "gradle",
    "rspec",
    "phpunit",
    "dotnet",
}

# NPM-style test scripts
_NPM_TEST_PATTERNS = [
    re.compile(r"^(npm|yarn|pnpm)\s+(run\s+)?test(:\S+)?$"),
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TestRun:
    """A single test execution."""

    command: str
    exit_code: Optional[int]
    is_test: bool = True


@dataclass
class Violation:
    """TDD order violation."""

    kind: str  # "impl_before_test" | "impl_before_red"
    path: str
    message: str


# ---------------------------------------------------------------------------
# TddGuard
# ---------------------------------------------------------------------------


@dataclass
class TddGuard:
    """Per-lane TDD state tracker.

    Tracks test files created, test commands run, implementation writes,
    and generates nudges when TDD order is violated. Each violation type
    triggers at most one nudge (to avoid token waste).
    """

    mode: str = "tdd"  # "tdd" | "fast"
    test_files: List[str] = field(default_factory=list)
    test_runs: List[TestRun] = field(default_factory=list)
    impl_writes: List[str] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    # 有序事件流：(kind, payload)。kind ∈ {"test_write", "impl_write", "test_run"}。
    # green_seen 需要"最后一次 impl 写入之后"的 test_run，故必须保序。
    _events: List[Tuple[str, Any]] = field(default_factory=list, repr=False)
    _nudged: Set[str] = field(default_factory=set, repr=False)

    # ------------------------------------------------------------------
    # Static recognition helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_test_path(path: str) -> bool:
        """Check if path matches test file patterns."""
        if not path:
            return False
        return any(p.search(path) for p in _TEST_PATH_PATTERNS)

    @staticmethod
    def is_test_command(command: str) -> bool:
        """Check if command (or segment) is a test command.

        Splits on && ; | and checks each segment.
        """
        if not command:
            return False

        # Split on shell operators
        segments = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)

        for raw_seg in segments:
            seg = raw_seg.strip()
            if not seg:
                continue

            # Check NPM-style patterns
            if any(p.match(seg) for p in _NPM_TEST_PATTERNS):
                return True

            # Check tokens (first word or after python -m)
            tokens = seg.split()
            if not tokens:
                continue

            # python -m pytest / python3 -m pytest
            if (
                len(tokens) >= 3
                and tokens[0] in ("python", "python3")
                and tokens[1] == "-m"
                and tokens[2] in ("pytest", "unittest")
            ):
                return True

            # Direct command match
            cmd = tokens[0].split("/")[-1]  # handle path like /usr/bin/pytest
            if cmd in _TEST_COMMAND_TOKENS:
                return True

        return False

    # ------------------------------------------------------------------
    # Observation hooks (called by BaseTool._observe_call)
    # ------------------------------------------------------------------

    def observe_write(self, path: str) -> Optional[str]:
        """Record a file write. Returns nudge text if TDD order violated.

        Nudge is returned at most once per violation type.
        """
        if self.mode != "tdd":
            return None

        if self.is_test_path(path):
            self.test_files.append(path)
            self._events.append(("test_write", path))
            return None

        # Implementation write
        self.impl_writes.append(path)
        self._events.append(("impl_write", path))

        # Check if TDD order violated
        if not self.test_files:
            # No test files created yet
            nudge = self._maybe_nudge(
                "impl_before_test",
                "TDD 模式：本 lane 尚未创建测试文件。建议先写测试并运行，观察失败（red）后再实现。",
            )
            if nudge:
                self.violations.append(
                    Violation("impl_before_test", path, "写实现时 test_files 为空")
                )
            return nudge

        if not self.test_runs:
            # Test files exist but never ran
            nudge = self._maybe_nudge(
                "impl_before_red",
                "TDD 模式：已创建测试但尚未运行。建议先运行测试观察失败（red）。",
            )
            if nudge:
                self.violations.append(Violation("impl_before_red", path, "写实现时未先跑测试"))
            return nudge

        return None

    def observe_test(self, command: str, exit_code: Optional[int]) -> None:
        """Record a test command execution."""
        if not self.is_test_command(command):
            return
        run = TestRun(command=command, exit_code=exit_code)
        self.test_runs.append(run)
        self._events.append(("test_run", run))

    # ------------------------------------------------------------------
    # Evidence extraction
    # ------------------------------------------------------------------

    @property
    def red_seen(self) -> bool:
        """Any test run with exit_code != 0."""
        return any(r.exit_code is not None and r.exit_code != 0 for r in self.test_runs)

    @property
    def green_seen(self) -> bool:
        """最后一次 impl 写入之后，存在 exit_code == 0 的 test_run。"""
        last_impl_idx = -1
        for idx, (kind, _) in enumerate(self._events):
            if kind == "impl_write":
                last_impl_idx = idx
        if last_impl_idx < 0:
            return False
        for kind, payload in self._events[last_impl_idx + 1 :]:
            if kind == "test_run" and payload.exit_code == 0:
                return True
        return False

    @property
    def compliant(self) -> bool:
        """Full TDD compliance: test_files non-empty AND red_seen AND green_seen AND no violations."""
        return (
            bool(self.test_files)
            and self.red_seen
            and self.green_seen
            and not any(v.kind == "impl_before_test" for v in self.violations)
        )

    def snapshot(self) -> Dict[str, Any]:
        """Evidence snapshot for reviewer prompt."""
        return {
            "mode": self.mode,
            "test_files": list(self.test_files),
            "test_runs": [{"command": r.command, "exit_code": r.exit_code} for r in self.test_runs],
            "impl_writes": list(self.impl_writes),
            "violations": [
                {"kind": v.kind, "path": v.path, "message": v.message} for v in self.violations
            ],
            "red_seen": self.red_seen,
            "green_seen": self.green_seen,
            "compliant": self.compliant,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_nudge(self, key: str, message: str) -> Optional[str]:
        """Return nudge text if not already nudged for this key."""
        if key in self._nudged:
            return None
        self._nudged.add(key)
        return message
