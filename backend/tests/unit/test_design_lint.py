"""Tests for design artifact lint engine (M2-3)."""
from __future__ import annotations

import pytest

from backend.design.lint import DesignLinter, LintReport, LintSeverity


@pytest.fixture()
def linter():
    return DesignLinter()


# ---------------------------------------------------------------------------
# P0 Rules: Positive cases (should trigger)
# ---------------------------------------------------------------------------


class TestP0NoDefaultIndigo:
    """Test no_default_indigo rule."""

    def test_detects_indigo_hex(self, linter):
        html = '<div style="color: #6366f1;">Text</div>'
        report = linter.lint(html)
        assert not report.ok
        assert report.error_count == 1
        assert report.issues[0].rule_id == "no_default_indigo"

    def test_detects_multiple_indigo_variants(self, linter):
        html = """
        <div style="color: #6366f1;">Primary</div>
        <div style="color: #4f46e5;">Secondary</div>
        <div style="background: #818cf8;">Accent</div>
        """
        report = linter.lint(html)
        indigo_issues = [i for i in report.issues if i.rule_id == "no_default_indigo"]
        assert len(indigo_issues) == 1  # Combined into one issue
        assert "3 uses" in indigo_issues[0].message

    def test_no_indigo_passes(self, linter):
        html = '<div style="color: #3b82f6;">Blue (not indigo)</div>'
        report = linter.lint(html)
        indigo_issues = [i for i in report.issues if i.rule_id == "no_default_indigo"]
        assert len(indigo_issues) == 0


class TestP0NoTrustGradient:
    """Test no_trust_gradient rule."""

    def test_detects_purple_to_blue_gradient(self, linter):
        html = '<div style="background: linear-gradient(to right, #8b5cf6, #3b82f6);"></div>'
        report = linter.lint(html)
        trust_issues = [i for i in report.issues if i.rule_id == "no_trust_gradient"]
        assert len(trust_issues) == 1
        assert trust_issues[0].severity == LintSeverity.ERROR

    def test_detects_reversed_gradient(self, linter):
        html = '<div style="background: linear-gradient(to left, #2563eb, #7c3aed);"></div>'
        report = linter.lint(html)
        trust_issues = [i for i in report.issues if i.rule_id == "no_trust_gradient"]
        assert len(trust_issues) == 1

    def test_non_trust_gradient_passes(self, linter):
        html = '<div style="background: linear-gradient(to right, #10b981, #059669);"></div>'
        report = linter.lint(html)
        trust_issues = [i for i in report.issues if i.rule_id == "no_trust_gradient"]
        assert len(trust_issues) == 0

    def test_text_gradient_exempt(self, linter):
        """Text gradients (background-clip:text) are a legitimate brand technique."""
        html = """
        <style>
        .g {
            background: linear-gradient(90deg, #a855f7, #60a5fa, #34d399);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }
        </style>
        """
        report = linter.lint(html)
        trust_issues = [i for i in report.issues if i.rule_id == "no_trust_gradient"]
        assert len(trust_issues) == 0


class TestP0NoEmojiIcons:
    """Test no_emoji_icons rule."""

    def test_detects_emoji_icons(self, linter):
        html = "<div>✨ Feature one 🚀 Feature two</div>"
        report = linter.lint(html)
        emoji_issues = [i for i in report.issues if i.rule_id == "no_emoji_icons"]
        assert len(emoji_issues) == 1
        assert "2 emoji" in emoji_issues[0].message

    def test_detects_multiple_emoji_types(self, linter):
        html = "<div>🎯 Goal: 100% 🔥 Hot 💡 Idea</div>"
        report = linter.lint(html)
        emoji_issues = [i for i in report.issues if i.rule_id == "no_emoji_icons"]
        assert len(emoji_issues) == 1
        assert "3 emoji" in emoji_issues[0].message

    def test_no_emoji_passes(self, linter):
        html = "<div>Feature one, Feature two</div>"
        report = linter.lint(html)
        emoji_issues = [i for i in report.issues if i.rule_id == "no_emoji_icons"]
        assert len(emoji_issues) == 0


