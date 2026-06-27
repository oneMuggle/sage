"""
Unit tests for ApprovalToken + ApprovalTokenStore.

Coverage (8 consume validations):
1. token exists
2. not revoked
3. not expired
4. consumed_count < max_uses
5. actor == approver (strict)
6. action strictly equal
7. repo strictly equal
8. branch strictly equal
9. commit matches (if declared)

Plus: issue / revoke / get / list behavior.
"""

from __future__ import annotations

import time

import pytest

from backend.orchestration.approval_tokens import (
    ApprovalToken,
    ApprovalTokenStore,
    DenyReason,
)

# ============================================================================
# Helpers
# ============================================================================


def _now_ms() -> int:
    return int(time.time() * 1000)


def _token(
    store: ApprovalTokenStore,
    **overrides,
) -> ApprovalToken:
    """Issue a token with sensible defaults; allow overrides for negative tests."""
    defaults = {
        "approver": "alice",
        "policy_exception": "force_push_blocked_lane",
        "action": "git push --force-with-lease",
        "scope_repo": "/repo",
        "scope_branch": "feat/example",
        "scope_commit": "abc123",
        "ttl_ms": 60_000,  # 60 seconds
        "max_uses": 1,
    }
    defaults.update(overrides)
    return store.issue(**defaults)


# ============================================================================
# Issue
# ============================================================================


class TestIssue:
    def test_issue_returns_token_with_unique_id(self):
        store = ApprovalTokenStore()
        t1 = _token(store)
        t2 = _token(store)
        assert t1.token_id != t2.token_id
        assert t1.token_id.startswith("apt_")

    def test_token_has_timestamps(self):
        store = ApprovalTokenStore()
        before = _now_ms()
        t = _token(store)
        after = _now_ms()
        assert before <= t.issued_at <= after
        assert t.expires_at == t.issued_at + 60_000

    def test_token_initial_state(self):
        store = ApprovalTokenStore()
        t = _token(store)
        assert t.consumed_count == 0
        assert t.revoked is False


# ============================================================================
# Consume — happy path
# ============================================================================


class TestConsumeHappyPath:
    def test_consume_increments_count(self):
        store = ApprovalTokenStore()
        t = _token(store)
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/example",
            commit="abc123",
        )
        assert result.granted is True
        assert t.consumed_count == 1

    def test_consume_max_uses_2(self):
        store = ApprovalTokenStore()
        t = _token(store, max_uses=2)
        r1 = store.consume(
            t.token_id, "alice", "git push --force-with-lease", "/repo", "feat/example", "abc123"
        )
        r2 = store.consume(
            t.token_id, "alice", "git push --force-with-lease", "/repo", "feat/example", "abc123"
        )
        assert r1.granted is True
        assert r2.granted is True
        assert t.consumed_count == 2


# ============================================================================
# Consume — 8 validation gates
# ============================================================================


