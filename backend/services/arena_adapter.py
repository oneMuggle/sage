"""Arena.ai site-specific automation.

Drives a Sage-managed browser session to:
  - check login state
  - fill credentials (char-by-char to avoid bot detection)
  - detect and wait for CAPTCHA
  - submit messages with Thinking filter applied
  - wait for response completion
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ThinkingFilter(Enum):
    KEEP = "keep"
    STRIP = "strip"
    SUMMARIZE = "summarize"


#: CSS selectors for Arena.ai page elements (kept here for easy updates)
_SELECTORS = {
    "avatar": "header [data-testid='user-avatar']",
    "email_input": "input[name='email']",
    "password_input": "input[name='password']",
    "code_input": "input[name='verificationCode']",
    "chat_input": "[data-testid='chat-input'] textarea",
    "send_button": "[data-testid='send-button']",
    "captcha_iframe": "iframe[src*='hcaptcha'], iframe[src*='recaptcha']",
}


_THOUGHT_BLOCK_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)
_NAIVE_TOKEN_ESTIMATE = 0.75  # chars per token


class ArenaAdapter:
    """Thin wrapper around a browser session that drives Arena.ai pages."""

    def __init__(self, browser_session: Any):
        self._bs = browser_session

    # -- state detection --------------------------------------------------

    def check_login_state(self) -> bool:
        result = self._eval_js(
            f"!!document.querySelector({_SELECTORS['avatar']!r})"
        )
        return bool(result)

    def detect_captcha(self) -> bool:
        result = self._eval_js(
            f"!!document.querySelector({_SELECTORS['captcha_iframe']!r})"
        )
        return bool(result)

    # -- form filling -----------------------------------------------------

    def fill_login(self, email: str, password: str) -> None:
        self._focus_selector(_SELECTORS["email_input"])
        self._type_chars(email)
        self._focus_selector(_SELECTORS["password_input"])
        self._type_chars(password)

    def fill_verification_code(self, code: str) -> None:
        self._focus_selector(_SELECTORS["code_input"])
        self._type_chars(code)

    # -- message dispatch -------------------------------------------------

    def submit_message(
        self, text: str, thinking_filter: ThinkingFilter = ThinkingFilter.KEEP
    ) -> str:
        filtered = self.apply_thinking_filter(text, thinking_filter)
        self._focus_selector(_SELECTORS["chat_input"])
        self._type_chars(filtered)
        self._click_selector(_SELECTORS["send_button"])
        return filtered

    def wait_for_response(self, timeout_sec: int = 60) -> Optional[str]:
        """Stub: in production this would observe SSE completion via CDP.

        Returns the final response text when the stream ends, or None on timeout.
        Real implementation lands in Phase 3 task 11 with the Node worker.
        """
        logger.debug("wait_for_response called with timeout=%d", timeout_sec)
        return None  # TODO(phase-3): real SSE completion observer

    # -- Thinking filter --------------------------------------------------

    @staticmethod
    def apply_thinking_filter(text: str, mode: ThinkingFilter) -> str:
        if not isinstance(text, str) or mode == ThinkingFilter.KEEP:
            return text
        if mode == ThinkingFilter.STRIP:
            return _THOUGHT_BLOCK_RE.sub("", text).strip()
        if mode == ThinkingFilter.SUMMARIZE:
            def _replace(match: "re.Match[str]") -> str:
                inner = match.group(0)[len("<thinking>"):-len("</thinking>")]
                est_tokens = max(1, int(len(inner) * _NAIVE_TOKEN_ESTIMATE / 4))
                return f"[thinking: ~{est_tokens} tokens]"
            return _THOUGHT_BLOCK_RE.sub(_replace, text)
        return text

    # -- internal helpers -------------------------------------------------

    def _eval_js(self, expression: str) -> Any:
        return self._bs.cdp_command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        ).get("result", {}).get("value")

    def _focus_selector(self, selector: str) -> None:
        self._bs.cdp_command(
            "Runtime.evaluate",
            {"expression": f"document.querySelector({selector!r})?.focus()", "returnByValue": True},
        )

    def _click_selector(self, selector: str) -> None:
        self._bs.cdp_command(
            "Runtime.evaluate",
            {"expression": f"document.querySelector({selector!r})?.click()", "returnByValue": True},
        )

    def _type_chars(self, text: str) -> None:
        for ch in text:
            self._bs.cdp_command(
                "Input.dispatchKeyEvent",
                {"type": "char", "text": ch},
            )
