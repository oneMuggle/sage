"""
Approval Token system for multi-agent orchestration.

Implements typed approval tokens for privileged operations (force push,
cross-branch merge, lane override, etc.). Mirrors claw-code's approval-token
contract:

- An approval token is a typed artifact, not prose.
- Consumption requires strict equality on actor / action / repo / branch /
  commit scope to prevent scope expansion.
- Tokens have an expiry and a max_uses (default 1, i.e. one-time use).
- Tokens can be revoked before consumption.
- Delegation traceability: any executor using the token can prove which
  approval artifact authorized the action.

References:
- claw-code `rust/crates/runtime/src/approval_tokens.rs`
- sage plan: docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md
"""

from __future__ import annotations
from typing import Dict, List, Optional

import secrets
import threading
import time
from dataclasses import dataclass
from enum import Enum


class DenyReason(str, Enum):
    """Reasons why an approval token consumption is denied."""

    NOT_FOUND = "not_found"
    REVOKED = "revoked"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    ACTOR_MISMATCH = "actor_mismatch"
    ACTION_MISMATCH = "action_mismatch"
    REPO_MISMATCH = "repo_mismatch"
    BRANCH_MISMATCH = "branch_mismatch"
    COMMIT_MISMATCH = "commit_mismatch"


@dataclass
class ApprovalToken:
    """A typed, scoped, time-bounded approval for a privileged action."""

    token_id: str
    approver: str
    policy_exception: str
    action: str
    scope_repo: str
    scope_branch: str
    scope_commit: Optional[str]
    issued_at: int
    expires_at: int
    max_uses: int = 1
    consumed_count: int = 0
    revoked: bool = False

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "approver": self.approver,
            "policy_exception": self.policy_exception,
            "action": self.action,
            "scope_repo": self.scope_repo,
            "scope_branch": self.scope_branch,
            "scope_commit": self.scope_commit,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
            "consumed_count": self.consumed_count,
            "revoked": self.revoked,
        }


@dataclass
class TokenUseResult:
    """Outcome of a `consume` attempt."""

    granted: bool
    token_id: str
    reason: Optional[DenyReason] = None
    message: str = ""


class ApprovalTokenStore:
    """In-memory store for `ApprovalToken`s.

    Thread-safety: a coarse `threading.Lock` guards the consume path so
    concurrent callers cannot exceed `max_uses`. The lock is intentionally
    not re-entrant — operations are short.
    """

    def __init__(self) -> None:
        self._tokens: Dict[str, ApprovalToken] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Issue / access
    # ------------------------------------------------------------------

    def issue(
        self,
        approver: str,
        policy_exception: str,
        action: str,
        scope_repo: str,
        scope_branch: str,
        scope_commit: Optional[str] = None,
        ttl_ms: int = 60_000,
        max_uses: int = 1,
    ) -> ApprovalToken:
        """Mint a new approval token."""
        now = int(time.time() * 1000)
        token_id = f"apt_{secrets.token_hex(8)}"
        token = ApprovalToken(
            token_id=token_id,
            approver=approver,
            policy_exception=policy_exception,
            action=action,
            scope_repo=scope_repo,
            scope_branch=scope_branch,
            scope_commit=scope_commit,
            issued_at=now,
            expires_at=now + ttl_ms,
            max_uses=max_uses,
            consumed_count=0,
            revoked=False,
        )
        with self._lock:
            self._tokens[token_id] = token
        return token

    def get(self, token_id: str) -> ApprovalToken | None:
        """Return the token with the given id, or None."""
        return self._tokens.get(token_id)

    def revoke(self, token_id: str) -> None:
        """Revoke a token. Raises `KeyError` if not found."""
        token = self._tokens.get(token_id)
        if token is None:
            raise KeyError(f"token {token_id!r} not found")
        with self._lock:
            token.revoked = True

    def list_active(self) -> List[ApprovalToken]:
        """Return all non-revoked tokens currently in the store."""
        return [t for t in self._tokens.values() if not t.revoked]

    # ------------------------------------------------------------------
    # Consume — 8 validation gates
    # ------------------------------------------------------------------

    def consume(  # noqa: PLR0911 — one return per validation gate is intentional
        self,
        token_id: str,
        actor: str,
        action: str,
        repo: str,
        branch: str,
        commit: Optional[str] = None,
    ) -> TokenUseResult:
        """Attempt to consume an approval token.

        Returns a `TokenUseResult` indicating granted/denied + reason.
        On grant, the token's `consumed_count` is incremented atomically.
        """
        token = self._tokens.get(token_id)
        if token is None:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.NOT_FOUND,
                message="token not found",
            )

        # Gate 2: revoked (check first; cheaper than expiry)
        if token.revoked:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.REVOKED,
                message="token has been revoked",
            )

        # Gate 3: expired
        now = int(time.time() * 1000)
        if now >= token.expires_at:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.EXPIRED,
                message="token has expired",
            )

        # Gates 5–8: scope matching (actor / action / repo / branch / commit)
        if actor != token.approver:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.ACTOR_MISMATCH,
                message=f"actor {actor!r} does not match approver {token.approver!r}",
            )
        if action != token.action:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.ACTION_MISMATCH,
                message=f"action {action!r} does not match {token.action!r}",
            )
        if repo != token.scope_repo:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.REPO_MISMATCH,
                message=f"repo {repo!r} does not match {token.scope_repo!r}",
            )
        if branch != token.scope_branch:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.BRANCH_MISMATCH,
                message=f"branch {branch!r} does not match {token.scope_branch!r}",
            )
        if token.scope_commit is not None and commit != token.scope_commit:
            return TokenUseResult(
                granted=False,
                token_id=token_id,
                reason=DenyReason.COMMIT_MISMATCH,
                message=f"commit {commit!r} does not match {token.scope_commit!r}",
            )

        # Gate 4: max_uses — increment under lock for atomicity.
        with self._lock:
            if token.consumed_count >= token.max_uses:
                return TokenUseResult(
                    granted=False,
                    token_id=token_id,
                    reason=DenyReason.EXHAUSTED,
                    message="token has been fully consumed",
                )
            token.consumed_count += 1

        return TokenUseResult(granted=True, token_id=token_id)