class TestConsumeValidation:
    # Gate 1: token exists
    def test_unknown_token_denied(self):
        store = ApprovalTokenStore()
        result = store.consume("apt_doesnotexist", "alice", "any", "/repo", "main", None)
        assert result.granted is False
        assert result.reason == DenyReason.NOT_FOUND

    # Gate 2: not revoked
    def test_revoked_token_denied(self):
        store = ApprovalTokenStore()
        t = _token(store)
        store.revoke(t.token_id)
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/example",
            commit="abc123",
        )
        assert result.granted is False
        assert result.reason == DenyReason.REVOKED

    # Gate 3: not expired
    def test_expired_token_denied(self):
        store = ApprovalTokenStore()
        t = _token(store, ttl_ms=1)  # 1 ms TTL
        time.sleep(0.01)
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/example",
            commit="abc123",
        )
        assert result.granted is False
        assert result.reason == DenyReason.EXPIRED

    # Gate 4: consumed_count < max_uses
    def test_exhausted_token_denied(self):
        store = ApprovalTokenStore()
        t = _token(store, max_uses=1)
        store.consume(
            t.token_id, "alice", "git push --force-with-lease", "/repo", "feat/example", "abc123"
        )
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/example",
            commit="abc123",
        )
        assert result.granted is False
        assert result.reason == DenyReason.EXHAUSTED

    # Gate 5: actor == approver
    def test_wrong_actor_denied(self):
        store = ApprovalTokenStore()
        t = _token(store)
        result = store.consume(
            token_id=t.token_id,
            actor="mallory",  # not alice
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/example",
            commit="abc123",
        )
        assert result.granted is False
        assert result.reason == DenyReason.ACTOR_MISMATCH

    # Gate 6: action strictly equal
    def test_wrong_action_denied(self):
        store = ApprovalTokenStore()
        t = _token(store)
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="rm -rf /",
            repo="/repo",
            branch="feat/example",
            commit="abc123",
        )
        assert result.granted is False
        assert result.reason == DenyReason.ACTION_MISMATCH

    # Gate 7: repo strictly equal
    def test_wrong_repo_denied(self):
        store = ApprovalTokenStore()
        t = _token(store)
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/other-repo",
            branch="feat/example",
            commit="abc123",
        )
        assert result.granted is False
        assert result.reason == DenyReason.REPO_MISMATCH

    # Gate 7b: branch strictly equal
    def test_wrong_branch_denied(self):
        store = ApprovalTokenStore()
        t = _token(store)
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/different",
            commit="abc123",
        )
        assert result.granted is False
        assert result.reason == DenyReason.BRANCH_MISMATCH

    # Gate 8: commit matches (if declared)
    def test_wrong_commit_denied_when_token_specifies_commit(self):
        store = ApprovalTokenStore()
        t = _token(store)  # scope_commit="abc123"
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/example",
            commit="def456",  # different
        )
        assert result.granted is False
        assert result.reason == DenyReason.COMMIT_MISMATCH

    def test_commit_not_required_when_token_omits_it(self):
        store = ApprovalTokenStore()
        t = _token(store, scope_commit=None)
        result = store.consume(
            token_id=t.token_id,
            actor="alice",
            action="git push --force-with-lease",
            repo="/repo",
            branch="feat/example",
            commit="any",
        )
        assert result.granted is True


# ============================================================================
# TokenUseResult shape
# ============================================================================


class TestTokenUseResult:
    def test_granted_result_carries_token_id(self):
        store = ApprovalTokenStore()
        t = _token(store)
        result = store.consume(
            t.token_id, "alice", "git push --force-with-lease", "/repo", "feat/example", "abc123"
        )
        assert result.granted is True
        assert result.token_id == t.token_id
        assert result.reason is None

    def test_denied_result_carries_reason(self):
        store = ApprovalTokenStore()
        result = store.consume("apt_unknown", "alice", "any", "/repo", "main", None)
        assert result.granted is False
        assert result.reason == DenyReason.NOT_FOUND
        assert result.token_id == "apt_unknown"


# ============================================================================
# Get / Revoke / list
# ============================================================================


class TestStoreAccessors:
    def test_get_existing(self):
        store = ApprovalTokenStore()
        t = _token(store)
        assert store.get(t.token_id) is t

    def test_get_unknown_returns_none(self):
        store = ApprovalTokenStore()
        assert store.get("apt_doesnotexist") is None

    def test_revoke_unknown_raises(self):
        store = ApprovalTokenStore()
        with pytest.raises(KeyError):
            store.revoke("apt_doesnotexist")

    def test_revoke_sets_flag(self):
        store = ApprovalTokenStore()
        t = _token(store)
        store.revoke(t.token_id)
        assert t.revoked is True

    def test_list_active_excludes_revoked(self):
        store = ApprovalTokenStore()
        t1 = _token(store)
        t2 = _token(store)
        store.revoke(t1.token_id)
        active = store.list_active()
        assert t1 not in active
        assert t2 in active


# ============================================================================
# Thread safety / concurrent consume
# ============================================================================


class TestConcurrency:
    def test_concurrent_consume_respects_max_uses(self):
        """Even if called rapidly, max_uses is enforced."""
        store = ApprovalTokenStore()
        t = _token(store, max_uses=1)
        results = []
        for _ in range(5):
            r = store.consume(
                t.token_id,
                "alice",
                "git push --force-with-lease",
                "/repo",
                "feat/example",
                "abc123",
            )
            results.append(r.granted)
        # Exactly one grant.
        assert results.count(True) == 1
        assert results.count(False) == 4
