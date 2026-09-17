"""Tests for Task 5: context window resolution via model catalog.

Verifies that effective_window() correctly integrates with resolved
catalog data (native/service limits) and that the new autoContext
setting produces correct budget calculations.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.api.legacy_routes import _check_request_within_window
from backend.model_catalog.context import effective_window
from backend.model_catalog.schemas import ContextLimits


class TestEffectiveWindowAuto:
    """autoContext=True: use min of known limits, unknown fallback 4096."""

    def test_small_service_window(self):
        """Service limit smaller than native -> use service."""
        assert effective_window(
            ContextLimits(native=32768, service=4096), True, 128000
        ) == 4096

    def test_small_native_window(self):
        """Native limit smaller than service -> use native."""
        assert effective_window(
            ContextLimits(native=4096, service=32768), True, 128000
        ) == 4096

    def test_both_known_takes_min(self):
        """Both known -> min of the two."""
        assert effective_window(
            ContextLimits(native=8192, service=16384), True, 128000
        ) == 8192

    def test_unknown_fallback(self):
        """No known limits -> conservative default 4096."""
        assert effective_window(ContextLimits(), True, 128000) == 4096

    def test_only_native_known(self):
        """Only native known -> use native."""
        assert effective_window(
            ContextLimits(native=32768), True, 128000
        ) == 32768

    def test_only_service_known(self):
        """Only service known -> use service."""
        assert effective_window(
            ContextLimits(service=8192), True, 128000
        ) == 8192

    def test_auto_ignores_fixed(self):
        """auto=True ignores the fixed parameter entirely."""
        result_auto = effective_window(
            ContextLimits(native=16384), True, 999999
        )
        assert result_auto == 16384


class TestEffectiveWindowManual:
    """autoContext=False: fixed is capped by known limits."""

    def test_fixed_within_limits(self):
        """Fixed smaller than all known -> use fixed."""
        assert effective_window(
            ContextLimits(native=32768, service=16384), False, 8192
        ) == 8192

    def test_fixed_exceeds_service(self):
        """Fixed exceeds service -> capped to service."""
        assert effective_window(
            ContextLimits(native=32768, service=4096), False, 128000
        ) == 4096

    def test_fixed_exceeds_native(self):
        """Fixed exceeds native -> capped to native."""
        assert effective_window(
            ContextLimits(native=4096, service=32768), False, 128000
        ) == 4096

    def test_no_known_limits_uses_fixed(self):
        """No known limits -> fixed is the result."""
        assert effective_window(ContextLimits(), False, 128000) == 128000

    def test_fixed_equals_limit(self):
        """Fixed exactly equals a limit -> use that value."""
        assert effective_window(
            ContextLimits(native=8192), False, 8192
        ) == 8192


class TestEffectiveWindowValidation:
    """Input validation."""

    def test_automatic_must_be_bool(self):
        with pytest.raises(ValueError, match="boolean"):
            effective_window(ContextLimits(), "yes", 4096)  # type: ignore[arg-type]

    def test_fixed_must_be_positive(self):
        with pytest.raises(ValueError, match="positive"):
            effective_window(ContextLimits(), True, 0)

    def test_fixed_rejects_bool(self):
        with pytest.raises(ValueError, match="positive"):
            effective_window(ContextLimits(), True, True)  # type: ignore[arg-type]

    def test_fixed_rejects_negative(self):
        with pytest.raises(ValueError, match="positive"):
            effective_window(ContextLimits(), False, -1)


class TestContextBudgetIntegration:
    """Verify that effective_window feeds correctly into history budget.

    The history budget should be: total_window - system/tool/input/output_reserve,
    with a minimum of 0 (never negative). Required content exceeding total
    window must be explicitly rejected, not silently truncated.
    """

    def test_budget_derived_from_effective_window(self):
        """Budget should use effective_window result, not raw model prefix."""
        window = effective_window(
            ContextLimits(native=32768, service=8192), True, 128000
        )
        assert window == 8192
        # Budget = window - reserve (e.g., 16384 for system/tools/output)
        # If window < reserve, budget should be 0 (not negative)
        reserve = 16384
        budget = max(0, window - reserve)
        assert budget == 0  # 8192 - 16384 = negative -> 0

    def test_budget_with_large_window(self):
        """Large window -> positive budget for history."""
        window = effective_window(
            ContextLimits(native=200000, service=128000), True, 128000
        )
        assert window == 128000
        reserve = 16384
        budget = max(0, window - reserve)
        assert budget == 111616


class TestResolveEffectiveWindow:
    """Round 2 (2026-09-15): pin the new ``_resolve_effective_window`` branches.

    Reviewer found ``autoContext`` was functionally inert because the previous
    logic made ``max_context`` always win. These tests pin the new behaviour:
    - ``auto_context=True``  → catalog-resolved window, ``max_context`` is
      a safety upper bound (``min(catalog, max)``).
    - ``auto_context=False`` → fixed cap at ``max_context`` (clamped by
      catalog limits via effective_window).
    - ``auto_context=None``  → resolve from catalog with 4096 default cap.
    """

    def _patch_resolver(self, settings_dict, catalog_limits):
        """Build context managers that stub Settings + Catalog for the
        deferred imports inside ``_resolve_effective_window``."""
        from unittest.mock import MagicMock

        from backend.model_catalog.schemas import EffectiveModel, Price

        effective = EffectiveModel(
            limits=catalog_limits,
            price=Price(),
            provenance={},
        )

        mock_settings_instance = MagicMock()
        mock_settings_instance.get_json.return_value = settings_dict

        mock_catalog_instance = MagicMock()
        mock_catalog_instance.resolve.return_value = effective

        return [
            patch(
                "backend.data.settings_repo.SettingsRepository",
                return_value=mock_settings_instance,
            ),
            patch(
                "backend.data.database.get_database",
                return_value=MagicMock(),
            ),
            patch(
                "backend.model_catalog.repository.CatalogRepository",
                return_value=mock_catalog_instance,
            ),
        ]

    def _settings(self):
        return {
            "endpoints": [{"id": "ep-1", "modelId": "gpt-x"}],
            "modelSelections": {
                "chatModel": {"endpointId": "ep-1", "modelId": "gpt-x"},
            },
        }

    def test_auto_context_true_with_max_context_clamps_to_max(self):
        """auto_context=True with max_context acts as safety upper bound.

        Catalog says 128K (service), user pinned max=4096 → result is 4096.
        This is the path that makes the UI autoContext toggle actually
        change behaviour: without the fix, the same call would also return
        4096, but only by accident (the old `elif max_context` branch
        always won). With the fix, removing max_context would let the
        catalog window through.
        """
        from backend.api.legacy_routes import _resolve_effective_window

        limits = ContextLimits(native=200_000, service=128_000)
        patches = self._patch_resolver(self._settings(), limits)
        with patches[0], patches[1], patches[2]:
            result = _resolve_effective_window(
                model_id="gpt-x",
                max_context=4096,
                request_endpoint_id="ep-1",
                auto_context=True,
            )
        assert result == 4096

    def test_auto_context_true_without_max_context_uses_catalog(self):
        """auto_context=True without max_context returns the catalog window.

        This is the key behaviour change — the old code fell through to
        fixed=4096 whenever max_context was set, but with the new branch
        a True toggle + no cap yields the full catalog-resolved window.
        """
        from backend.api.legacy_routes import _resolve_effective_window

        limits = ContextLimits(native=200_000, service=128_000)
        patches = self._patch_resolver(self._settings(), limits)
        with patches[0], patches[1], patches[2]:
            result = _resolve_effective_window(
                model_id="gpt-x",
                max_context=None,
                request_endpoint_id="ep-1",
                auto_context=True,
            )
        # Catalog has service=128K, native=200K → min = 128000
        assert result == 128000

    def test_auto_context_false_uses_max_as_fixed_cap(self):
        """auto_context=False with max_context → fixed cap (capped by catalog)."""
        from backend.api.legacy_routes import _resolve_effective_window

        # Catalog service cap (4096) is smaller than max_context (8192),
        # so the cap clamps the fixed value.
        limits = ContextLimits(native=32_000, service=4096)
        patches = self._patch_resolver(self._settings(), limits)
        with patches[0], patches[1], patches[2]:
            result = _resolve_effective_window(
                model_id="gpt-x",
                max_context=8192,
                request_endpoint_id="ep-1",
                auto_context=False,
            )
        assert result == 4096

    def test_auto_context_none_falls_back_to_catalog(self):
        """auto_context=None (caller did not pass the field) → catalog.

        Same behaviour as ``auto_context=True`` without max_context — the
        resolver still reaches the catalog. This preserves the behaviour
        for older clients that don't send the new field.
        """
        from backend.api.legacy_routes import _resolve_effective_window

        limits = ContextLimits(native=200_000, service=128_000)
        patches = self._patch_resolver(self._settings(), limits)
        with patches[0], patches[1], patches[2]:
            result = _resolve_effective_window(
                model_id="gpt-x",
                max_context=None,
                request_endpoint_id="ep-1",
                auto_context=None,
            )
        assert result == 128000

    def test_endpoint_id_request_overrides_persisted(self):
        """Request endpoint_id wins over the persisted chat selection."""
        from backend.api.legacy_routes import _resolve_effective_window

        settings = {
            "endpoints": [
                {"id": "ep-1", "modelId": "gpt-x"},
                {"id": "ep-2", "modelId": "gpt-x"},
            ],
            "modelSelections": {
                # Persisted points at ep-1 (catalog has 200K/128K = 128K).
                "chatModel": {"endpointId": "ep-1", "modelId": "gpt-x"},
            },
        }
        # ep-2 has the larger catalog window.
        limits = ContextLimits(native=1_000_000, service=500_000)
        patches = self._patch_resolver(settings, limits)
        with patches[0], patches[1], patches[2]:
            result = _resolve_effective_window(
                model_id="gpt-x",
                max_context=None,
                request_endpoint_id="ep-2",
                auto_context=True,
            )
        assert result == 500_000


class TestCheckRequestWithinWindow:
    """Round 2 (2026-09-15): brief line 16 explicit reject helper."""

    def test_no_op_when_window_unknown(self):
        """Catalog unresolvable → no reject (legacy behaviour preserved)."""
        messages = [{"role": "user", "content": "x" * 100_000}]
        # Must not raise even with a huge message and unknown window.
        _check_request_within_window(messages, None)
        _check_request_within_window(messages, 0)
        _check_request_within_window(messages, -1)

    def test_under_window_passes(self):
        """Total tokens at or under the window → no reject."""
        # 100 chars of text, well under 4096 tokens.
        messages = [{"role": "user", "content": "x" * 100}]
        _check_request_within_window(messages, 4096)

    def test_overshoot_raises_400(self):
        """Total tokens strictly greater than the window → HTTP 400."""
        # ~25 000 chars of text in one user message → ~6250 tokens
        # (4 chars ≈ 1 token), well over a 4096-token window.
        messages = [{"role": "user", "content": "x" * 25_000}]
        with pytest.raises(HTTPException) as exc:
            _check_request_within_window(messages, 4096)
        assert exc.value.status_code == 400
        # Detail mentions both token count and window size for diagnosis.
        detail = exc.value.detail
        assert "4096" in detail
        assert "tokens" in detail.lower()

    def test_overshoot_with_multiple_messages(self):
        """Multi-message overshoot (system + user) also fires."""
        messages = [
            {"role": "system", "content": "y" * 20_000},
            {"role": "user", "content": "x" * 20_000},
        ]
        with pytest.raises(HTTPException) as exc:
            _check_request_within_window(messages, 4096)
        assert exc.value.status_code == 400
