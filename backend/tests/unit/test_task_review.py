"""Unit tests for task-level review — prompt construction + verdict parsing."""

from backend.orchestration.task_review import (
    build_task_review_prompt,
    parse_review_verdict,
)


class TestBuildTaskReviewPrompt:
    def test_includes_goal(self):
        prompt = build_task_review_prompt(
            goal="实现用户登录接口",
            implementer_output="done",
            tdd_snapshot={"mode": "tdd"},
        )
        assert "实现用户登录接口" in prompt

    def test_includes_implementer_output(self):
        prompt = build_task_review_prompt(
            goal="G",
            implementer_output="新增 endpoint /api/v1/login",
            tdd_snapshot={"mode": "tdd"},
        )
        assert "/api/v1/login" in prompt

    def test_includes_tdd_evidence(self):
        prompt = build_task_review_prompt(
            goal="G",
            implementer_output="out",
            tdd_snapshot={
                "mode": "tdd",
                "test_files": ["backend/tests/unit/test_login.py"],
                "test_runs": [{"command": "pytest", "exit_code": 1}],
                "red_seen": True,
                "green_seen": False,
                "compliant": False,
            },
        )
        assert "test_login.py" in prompt
        assert "pytest" in prompt
        assert "red" in prompt.lower()

    def test_includes_acceptance_report(self):
        prompt = build_task_review_prompt(
            goal="G",
            implementer_output="out",
            tdd_snapshot={"mode": "tdd"},
            acceptance_report={
                "checks": [{"name": "pytest", "passed": False, "summary": "1 failed"}],
                "all_passed": False,
            },
        )
        assert "pytest" in prompt
        assert "1 failed" in prompt

    def test_fast_mode_omits_tdd_dimension(self):
        prompt = build_task_review_prompt(
            goal="G",
            implementer_output="out",
            tdd_snapshot={"mode": "fast"},
        )
        assert "TDD compliance" not in prompt

    def test_tdd_mode_includes_tdd_dimension(self):
        prompt = build_task_review_prompt(
            goal="G",
            implementer_output="out",
            tdd_snapshot={"mode": "tdd"},
        )
        assert "TDD compliance" in prompt

    def test_includes_output_format_instructions(self):
        prompt = build_task_review_prompt(
            goal="G",
            implementer_output="out",
            tdd_snapshot={"mode": "tdd"},
        )
        assert "VERDICT" in prompt
        assert "NEGATIVE_EVIDENCE" in prompt


class TestParseReviewVerdict:
    def test_pass(self):
        parsed = parse_review_verdict("[FACT] 登录接口已实现 (confidence: 0.9)\nVERDICT: PASS")
        assert parsed["verdict"] == "pass"
        assert len(parsed["assertions"]) == 1

    def test_fail_with_reason(self):
        parsed = parse_review_verdict(
            "[NEGATIVE_EVIDENCE] 缺少错误处理 (confidence: 0.9)\n"
            "VERDICT: FAIL\nREASON: 未处理密码错误"
        )
        assert parsed["verdict"] == "fail"
        assert parsed["reason"] == "未处理密码错误"

    def test_fail_without_reason(self):
        parsed = parse_review_verdict("VERDICT: FAIL")
        assert parsed["verdict"] == "fail"
        assert parsed["reason"]

    def test_no_verdict_line_falls_back_to_assertions(self):
        parsed = parse_review_verdict(
            "[FACT] 实现完整 (confidence: 0.9)\n[HYPOTHESIS] 可上线 (confidence: 0.6)"
        )
        assert parsed["verdict"] == "pass"
        assert len(parsed["assertions"]) == 2

    def test_negative_evidence_without_verdict_line_fails(self):
        parsed = parse_review_verdict("[NEGATIVE_EVIDENCE] 目标未达成 (confidence: 0.9)")
        assert parsed["verdict"] == "fail"

    def test_no_assertions_and_no_verdict_fails(self):
        parsed = parse_review_verdict("看起来还行")
        assert parsed["verdict"] == "fail"
        assert parsed["reason"]

    def test_explicit_pass_downgraded_by_negative_evidence(self):
        """fail-safe：显式 PASS 与高置信 NEGATIVE_EVIDENCE 冲突时判 fail。"""
        parsed = parse_review_verdict(
            "[NEGATIVE_EVIDENCE] 关键缺陷 (confidence: 0.9)\nVERDICT: PASS"
        )
        assert parsed["verdict"] == "fail"

    def test_explicit_fail_wins_over_assertions(self):
        parsed = parse_review_verdict(
            "[FACT] 看起来没问题 (confidence: 0.9)\nVERDICT: FAIL\nREASON: 仍有缺口"
        )
        assert parsed["verdict"] == "fail"
        assert parsed["reason"] == "仍有缺口"