class TestP0NoInventedMetrics:
    """Test no_invented_metrics rule."""

    def test_detects_10x_faster(self, linter):
        html = "<div>Our solution is 10x faster than competitors</div>"
        report = linter.lint(html)
        metrics_issues = [i for i in report.issues if i.rule_id == "no_invented_metrics"]
        assert len(metrics_issues) == 1

    def test_detects_99_percent_uptime(self, linter):
        html = "<div>Guaranteed 99.9% uptime SLA</div>"
        report = linter.lint(html)
        metrics_issues = [i for i in report.issues if i.rule_id == "no_invented_metrics"]
        assert len(metrics_issues) == 1

    def test_detects_save_hours(self, linter):
        html = "<div>Save 40 hours per week with automation</div>"
        report = linter.lint(html)
        metrics_issues = [i for i in report.issues if i.rule_id == "no_invented_metrics"]
        assert len(metrics_issues) == 1

    def test_real_data_passes(self, linter):
        html = "<div>Based on 2024 Q3 internal benchmarks</div>"
        report = linter.lint(html)
        metrics_issues = [i for i in report.issues if i.rule_id == "no_invented_metrics"]
        assert len(metrics_issues) == 0


class TestP0NoFillerCopy:
    """Test no_filler_copy rule."""

    def test_detects_lorem_ipsum(self, linter):
        html = "<p>Lorem ipsum dolor sit amet</p>"
        report = linter.lint(html)
        filler_issues = [i for i in report.issues if i.rule_id == "no_filler_copy"]
        assert len(filler_issues) == 1

    def test_detects_feature_one_two_three(self, linter):
        html = "<div>Feature One, Feature Two, Feature Three</div>"
        report = linter.lint(html)
        filler_issues = [i for i in report.issues if i.rule_id == "no_filler_copy"]
        assert len(filler_issues) >= 1

    def test_detects_placeholder(self, linter):
        html = '<img src="placeholder.png" alt="Placeholder image">'
        report = linter.lint(html)
        filler_issues = [i for i in report.issues if i.rule_id == "no_filler_copy"]
        assert len(filler_issues) == 1

    def test_detects_insert_text_here(self, linter):
        html = "<div>Insert text here</div>"
        report = linter.lint(html)
        filler_issues = [i for i in report.issues if i.rule_id == "no_filler_copy"]
        assert len(filler_issues) == 1

    def test_real_content_passes(self, linter):
        html = "<div>Advanced analytics dashboard for data teams</div>"
        report = linter.lint(html)
        filler_issues = [i for i in report.issues if i.rule_id == "no_filler_copy"]
        assert len(filler_issues) == 0


# ---------------------------------------------------------------------------
# P1 Rules (warnings, not errors)
# ---------------------------------------------------------------------------


class TestP1NoAiCardShape:
    """Test no_ai_card_shape rule."""

    def test_detects_card_shape(self, linter):
        html = '<div style="border-radius: 16px; border-left: 4px solid #6366f1;">Card</div>'
        report = linter.lint(html)
        card_issues = [i for i in report.issues if i.rule_id == "no_ai_card_shape"]
        assert len(card_issues) == 1
        assert card_issues[0].severity == LintSeverity.WARNING

    def test_small_border_radius_passes(self, linter):
        html = '<div style="border-radius: 4px; border-left: 4px solid #6366f1;">Card</div>'
        report = linter.lint(html)
        card_issues = [i for i in report.issues if i.rule_id == "no_ai_card_shape"]
        assert len(card_issues) == 0


class TestP1NoAiBuzzwords:
    """Test no_ai_buzzwords rule."""

    def test_detects_seamless(self, linter):
        html = "<div>Seamless integration with your workflow</div>"
        report = linter.lint(html)
        buzz_issues = [i for i in report.issues if i.rule_id == "no_ai_buzzwords"]
        assert len(buzz_issues) == 1
        assert buzz_issues[0].severity == LintSeverity.WARNING

    def test_detects_cutting_edge(self, linter):
        html = "<div>Cutting-edge AI technology</div>"
        report = linter.lint(html)
        buzz_issues = [i for i in report.issues if i.rule_id == "no_ai_buzzwords"]
        assert len(buzz_issues) == 1

    def test_detects_multiple_buzzwords(self, linter):
        html = "<div>Seamless, intuitive, powerful, cutting-edge solution</div>"
        report = linter.lint(html)
        buzz_issues = [i for i in report.issues if i.rule_id == "no_ai_buzzwords"]
        assert len(buzz_issues) == 1
        assert "4 AI buzzwords" in buzz_issues[0].message

    def test_concrete_language_passes(self, linter):
        html = "<div>REST API with OAuth 2.0 authentication</div>"
        report = linter.lint(html)
        buzz_issues = [i for i in report.issues if i.rule_id == "no_ai_buzzwords"]
        assert len(buzz_issues) == 0


