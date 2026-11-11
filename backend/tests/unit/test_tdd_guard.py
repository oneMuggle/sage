"""Unit tests for TddGuard — TDD workflow enforcement."""

from backend.orchestration.tdd_guard import TddGuard


class TestIsTestPath:
    """Path recognition rules."""

    def test_python_test_prefix(self):
        assert TddGuard.is_test_path("test_foo.py")
        assert TddGuard.is_test_path("backend/tests/test_bar.py")

    def test_python_test_suffix(self):
        assert TddGuard.is_test_path("foo_test.py")

    def test_python_tests_dir(self):
        assert TddGuard.is_test_path("tests/test_bar.py")
        assert TddGuard.is_test_path("backend/tests/unit/test_baz.py")

    def test_python_conftest(self):
        assert TddGuard.is_test_path("conftest.py")
        assert TddGuard.is_test_path("tests/conftest.py")

    def test_ts_test_suffix(self):
        assert TddGuard.is_test_path("foo.test.ts")
        assert TddGuard.is_test_path("bar.spec.tsx")

    def test_ts_tests_dir(self):
        assert TddGuard.is_test_path("__tests__/foo.ts")
        assert TddGuard.is_test_path("src/__tests__/bar.tsx")

    def test_go_test_suffix(self):
        assert TddGuard.is_test_path("foo_test.go")

    def test_non_test_paths(self):
        assert not TddGuard.is_test_path("foo.py")
        assert not TddGuard.is_test_path("utils.ts")
        assert not TddGuard.is_test_path("main.go")
        assert not TddGuard.is_test_path("README.md")


class TestIsTestCommand:
    """Test command recognition."""

    def test_simple_commands(self):
        assert TddGuard.is_test_command("pytest")
        assert TddGuard.is_test_command("vitest")
        assert TddGuard.is_test_command("npm test")
        assert TddGuard.is_test_command("pnpm test")

    def test_python_variants(self):
        assert TddGuard.is_test_command("python -m pytest")
        assert TddGuard.is_test_command("python3 -m pytest")
        assert TddGuard.is_test_command("unittest discover")

    def test_npm_variants(self):
        assert TddGuard.is_test_command("npm run test")
        assert TddGuard.is_test_command("npm run test:unit")
        assert TddGuard.is_test_command("yarn test")

    def test_other_frameworks(self):
        assert TddGuard.is_test_command("go test")
        assert TddGuard.is_test_command("cargo test")
        assert TddGuard.is_test_command("mvn test")
        assert TddGuard.is_test_command("rspec")

    def test_chained_commands(self):
        assert TddGuard.is_test_command("npm run build && pytest")
        assert TddGuard.is_test_command("tsc --noEmit; pytest -q")

    def test_negative_cases(self):
        assert not TddGuard.is_test_command("npm run lint")
        assert not TddGuard.is_test_command("tsc --noEmit")
        assert not TddGuard.is_test_command("python main.py")
        assert not TddGuard.is_test_command("echo hello")


class TestNudge:
    """Nudge injection logic."""

    def test_nudge_write_before_test(self):
        guard = TddGuard(mode="tdd")
        nudge = guard.observe_write("src/foo.py")
        assert nudge is not None
        assert "测试文件" in nudge or "test" in nudge.lower()

    def test_nudge_impl_before_red(self):
        """TDD: test created but not run → nudge to run it first."""
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_foo.py")  # create test
        nudge = guard.observe_write("src/foo.py")  # impl without running test
        assert nudge is not None
        assert "尚未运行" in nudge or "red" in nudge.lower()

    def test_nudge_write_after_test_run(self):
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_foo.py")
        guard.observe_test("pytest", exit_code=1)  # red
        nudge = guard.observe_write("src/foo.py")
        assert nudge is None  # test ran, no nudge

    def test_nudge_only_once_per_type(self):
        guard = TddGuard(mode="tdd")
        nudge1 = guard.observe_write("src/foo.py")
        nudge2 = guard.observe_write("src/bar.py")
        assert nudge1 is not None
        assert nudge2 is None  # already nudged

    def test_no_nudge_in_fast_mode(self):
        guard = TddGuard(mode="fast")
        nudge = guard.observe_write("src/foo.py")
        assert nudge is None


class TestEvidence:
    """TDD evidence extraction."""

    def test_compliant_full_cycle(self):
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_foo.py")  # test first
        guard.observe_test("pytest", exit_code=1)  # red
        guard.observe_write("src/foo.py")  # impl
        guard.observe_test("pytest", exit_code=0)  # green
        assert guard.compliant

    def test_not_compliant_no_red(self):
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_foo.py")
        guard.observe_test("pytest", exit_code=0)  # green directly
        assert not guard.compliant

    def test_not_compliant_no_test_files(self):
        guard = TddGuard(mode="tdd")
        guard.observe_test("pytest", exit_code=1)
        guard.observe_test("pytest", exit_code=0)
        assert not guard.compliant

    def test_not_compliant_no_green(self):
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_foo.py")
        guard.observe_test("pytest", exit_code=1)  # red but no green
        assert not guard.compliant

    def test_green_after_impl_with_multiple_test_files(self):
        """green 判定基于事件顺序，而非 test_files 数量。"""
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_a.py")
        guard.observe_write("tests/test_b.py")
        guard.observe_test("pytest", exit_code=1)  # red
        guard.observe_write("src/foo.py")  # impl
        guard.observe_test("pytest", exit_code=0)  # green
        assert guard.green_seen
        assert guard.compliant

    def test_green_before_impl_does_not_count(self):
        """green 出现在最后一次 impl 写入之前 → 不算 green。"""
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_foo.py")
        guard.observe_test("pytest", exit_code=0)  # green 先
        guard.observe_write("src/foo.py")  # impl 后
        assert not guard.green_seen

    def test_snapshot_structure(self):
        guard = TddGuard(mode="tdd")
        guard.observe_write("tests/test_foo.py")
        guard.observe_test("pytest -q", exit_code=1)
        snapshot = guard.snapshot()
        assert "test_files" in snapshot
        assert "test_runs" in snapshot
        assert "red_seen" in snapshot
        assert "green_seen" in snapshot
        assert "compliant" in snapshot
