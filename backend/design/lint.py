"""Design artifact lint engine (M2-3).

Detects anti-patterns and AI-generated design "tells" in HTML artifacts.
Rules are classified as P0 (must-fix) and P1 (recommended).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class LintSeverity(str, Enum):
    """Severity level for lint issues."""

    ERROR = "error"  # P0: must fix
    WARNING = "warning"  # P1: recommended fix


@dataclass
class LintIssue:
    """A single lint issue found in the HTML."""

    rule_id: str
    severity: LintSeverity
    message: str
    line: Optional[int] = None
    snippet: Optional[str] = None


@dataclass
class LintReport:
    """Aggregated lint results."""

    issues: List[LintIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True if no P0 issues."""
        return not any(i.severity == LintSeverity.ERROR for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == LintSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == LintSeverity.WARNING)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [
                {
                    "rule_id": i.rule_id,
                    "severity": i.severity.value,
                    "message": i.message,
                    "line": i.line,
                    "snippet": i.snippet,
                }
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# P0 Rules (must fix)
# ---------------------------------------------------------------------------

# Default indigo colors commonly used by AI
_DEFAULT_INDIGO_PATTERN = re.compile(
    r"#(?:6366f1|4f46e5|4338ca|3730a3|818cf8|a5b4fc|c7d2fe|e0e7ff)",
    re.IGNORECASE,
)

# "Trust gradient" - purple-to-blue gradients that scream AI
_TRUST_GRADIENT_PATTERN = re.compile(
    r"linear-gradient\([^)]*(?:#8b5cf6|#7c3aed|#6366f1|#4f46e5)[^)]*(?:#3b82f6|#2563eb|#1d4ed8)\)"
    r"|"
    r"linear-gradient\([^)]*(?:#3b82f6|#2563eb|#1d4ed8)[^)]*(?:#8b5cf6|#7c3aed|#6366f1|#4f46e5)\)",
    re.IGNORECASE,
)

# Emoji used as icons (common AI tell)
_EMOJI_ICONS_PATTERN = re.compile(
    r"[✨🚀🎯💡🔥⚡️🌟💎🎨📊📈🤖🧠💪✅❌⚠️🎉🎊]"
)

# Invented metrics / fake statistics
_INVENTED_METRICS_PATTERN = re.compile(
    r"\b(?:10x|100x|1000x|10x\s+faster|99\.9%?|99\.99%?|100%\s+uptime|"
    r"increase.*by\s+\d+x|reduce.*by\s+\d+%|"
    r"save\s+\d+\s+hours|boost.*\d+%)\b",
    re.IGNORECASE,
)

# Filler copy patterns
_FILLER_COPY_PATTERNS = [
    re.compile(r"\blorem\s+ipsum\b", re.IGNORECASE),
    re.compile(r"\bfeature\s+one\b|\bfeature\s+two\b|\bfeature\s+three\b", re.IGNORECASE),
    re.compile(r"\byour\s+company\s+name\b", re.IGNORECASE),
    re.compile(r"\binsert\s+(?:text|content|image|logo)\s+here\b", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# P1 Rules (recommended fix)
# ---------------------------------------------------------------------------

# AI-typical card shape: rounded corners + colored left border (may be in same style attr)
_AI_CARD_SHAPE_PATTERN = re.compile(
    r"border-radius:\s*(?:12|16|20|24)px[^\"']*(?:;|\s)*border-left:\s*\d+px\s+solid",
    re.IGNORECASE,
)

# Overuse of the word "seamless" / "intuitive" / "powerful"
_AI_BUZZWORDS_PATTERN = re.compile(
    r"\b(?:seamless|seamlessly|intuitive|intuitively|powerful|powerfully|"
    r"cutting-edge|next-generation|revolutionary|game-changer)\b",
    re.IGNORECASE,
)

# Detect text-clip gradients declared shortly after a gradient value
_TEXT_CLIP_PATTERN = re.compile(
    r"background-clip\s*:\s*text|-webkit-background-clip\s*:\s*text",
    re.IGNORECASE,
)


def _is_text_gradient(html: str, gradient_end: int) -> bool:
    """True when a text-clip declaration follows the gradient (same rule block)."""
    tail = html[gradient_end:gradient_end + 200]
    return bool(_TEXT_CLIP_PATTERN.search(tail))


class DesignLinter:
    """Lint a generated HTML design for anti-patterns."""

    def lint(self, html: str) -> LintReport:
        """Run all lint rules and return a report."""
        report = LintReport()

        # Rule: default AI indigo palette
        if matches := _DEFAULT_INDIGO_PATTERN.findall(html):
            unique_colors = {m.lower() for m in matches}
            report.issues.append(
                LintIssue(
                    rule_id="no_default_indigo",
                    severity=LintSeverity.ERROR,
                    message=(
                        f"Found {len(matches)} uses of default AI indigo colors "
                        f"({', '.join(sorted(unique_colors)[:3])}...). "
                        "Choose brand-specific colors instead."
                    ),
                    snippet=matches[0],
                )
            )

        # Rule: trust gradient (background only; text-clip gradients are
        # a legitimate brand technique)
        if gradient_matches := _TRUST_GRADIENT_PATTERN.finditer(html):
            background_hits = [
                m for m in gradient_matches
                if not _is_text_gradient(html, m.end())
            ]
            if background_hits:
                first = background_hits[0].group(0)
                report.issues.append(
                    LintIssue(
                        rule_id="no_trust_gradient",
                        severity=LintSeverity.ERROR,
                        message=(
                            "Found 'trust gradient' (purple-to-blue background). "
                            "This is a common AI-generated design pattern. "
                            "Use a brand-appropriate gradient or solid color."
                        ),
                        snippet=first[:60] + "..." if len(first) > 60 else first,
                    )
                )

        # Rule: emoji used as icons
        if matches := _EMOJI_ICONS_PATTERN.findall(html):
            unique_emojis = set(matches)
            report.issues.append(
                LintIssue(
                    rule_id="no_emoji_icons",
                    severity=LintSeverity.ERROR,
                    message=(
                        f"Found {len(matches)} emoji icons ({', '.join(list(unique_emojis)[:5])}). "
                        "Replace with SVG icons or text labels."
                    ),
                )
            )

        # Rule: invented metrics
        if matches := _INVENTED_METRICS_PATTERN.findall(html):
            report.issues.append(
                LintIssue(
                    rule_id="no_invented_metrics",
                    severity=LintSeverity.ERROR,
                    message=(
                        f"Found {len(matches)} invented metrics "
                        f"({', '.join(matches[:3])}...). "
                        "Use real data or remove specific claims."
                    ),
                )
            )

        # Rule: filler copy
        for pattern in _FILLER_COPY_PATTERNS:
            if matches := pattern.findall(html):
                report.issues.append(
                    LintIssue(
                        rule_id="no_filler_copy",
                        severity=LintSeverity.ERROR,
                        message=(
                            f"Found filler copy ({', '.join(matches[:3])}...). "
                            "Replace with actual content."
                        ),
                    )
                )

        # Rule: AI-typical card shape (warning)
        if matches := _AI_CARD_SHAPE_PATTERN.findall(html):
            report.issues.append(
                LintIssue(
                    rule_id="no_ai_card_shape",
                    severity=LintSeverity.WARNING,
                    message=(
                        f"Found {len(matches)} instances of AI-typical card shape "
                        "(large border-radius + colored left border). "
                        "Consider varying the design."
                    ),
                )
            )

        # Rule: AI buzzwords (warning)
        if matches := _AI_BUZZWORDS_PATTERN.findall(html):
            unique_words = {m.lower() for m in matches}
            report.issues.append(
                LintIssue(
                    rule_id="no_ai_buzzwords",
                    severity=LintSeverity.WARNING,
                    message=(
                        f"Found {len(matches)} AI buzzwords "
                        f"({', '.join(sorted(unique_words)[:4])}...). "
                        "Use more specific, concrete language."
                    ),
                )
            )

        return report

    def auto_fix(self, html: str, issues: list[LintIssue] | None = None) -> str:
        """Apply safe automatic fixes.

        Currently fixes:
        - Replaces default indigo with a neutral slate palette
        """
        if issues is None:
            report = self.lint(html)
            issues = report.issues

        fixable_rules = {"no_default_indigo"}
        fixable = {i.rule_id for i in issues if i.rule_id in fixable_rules}

        if "no_default_indigo" in fixable:
            # Replace indigo palette with slate (neutral, professional)
            html = re.sub(r"#6366f1", "#475569", html, flags=re.IGNORECASE)
            html = re.sub(r"#4f46e5", "#334155", html, flags=re.IGNORECASE)
            html = re.sub(r"#4338ca", "#1e293b", html, flags=re.IGNORECASE)
            html = re.sub(r"#3730a3", "#0f172a", html, flags=re.IGNORECASE)
            html = re.sub(r"#818cf8", "#64748b", html, flags=re.IGNORECASE)
            html = re.sub(r"#a5b4fc", "#94a3b8", html, flags=re.IGNORECASE)
            html = re.sub(r"#c7d2fe", "#cbd5e1", html, flags=re.IGNORECASE)
            html = re.sub(r"#e0e7ff", "#e2e8f0", html, flags=re.IGNORECASE)

        return html

    def generate_feedback(self, report: LintReport) -> str:
        """Generate human-readable feedback for LLM iteration."""
        if report.ok and report.warning_count == 0:
            return ""

        lines = ["## Design Lint Feedback", ""]

        if report.error_count > 0:
            lines.append(f"**{report.error_count} error(s) to fix:**")
            lines.append("")
            for issue in report.issues:
                if issue.severity == LintSeverity.ERROR:
                    lines.append(f"- **{issue.rule_id}**: {issue.message}")
            lines.append("")

        if report.warning_count > 0:
            lines.append(f"**{report.warning_count} warning(s):**")
            lines.append("")
            for issue in report.issues:
                if issue.severity == LintSeverity.WARNING:
                    lines.append(f"- {issue.rule_id}: {issue.message}")

        return "\n".join(lines)


__all__ = [
    "DesignLinter",
    "LintIssue",
    "LintReport",
    "LintSeverity",
]
