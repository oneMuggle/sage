"""PatternDetector — detect repeated tool call patterns in conversations.

This module provides the "重复模式挖掘" trigger for the background review
system. It analyzes sequences of tool calls, extracts signatures (tool name
+ sorted parameter keys), and identifies when the same signature recurs
beyond a configurable threshold.
"""

from collections import Counter
from typing import Optional


class PatternDetector:
    """Detect repeated tool call patterns within a conversation session."""

    def _extract_signature(self, tool_call: dict) -> str:
        """
        Extract signature: tool_name + sorted parameter keys.
        Ignores parameter values to detect repeated patterns.

        Args:
            tool_call: Dict with "tool" (str) and optional "args" (dict).

        Returns:
            Signature string in the format "tool_name:key1,key2,...".
        """
        tool_name = tool_call.get("tool", "unknown")
        args = tool_call.get("args", {})
        param_keys = sorted(args.keys())
        return f"{tool_name}:{','.join(param_keys)}"

    def detect_repeated_pattern(
        self,
        tool_calls: list[dict],
        threshold: int = 3,
        window_size: int = 5,
    ) -> Optional[dict]:
        """
        Detect repeated tool call patterns within a sliding window.

        Scans the entire ``tool_calls`` list and returns the most frequent
        signature that meets or exceeds ``threshold``.  ``window_size`` is
        accepted for API compatibility with future sliding-window refinements
        but is not used in the current counting implementation.

        Args:
            tool_calls: List of tool call dicts (each with "tool" and "args").
            threshold: Minimum repetitions to trigger a pattern.
            window_size: Sliding window size (reserved for future use).

        Returns:
            Dict with keys "signature" (str), "count" (int), and
            "tool_calls" (list of matching tool call dicts) if a pattern
            is found; otherwise None.
        """
        if len(tool_calls) < threshold:
            return None

        # Extract signatures for every tool call
        signatures = [self._extract_signature(tc) for tc in tool_calls]

        # Count occurrences
        counter = Counter(signatures)

        # Find the most common signature that meets the threshold
        for sig, count in counter.most_common():
            if count >= threshold:
                matching_calls = [
                    tc for tc, s in zip(tool_calls, signatures) if s == sig
                ]
                return {
                    "signature": sig,
                    "count": count,
                    "tool_calls": matching_calls,
                }

        return None
