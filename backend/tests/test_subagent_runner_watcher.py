"""Test SubagentRunner watcher lifecycle hardening.

Verifies that the interrupt watcher task is properly cleaned up:
- CancelledError is caught inside _watch() to prevent leakage
- finally block awaits watcher.cancel() to prevent task leaks
- Watcher cleanup works correctly on both normal completion and exception paths
"""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from backend.orchestration.subagent_runner import SubagentRunner


@pytest.fixture()
def mock_agent():
    """Create a mock SageAgent."""
    agent = Mock()
    agent.interrupt = Mock()
    agent.run_loop = AsyncMock(return_value=iter([]))
    return agent


@pytest.fixture()
def mock_task():
    """Create a mock orchestration task."""
    task = Mock()
    task.parameters = {
        "goal": "Test goal",
        "scratch_dir": "/tmp/test",
    }
    return task


@pytest.mark.asyncio()
async def test_watcher_cleanup_on_normal_completion():
    """Test that watcher is properly cleaned up when run_loop completes normally."""
    interrupt_event = asyncio.Event()
    runner = SubagentRunner(interrupt_event=interrupt_event)

    # Mock the agent and run_loop
    with patch("backend.orchestration.subagent_runner.SageAgent") as MockAgent, \
         patch("backend.orchestration.subagent_runner.get_enabled_agent", return_value={"system_prompt": "test"}), \
         patch("backend.orchestration.subagent_runner.build_system_base", return_value=""):

        mock_child = Mock()
        mock_child.interrupt = Mock()

        # Create an async generator that yields a done event
        async def mock_run_loop(*args, **kwargs):
            event = Mock()
            event.state = Mock()
            event.state.value = "done"
            event.content = "Test output"
            yield event

        mock_child.run_loop = mock_run_loop
        MockAgent.return_value = mock_child

        task = Mock()
        task.parameters = {"goal": "Test", "scratch_dir": "/tmp/test"}

        # Run the task - should complete without hanging
        result = await runner(task, "test-agent")

        assert result["status"] == "succeeded"
        # Watcher should have been cancelled (we can't directly verify this,
        # but the fact that we completed without hanging is the key assertion)


@pytest.mark.asyncio()
async def test_watcher_cleanup_on_exception():
    """Test that watcher is cleaned up even when run_loop raises an exception."""
    interrupt_event = asyncio.Event()
    runner = SubagentRunner(interrupt_event=interrupt_event)

    with patch("backend.orchestration.subagent_runner.SageAgent") as MockAgent, \
         patch("backend.orchestration.subagent_runner.get_enabled_agent", return_value={"system_prompt": "test"}), \
         patch("backend.orchestration.subagent_runner.build_system_base", return_value=""):

        mock_child = Mock()
        mock_child.interrupt = Mock()

        # Create an async generator that raises an exception
        async def mock_run_loop(*args, **kwargs):
            raise RuntimeError("Simulated error")
            yield  # Make it a generator  # noqa: E501

        mock_child.run_loop = mock_run_loop
        MockAgent.return_value = mock_child

        task = Mock()
        task.parameters = {"goal": "Test", "scratch_dir": "/tmp/test"}

        # Should raise the exception, not hang
        with pytest.raises(RuntimeError, match="Simulated error"):
            await runner(task, "test-agent")

        # Watcher cleanup happened in finally block (key assertion: no hang)


@pytest.mark.asyncio()
async def test_watcher_cancelled_error_handling():
    """Test that watcher cleanup works when interrupt is triggered."""
    interrupt_event = asyncio.Event()
    runner = SubagentRunner(interrupt_event=interrupt_event)

    with patch("backend.orchestration.subagent_runner.SageAgent") as MockAgent, \
         patch("backend.orchestration.subagent_runner.get_enabled_agent", return_value={"system_prompt": "test"}), \
         patch("backend.orchestration.subagent_runner.build_system_base", return_value=""):

        mock_child = Mock()

        # Track if interrupt was called
        interrupt_called = False

        def track_interrupt():
            nonlocal interrupt_called
            interrupt_called = True

        mock_child.interrupt = track_interrupt

        # Create an async generator that yields a done event quickly
        async def mock_run_loop(*args, **kwargs):
            # Give watcher a chance to fire
            await asyncio.sleep(0.01)
            event = Mock()
            event.state = Mock()
            event.state.value = "done"
            event.content = "Test output"
            yield event

        mock_child.run_loop = mock_run_loop
        MockAgent.return_value = mock_child

        task = Mock()
        task.parameters = {"goal": "Test", "scratch_dir": "/tmp/test"}

        # Set interrupt event before running
        interrupt_event.set()

        # Run the task - watcher should fire and interrupt should be called
        result = await runner(task, "test-agent")

        # Verify interrupt was called (watcher fired successfully)
        assert interrupt_called
        assert result["status"] == "succeeded"


@pytest.mark.asyncio()
async def test_watcher_no_interrupt_event():
    """Test that runner works correctly when no interrupt_event is provided."""
    runner = SubagentRunner(interrupt_event=None)

    with patch("backend.orchestration.subagent_runner.SageAgent") as MockAgent, \
         patch("backend.orchestration.subagent_runner.get_enabled_agent", return_value={"system_prompt": "test"}), \
         patch("backend.orchestration.subagent_runner.build_system_base", return_value=""):

        mock_child = Mock()
        mock_child.interrupt = Mock()

        # Create an async generator that yields a done event
        async def mock_run_loop(*args, **kwargs):
            event = Mock()
            event.state = Mock()
            event.state.value = "done"
            event.content = "Test output"
            yield event

        mock_child.run_loop = mock_run_loop
        MockAgent.return_value = mock_child

        task = Mock()
        task.parameters = {"goal": "Test", "scratch_dir": "/tmp/test"}

        # Should complete without creating a watcher
        result = await runner(task, "test-agent")

        assert result["status"] == "succeeded"


@pytest.mark.asyncio()
async def test_watcher_cleanup_on_multiple_exceptions():
    """Test watcher cleanup when multiple exceptions occur in sequence."""
    interrupt_event = asyncio.Event()
    runner = SubagentRunner(interrupt_event=interrupt_event)

    with patch("backend.orchestration.subagent_runner.SageAgent") as MockAgent, \
         patch("backend.orchestration.subagent_runner.get_enabled_agent", return_value={"system_prompt": "test"}), \
         patch("backend.orchestration.subagent_runner.build_system_base", return_value=""):

        mock_child = Mock()
        mock_child.interrupt = Mock()

        # First call: raise ValueError
        async def mock_run_loop_1(*args, **kwargs):
            raise ValueError("First error")
            yield  # Make it a generator  # noqa: E501

        mock_child.run_loop = mock_run_loop_1
        MockAgent.return_value = mock_child

        task = Mock()
        task.parameters = {"goal": "Test", "scratch_dir": "/tmp/test"}

        # First run should fail but clean up watcher
        with pytest.raises(ValueError, match="First error"):
            await runner(task, "test-agent")

        # Second call: raise RuntimeError
        async def mock_run_loop_2(*args, **kwargs):
            raise RuntimeError("Second error")
            yield  # Make it a generator  # noqa: E501

        mock_child.run_loop = mock_run_loop_2

        # Second run should also fail and clean up watcher
        with pytest.raises(RuntimeError, match="Second error"):
            await runner(task, "test-agent")

        # Both runs completed without hanging (watcher cleanup worked)