# ---------------------------------------------------------------------------
# LintReport
# ---------------------------------------------------------------------------


class TestLintReport:
    """Test LintReport model."""

    def test_ok_when_no_errors(self):
        report = LintReport()
        assert report.ok is True
        assert report.error_count == 0
        assert report.warning_count == 0

    def test_not_ok_when_has_error(self):
        from backend.design.lint import LintIssue

        report = LintReport(
            issues=[
                LintIssue(
                    rule_id="test",
                    severity=LintSeverity.ERROR,
                    message="Test error",
                )
            ]
        )
        assert report.ok is False
        assert report.error_count == 1

    def test_ok_with_only_warnings(self):
        from backend.design.lint import LintIssue

        report = LintReport(
            issues=[
                LintIssue(
                    rule_id="test",
                    severity=LintSeverity.WARNING,
                    message="Test warning",
                )
            ]
        )
        assert report.ok is True
        assert report.warning_count == 1

    def test_to_dict(self):
        from backend.design.lint import LintIssue

        report = LintReport(
            issues=[
                LintIssue(
                    rule_id="test",
                    severity=LintSeverity.ERROR,
                    message="Test error",
                    line=42,
                    snippet="<test>",
                )
            ]
        )
        d = report.to_dict()
        assert d["ok"] is False
        assert d["error_count"] == 1
        assert d["warning_count"] == 0
        assert len(d["issues"]) == 1
        assert d["issues"][0]["rule_id"] == "test"
        assert d["issues"][0]["severity"] == "error"
        assert d["issues"][0]["line"] == 42


# ---------------------------------------------------------------------------
# auto_fix
# ---------------------------------------------------------------------------


class TestAutoFix:
    """Test automatic fixes."""

    def test_fixes_indigo_to_slate(self, linter):
        html = '<div style="color: #6366f1;">Text</div>'
        fixed = linter.auto_fix(html)
        assert "#6366f1" not in fixed
        assert "#475569" in fixed

    def test_fixes_multiple_indigo_variants(self, linter):
        html = """
        <div style="color: #6366f1;">Primary</div>
        <div style="color: #4f46e5;">Secondary</div>
        """
        fixed = linter.auto_fix(html)
        assert "#6366f1" not in fixed
        assert "#4f46e5" not in fixed
        assert "#475569" in fixed
        assert "#334155" in fixed


# ---------------------------------------------------------------------------
# generate_feedback
# ---------------------------------------------------------------------------


class TestGenerateFeedback:
    """Test feedback generation for LLM iteration."""

    def test_empty_feedback_when_clean(self, linter):
        html = "<div>Good content</div>"
        report = linter.lint(html)
        feedback = linter.generate_feedback(report)
        assert feedback == ""

    def test_feedback_includes_errors(self, linter):
        html = '<div style="color: #6366f1;">Bad color</div>'
        report = linter.lint(html)
        feedback = linter.generate_feedback(report)
        assert "Design Lint Feedback" in feedback
        assert "no_default_indigo" in feedback

    def test_feedback_includes_warnings(self, linter):
        html = "<div>Seamless integration</div>"
        report = linter.lint(html)
        feedback = linter.generate_feedback(report)
        assert "warning" in feedback.lower()
        assert "no_ai_buzzwords" in feedback


# ---------------------------------------------------------------------------
# Clean HTML passes all rules
# ---------------------------------------------------------------------------


class TestCleanHtml:
    """Test that clean HTML passes all rules."""

    def test_clean_professional_html(self, linter):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Analytics Dashboard</title>
            <style>
                .card {
                    background: #ffffff;
                    border: 1px solid #e2e8f0;
                    border-radius: 8px;
                    padding: 24px;
                }
                h1 { color: #1e293b; }
                p { color: #64748b; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Q3 2024 Performance</h1>
                <p>Revenue increased 23% compared to Q2, based on audited financials.</p>
            </div>
        </body>
        </html>
        """
        report = linter.lint(html)
        assert report.ok is True
        assert report.error_count == 0
