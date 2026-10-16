"""Test evolution task wall-clock timeout."""
import asyncio
import pytest
from unittest.mock import Mock, patch

from backend.scheduler.evolution import BaseEvolutionTask, _EVOLUTION_TASK_TIMEOUT_S


class SlowTask(BaseEvolutionTask):
    """Test task that hangs indefinitely."""

    async def run_async(self):
        """Simulate LLM call hang."""
        await asyncio.sleep(9999)  # Will be interrupted by timeout


class FastTask(BaseEvolutionTask):
    """Test task that completes quickly."""

    async def run_async(self):
        """Complete immediately."""
        return {"status": "success", "items_processed": 42}


def test_evolution_task_timeout():
    """Test that evolution task is terminated after timeout."""
    task = SlowTask()

    # Use a short timeout for testing
    with patch("backend.scheduler.evolution._EVOLUTION_TASK_TIMEOUT_S", 0.1):
        with pytest.raises(asyncio.TimeoutError):
            task.run()


def test_evolution_task_completes_before_timeout():
    """Test that fast task completes successfully."""
    task = FastTask()

    # Should complete well before timeout
    with patch("backend.scheduler.evolution._EVOLUTION_TASK_TIMEOUT_S", 10.0):
        result = task.run()
        assert result == {"status": "success", "items_processed": 42}


def test_evolution_task_timeout_default_value():
    """Test that default timeout is 1800s (30 minutes)."""
    # The constant should be set at module import time
    # If env var is not set, it should default to 1800
    import os
    original = os.environ.get("SAGE_EVOLUTION_TASK_TIMEOUT_S")

    try:
        # Remove env var to test default
        if "SAGE_EVOLUTION_TASK_TIMEOUT_S" in os.environ:
            del os.environ["SAGE_EVOLUTION_TASK_TIMEOUT_S"]

        # Re-import to get fresh value
        import importlib
        import backend.scheduler.evolution as evolution_module
        importlib.reload(evolution_module)

        assert evolution_module._EVOLUTION_TASK_TIMEOUT_S == 1800.0
    finally:
        # Restore env var
        if original is not None:
            os.environ["SAGE_EVOLUTION_TASK_TIMEOUT_S"] = original


def test_evolution_task_timeout_env_override():
    """Test that timeout can be overridden via environment variable."""
    import os
    original = os.environ.get("SAGE_EVOLUTION_TASK_TIMEOUT_S")

    try:
        os.environ["SAGE_EVOLUTION_TASK_TIMEOUT_S"] = "600"

        # Re-import to get fresh value
        import importlib
        import backend.scheduler.evolution as evolution_module
        importlib.reload(evolution_module)

        assert evolution_module._EVOLUTION_TASK_TIMEOUT_S == 600.0
    finally:
        # Restore env var
        if original is not None:
            os.environ["SAGE_EVOLUTION_TASK_TIMEOUT_S"] = original
        elif "SAGE_EVOLUTION_TASK_TIMEOUT_S" in os.environ:
            del os.environ["SAGE_EVOLUTION_TASK_TIMEOUT_S"]
