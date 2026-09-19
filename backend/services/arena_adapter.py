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
from typing import Any, List, Optional

from backend.services.http_retry import retry_on_status

logger = logging.getLogger(__name__)


class ArenaAdapterError(Exception):
    """Base class for arena adapter failures."""


class SelectorNotFoundError(ArenaAdapterError):
    """Element selector matched no DOM node."""


class CDPCommandError(ArenaAdapterError):
    """CDP command returned an error or no value."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        """Fill email + password fields. Retries on 429 per spec §6.2."""
        def _do_fill() -> None:
            self._focus_selector(_SELECTORS["email_input"])
            self._type_chars(email)
            self._focus_selector(_SELECTORS["password_input"])
            self._type_chars(password)

        retry_on_status(
            _do_fill,
            retry_statuses=(429,),
            max_attempts=3,
            base_delay=1.0,
        )

    def fill_verification_code(self, code: str) -> None:
        """Fill verification code field. Retries on 429 per spec §6.2."""
        def _do_fill() -> None:
            self._focus_selector(_SELECTORS["code_input"])
            self._type_chars(code)

        retry_on_status(
            _do_fill,
            retry_statuses=(429,),
            max_attempts=3,
            base_delay=1.0,
        )

    # -- message dispatch -------------------------------------------------

    def submit_message(
        self, text: str, thinking_filter: ThinkingFilter = ThinkingFilter.KEEP
    ) -> str:
        """Type text and click send. Retries on 429 per spec §6.2."""
        filtered = self.apply_thinking_filter(text, thinking_filter)

        def _do_submit() -> str:
            self._focus_selector(_SELECTORS["chat_input"])
            self._type_chars(filtered)
            self._click_selector(_SELECTORS["send_button"])
            return filtered

        return retry_on_status(
            _do_submit,
            retry_statuses=(429,),
            max_attempts=3,
            base_delay=1.0,
        )

    def wait_for_response(self, timeout_sec: int = 60) -> Optional[str]:
        """Stub: requires Phase-3 SSE completion observer."""
        raise NotImplementedError(
            f"wait_for_response not implemented (timeout_sec={timeout_sec}); "
            "see docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md §3.4"
        )

    # -- registration assist (best-effort form filling; CAPTCHA stays manual) --

    #: 候选选择器：arena 注册页/表单的具体结构会随站点改版漂移，按顺序试，
    #: 全部失配抛 SelectorNotFoundError —— 上层降级为「请手动操作」而非失败。
    SIGNUP_EMAIL_SELECTORS = [
        "input[name='email']",
        "input[type='email']",
        "input[autocomplete='email']",
    ]
    SUBMIT_SELECTORS = [
        "button[type='submit']",
        "form button:not([type='reset']):not([type='button'])",
    ]

    def open_page(self, url: str) -> None:
        """Navigate the current page target to ``url`` (user-visible browser)."""
        result = self._bs.cdp_command("Page.navigate", {"url": url})
        if not isinstance(result, dict):
            raise CDPCommandError(f"Page.navigate returned non-dict: {result!r}")

    def current_url(self) -> str:
        result = self._eval_js("location.href")
        return str(result or "")

    def fill_first_input(self, selectors: List[str], text: str) -> str:
        """Focus the first matching selector and type ``text``. Returns the
        selector that matched; raises SelectorNotFoundError when none do."""
        last_error: Optional[Exception] = None
        for selector in selectors:
            try:
                self._focus_selector(selector)
            except (SelectorNotFoundError, CDPCommandError) as exc:
                last_error = exc
                continue
            self._type_chars(text)
            return selector
        raise SelectorNotFoundError(
            f"no signup input matched any of {selectors!r}"
        ) from last_error

    def click_first(self, selectors: List[str]) -> str:
        """Click the first matching selector; raises SelectorNotFoundError
        when none do."""
        for selector in selectors:
            try:
                self._click_selector(selector)
                return selector
            except (SelectorNotFoundError, CDPCommandError):
                continue
        raise SelectorNotFoundError(f"no submit button matched any of {selectors!r}")

    def fill_signup_email(self, email: str) -> str:
        return self.fill_first_input(self.SIGNUP_EMAIL_SELECTORS, email)

    def submit_visible_form(self) -> str:
        return self.click_first(self.SUBMIT_SELECTORS)

    def fill_password_inputs(self, password: str) -> int:
        """Type ``password`` into every input[type=password] on the page
        (covers password + confirm fields). Returns the field count."""
        count = self._eval_js(
            '(function(){return document.querySelectorAll'
            '("input[type=password]").length;})()'
        )  # 无插值，纯字面量
        count = int(count or 0)
        if count < 1:
            raise SelectorNotFoundError("no input[type=password] on page")
        for index in range(count):
            expr = (
                '(function(){var els=document.querySelectorAll'
                '("input[type=password]");'
                f'var el=els[{index}];'
                'if(!el){return false;}el.focus();return true;})()'
            )
            result = self._eval_js(expr)
            if not result:
                raise SelectorNotFoundError(f"password input #{index} not focusable")
            self._type_chars(password)
        return count

    # -- Thinking filter --------------------------------------------------

    @staticmethod
    def apply_thinking_filter(text: str, mode: ThinkingFilter) -> str:
        if not isinstance(text, str) or mode == ThinkingFilter.KEEP:
            return text
        if mode == ThinkingFilter.STRIP:
            return _THOUGHT_BLOCK_RE.sub("", text).strip()
        if mode == ThinkingFilter.SUMMARIZE:
            def _replace(match: re.Match[str]) -> str:
                inner = match.group(0)[len("<thinking>"):-len("</thinking>")]
                est_tokens = max(1, int(len(inner) * _NAIVE_TOKEN_ESTIMATE / 4))
                return f"[thinking: ~{est_tokens} tokens]"
            return _THOUGHT_BLOCK_RE.sub(_replace, text)
        return text

    # -- internal helpers -------------------------------------------------

    def _eval_js(self, expression: str) -> Any:
        try:
            result = self._bs.cdp_command(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
            )
        except Exception as exc:
            raise CDPCommandError(
                f"Runtime.evaluate failed: {exc}",
                status_code=getattr(exc, "status_code", None),
            ) from exc
        if not isinstance(result, dict):
            raise CDPCommandError(
                f"Runtime.evaluate returned non-dict: {result!r}"
            )
        inner = result.get("result")
        if inner is not None and "value" not in inner:
            raise CDPCommandError(
                f"Runtime.evaluate missing 'value' key: {result!r}"
            )
        if inner is None:
            return None
        return inner.get("value")

    def _focus_selector(self, selector: str) -> None:
        # 表达式必须返回值：`el?.focus()` 求值为 undefined，CDP returnByValue
        # 不带 value 键会让 _eval_js 抛 CDPCommandError。用 IIFE 返回布尔。
        result = self._eval_js(
            f"(function(){{var el=document.querySelector({selector!r});"
            f"if(!el){{return false;}}el.focus();return true;}})()"
        )
        if not result:
            raise SelectorNotFoundError(
                f"selector matched no element: {selector!r}"
            )

    def _click_selector(self, selector: str) -> None:
        result = self._eval_js(
            f"(function(){{var el=document.querySelector({selector!r});"
            f"if(!el){{return false;}}el.click();return true;}})()"
        )
        if not result:
            raise SelectorNotFoundError(
                f"selector matched no element: {selector!r}"
            )

    def _type_chars(self, text: str) -> None:
        for i, ch in enumerate(text):
            try:
                self._bs.cdp_command(
                    "Input.dispatchKeyEvent",
                    {"type": "char", "text": ch},
                )
            except Exception as exc:
                raise CDPCommandError(
                    f"Input.dispatchKeyEvent failed at char {i}/{len(text)}: {exc}",
                    status_code=getattr(exc, "status_code", None),
                ) from exc
