"""Test WakeScheduler resumer timeout."""
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta, timezone

from backend.orchestration.wake_scheduler import WakeScheduler, _WAKE_RESUMER_TIMEOUT_S
from backend.domain.wake import Wake, WakeKind, WakeState, to_utc_iso


@pytest.fixture
def mock_store():
    """Create a mock WakeStore."""
    store = Mock()
    store.get_due_wakes = Mock(return_value=[])
    store.mark_fired = Mock()
    return store


@pytest.fixture
def sample_wake():
    """Create a sample Wake object."""
    return Wake(
        id="wake-001",
        session_id="session-abc",
        kind=WakeKind.TIMER,
        state=WakeState.DUE,  # Ready to be consumed
        fire_at=to_utc_iso(datetime.now(timezone.utc) - timedelta(minutes=1)),
        note="test",
    )


@pytest.mark.asyncio
async def test_wake_scheduler_resumer_timeout(mock_store, sample_wake):
    """Test that slow resumer is terminated after timeout."""
    mock_store.get_due_wakes.return_value = [sample_wake]

    # Create a slow resumer that hangs
    async def slow_resumer(wake):
        await asyncio.sleep(9999)  # Will be interrupted by timeout

    scheduler = WakeScheduler(mock_store, slow_resumer, tick_seconds=15.0)

    # Use a short timeout for testing
    with patch("backend.orchestration.wake_scheduler._WAKE_RESUMER_TIMEOUT_S", 0.1):
        # Should not hang, should complete quickly
        resumed = await scheduler.tick()

        # Timeout should prevent resumer from completing
        assert resumed == 0
        mock_store.mark_fired.assert_called_once_with(sample_wake.id)


@pytest.mark.asyncio
async def test_wake_scheduler_fast_resumer(mock_store, sample_wake):
    """Test that fast resumer completes successfully."""
    mock_store.get_due_wakes.return_value = [sample_wake]

    # Create a fast resumer
    fast_resumer = AsyncMock()

    scheduler = WakeScheduler(mock_store, fast_resumer, tick_seconds=15.0)

    # Should complete well before timeout
    with patch("backend.orchestration.wake_scheduler._WAKE_RESUMER_TIMEOUT_S", 10.0):
        resumed = await scheduler.tick()

        assert resumed == 1
        fast_resumer.assert_called_once_with(sample_wake)
        mock_store.mark_fired.assert_called_once_with(sample_wake.id)


@pytest.mark.asyncio
async def test_wake_scheduler_resumer_exception(mock_store, sample_wake):
    """Test that resumer exception is caught and logged."""
    mock_store.get_due_wakes.return_value = [sample_wake]

    # Create a resumer that raises an exception
    async def failing_resumer(wake):
        raise ValueError("Test error")

    scheduler = WakeScheduler(mock_store, failing_resumer, tick_seconds=15.0)

    # Should not crash, should continue
    with patch("backend.orchestration.wake_scheduler._WAKE_RESUMER_TIMEOUT_S", 10.0):
        resumed = await scheduler.tick()

        # Exception should be caught, not counted as resumed
        assert resumed == 0
        mock_store.mark_fired.assert_called_once_with(sample_wake.id)


def test_wake_scheduler_timeout_default_value():
    """Test that default timeout is 30s."""
    import os
    original = os.environ.get("SAGE_WAKE_RESUMER_TIMEOUT_S")

    try:
        # Remove env var to test default
        if "SAGE_WAKE_RESUMER_TIMEOUT_S" in os.environ:
            del os.environ["SAGE_WAKE_RESUMER_TIMEOUT_S"]

        # Re-import to get fresh value
        import importlib
        import backend.orchestration.wake_scheduler as ws_module
        importlib.reload(ws_module)

        assert ws_module._WAKE_RESUMER_TIMEOUT_S == 30.0
    finally:
        # Restore env var
        if original is not None:
            os.environ["SAGE_WAKE_RESUMER_TIMEOUT_S"] = original


def test_wake_scheduler_timeout_env_override():
    """Test that timeout can be overridden via environment variable."""
    import os
    original = os.environ.get("SAGE_WAKE_RESUMER_TIMEOUT_S")

    try:
        os.environ["SAGE_WAKE_RESUMER_TIMEOUT_S"] = "60"

        # Re-import to get fresh value
        import importlib
        import backend.orchestration.wake_scheduler as ws_module
        importlib.reload(ws_module)

        assert ws_module._WAKE_RESUMER_TIMEOUT_S == 60.0
    finally:
        # Restore env var
        if original is not None:
            os.environ["SAGE_WAKE_RESUMER_TIMEOUT_S"] = original
        elif "SAGE_WAKE_RESUMER_TIMEOUT_S" in os.environ:
            del os.environ["SAGE_WAKE_RESUMER_TIMEOUT_S"]


@pytest.mark.asyncio
async def test_wake_scheduler_multiple_wakes(mock_store, sample_wake):
    """Test that timeout on one wake doesn't block others."""
    wake1 = sample_wake
    wake2 = Wake(
        id="wake-002",
        session_id="session-def",
        kind=WakeKind.TIMER,
        state=WakeState.DUE,
        fire_at=to_utc_iso(datetime.now(timezone.utc) - timedelta(minutes=1)),
        note="test2",
    )
    mock_store.get_due_wakes.return_value = [wake1, wake2]

    # First resumer hangs, second completes
    call_count = 0
    async def mixed_resumer(wake):
        nonlocal call_count
        call_count += 1
        if wake.id == "wake-001":
            await asyncio.sleep(9999)  # Hang
        # wake2 completes immediately

    scheduler = WakeScheduler(mock_store, mixed_resumer, tick_seconds=15.0)

    with patch("backend.orchestration.wake_scheduler._WAKE_RESUMER_TIMEOUT_S", 0.1):
        resumed = await scheduler.tick()

        # wake1 times out (0), wake2 completes (1)
        assert resumed == 1
        assert call_count == 2  # Both wakes were attempted
        assert mock_store.mark_fired.call_count == 2
