"""Unit tests for PatternDetector — repeated tool trace detection."""


from backend.skills.pattern_detector import PatternDetector

# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------


class TestExtractSignature:
    """Tests for PatternDetector._extract_signature."""

    def test_extract_signature_ignores_parameter_values(self):
        """Same tool + same param keys → same signature regardless of values."""
        detector = PatternDetector()
        tc1 = {"tool": "read", "args": {"path": "/a"}}
        tc2 = {"tool": "read", "args": {"path": "/b"}}

        sig1 = detector._extract_signature(tc1)
        sig2 = detector._extract_signature(tc2)

        assert sig1 == sig2  # Same signature despite different paths
        assert sig1 == "read:path"

    def test_extract_signature_sorts_param_keys(self):
        """Parameter keys are sorted alphabetically for deterministic signatures."""
        detector = PatternDetector()
        tc = {"tool": "edit", "args": {"path": "/a", "old_string": "x", "new_string": "y"}}

        sig = detector._extract_signature(tc)
        # Keys sorted: new_string, old_string, path
        assert sig == "edit:new_string,old_string,path"

    def test_extract_signature_no_args(self):
        """Tool call with no args produces signature with empty param section."""
        detector = PatternDetector()
        tc = {"tool": "list_files", "args": {}}

        sig = detector._extract_signature(tc)
        assert sig == "list_files:"

    def test_extract_signature_missing_args(self):
        """Tool call missing 'args' key still produces a valid signature."""
        detector = PatternDetector()
        tc = {"tool": "bash"}

        sig = detector._extract_signature(tc)
        assert sig == "bash:"

    def test_extract_signature_missing_tool(self):
        """Tool call missing 'tool' key uses 'unknown' as tool name."""
        detector = PatternDetector()
        tc = {"args": {"path": "/a"}}

        sig = detector._extract_signature(tc)
        assert sig == "unknown:path"


# ---------------------------------------------------------------------------
# Repeated pattern detection
# ---------------------------------------------------------------------------


class TestDetectRepeatedPattern:
    """Tests for PatternDetector.detect_repeated_pattern."""

    def test_detect_repeated_pattern_with_3_repeats(self):
        """3 read:path calls interleaved with edit:path → pattern detected."""
        tool_calls = [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "edit", "args": {"path": "/b"}},
            {"tool": "read", "args": {"path": "/c"}},  # 2nd read
            {"tool": "edit", "args": {"path": "/d"}},
            {"tool": "read", "args": {"path": "/e"}},  # 3rd read
        ]
        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern(tool_calls, threshold=3)

        assert pattern is not None
        assert pattern["signature"] == "read:path"
        assert pattern["count"] == 3
        assert len(pattern["tool_calls"]) == 3

    def test_no_pattern_below_threshold(self):
        """Only 2 reads when threshold=3 → no pattern."""
        tool_calls = [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "edit", "args": {"path": "/b"}},
            {"tool": "read", "args": {"path": "/c"}},  # Only 2 reads
        ]
        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern(tool_calls, threshold=3)
        assert pattern is None

    def test_empty_tool_calls(self):
        """Empty list → no pattern."""
        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern([], threshold=3)
        assert pattern is None

    def test_fewer_than_threshold_calls(self):
        """Fewer total calls than threshold → no pattern."""
        tool_calls = [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "read", "args": {"path": "/b"}},
        ]
        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern(tool_calls, threshold=3)
        assert pattern is None

    def test_exact_threshold(self):
        """Exactly threshold repetitions → pattern detected."""
        tool_calls = [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "read", "args": {"path": "/b"}},
            {"tool": "read", "args": {"path": "/c"}},
        ]
        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern(tool_calls, threshold=3)

        assert pattern is not None
        assert pattern["signature"] == "read:path"
        assert pattern["count"] == 3

    def test_multiple_patterns_returns_highest_count(self):
        """When multiple patterns exceed threshold, return the most frequent."""
        tool_calls = [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "edit", "args": {"path": "/b"}},
            {"tool": "read", "args": {"path": "/c"}},
            {"tool": "edit", "args": {"path": "/d"}},
            {"tool": "read", "args": {"path": "/e"}},
            {"tool": "edit", "args": {"path": "/f"}},
            {"tool": "edit", "args": {"path": "/g"}},  # 4 edits vs 3 reads
        ]
        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern(tool_calls, threshold=3)

        assert pattern is not None
        # edit has 4 occurrences, should win over read's 3
        assert pattern["count"] == 4
        assert pattern["signature"] == "edit:path"

    def test_tool_calls_in_result_are_original_dicts(self):
        """Returned tool_calls are the original dicts, not copies."""
        tc1 = {"tool": "read", "args": {"path": "/a"}}
        tc2 = {"tool": "read", "args": {"path": "/b"}}
        tc3 = {"tool": "read", "args": {"path": "/c"}}
        tool_calls = [tc1, tc2, tc3]

        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern(tool_calls, threshold=3)

        assert pattern is not None
        # Verify the returned tool_calls are references to the originals
        assert pattern["tool_calls"][0] is tc1
        assert pattern["tool_calls"][1] is tc2
        assert pattern["tool_calls"][2] is tc3

    def test_custom_threshold(self):
        """Custom threshold=2 detects patterns with just 2 repetitions."""
        tool_calls = [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "edit", "args": {"path": "/b"}},
            {"tool": "read", "args": {"path": "/c"}},
        ]
        detector = PatternDetector()
        pattern = detector.detect_repeated_pattern(tool_calls, threshold=2)

        assert pattern is not None
        assert pattern["count"] == 2

    def test_window_size_parameter_accepted(self):
        """window_size parameter is accepted (sliding window support)."""
        tool_calls = [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "read", "args": {"path": "/b"}},
            {"tool": "read", "args": {"path": "/c"}},
        ]
        detector = PatternDetector()
        # Should not raise even with explicit window_size
        pattern = detector.detect_repeated_pattern(
            tool_calls, threshold=3, window_size=5
        )
        assert pattern is not None
