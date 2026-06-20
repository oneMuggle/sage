"""``backend.adapters.out.compute.subprocess_adapter`` 单测。

覆盖:

- 6 个错误分支:OPERATION_NOT_FOUND / INVALID_PARAMS / TIMEOUT / PROCESS_FAILED
  / OUTPUT_PARSE_ERROR / ExecutableNotFoundError → INTERNAL_ERROR
- 1 个成功路径
- ``list_operations`` 与 yaml 一致
- ``_params_to_args`` 各种类型场景(bool / list / str / int / kebab-case)
- ``_parse_success`` / ``_parse_failure`` 模块级辅助函数

策略:不真打 subprocess,统一 mock ``asyncio.create_subprocess_exec`` 与
``ExecutableResolver.resolve``。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sage_core import (
    ComputeErrorType,
    ComputeRequest,
)

from backend.adapters.out.compute._resolver import (
    ExecutableNotFoundError,
    ResolvedExecutable,
)
from backend.adapters.out.compute.subprocess_adapter import (
    SubprocessComputeAdapter,
    _OperationDef,
    _params_to_args,
    _parse_failure,
    _parse_success,
)

# ---------- 通用 fixtures ----------


def _make_config(**overrides: Any) -> dict[str, Any]:
    """生成默认 yaml-like config(可单测精细覆盖)。"""
    cfg: dict[str, Any] = {
        "enabled": True,
        "timeout_seconds": 10,
        "adapter": "subprocess",
        "subprocess": {
            "python_module": {
                "python": "/usr/bin/python3",
                "module": "ghm",
            },
        },
        "operations": [
            {
                "name": "compute_shock",
                "cli_subcommand": ["core", "shock"],
                "description": "正激波计算",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        "mach": {"type": "number"},
                        "gamma": {"type": "number"},
                        "p1": {"type": "number"},
                        "t1": {"type": "number"},
                    },
                },
            }
        ],
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture()
def resolved_dummy() -> ResolvedExecutable:
    return ResolvedExecutable(
        argv_prefix=["/usr/bin/python3", "-m", "ghm"],
        working_dir="/some/dir",
        source="python_module",
    )


def _make_mock_proc(
    stdout: bytes = b"",
    stderr: bytes = b"",
    return_code: int = 0,
    timeout: bool = False,
) -> MagicMock:
    """生成模拟的 asyncio subprocess。"""
    proc = MagicMock()
    if timeout:
        # 在 communicate 时永久挂起(由 wait_for timeout 触发)
        async def hang() -> tuple[bytes, bytes]:
            await asyncio.sleep(100)
            return (b"", b"")

        proc.communicate = AsyncMock(side_effect=hang)
    else:
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = return_code
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=None)
    return proc


# ---------- list_operations ----------


def test_list_operations_reflects_yaml() -> None:
    """list_operations 应返回 yaml 中声明的全部 spec。"""
    cfg = _make_config()
    cfg["operations"].append(
        {
            "name": "compute_equilibrium",
            "cli_subcommand": ["core", "equilibrium"],
            "description": "平衡气体",
            "params_schema": {"type": "object"},
        }
    )
    adapter = SubprocessComputeAdapter(cfg)

    specs = adapter.list_operations()

    assert [s.name for s in specs] == ["compute_shock", "compute_equilibrium"]
    assert specs[0].description == "正激波计算"
    assert "properties" in specs[0].params_schema


# ---------- 成功路径 ----------


@pytest.mark.asyncio()
async def test_execute_success(resolved_dummy: ResolvedExecutable) -> None:
    """正常执行 → success=True,output 解析自 stdout JSON。"""
    cfg = _make_config()
    adapter = SubprocessComputeAdapter(cfg)

    mock_proc = _make_mock_proc(
        stdout=b'{"p2": 51000, "t2": 1456.8, "m2": 0.4}',
        return_code=0,
    )

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        req = ComputeRequest(
            operation="compute_shock",
            params={"mach": 6.5, "gamma": 1.4, "p1": 1000, "t1": 250},
        )

        result = await adapter.execute(req)

    assert result.success is True
    assert result.output == {"p2": 51000, "t2": 1456.8, "m2": 0.4}
    assert result.exit_code == 0
    assert result.error is None
    assert result.duration_ms is not None
    assert result.duration_ms >= 0


# ---------- 错误:OPERATION_NOT_FOUND ----------


@pytest.mark.asyncio()
async def test_execute_unknown_operation() -> None:
    """未声明的 operation → OPERATION_NOT_FOUND,不会 spawn 进程。"""
    adapter = SubprocessComputeAdapter(_make_config())
    req = ComputeRequest(operation="not_declared", params={})

    result = await adapter.execute(req)

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.OPERATION_NOT_FOUND
    assert "not_declared" in result.error.message


# ---------- 错误:ExecutableNotFoundError → INTERNAL_ERROR ----------


@pytest.mark.asyncio()
async def test_execute_resolver_failure() -> None:
    """ExecutableResolver 抛错 → INTERNAL_ERROR,details.tried 包含尝试。"""
    adapter = SubprocessComputeAdapter(_make_config())

    with patch.object(adapter, "_resolver") as mock_resolver:
        mock_resolver.resolve.side_effect = ExecutableNotFoundError(
            ["executable_path=/none", "python_module=...", "shutil.which=ghm-cli"]
        )
        req = ComputeRequest(operation="compute_shock", params={"mach": 6.5})

        result = await adapter.execute(req)

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.INTERNAL_ERROR
    assert "tried" in result.error.details
    assert len(result.error.details["tried"]) == 3


# ---------- 错误:TIMEOUT ----------


@pytest.mark.asyncio()
async def test_execute_timeout(resolved_dummy: ResolvedExecutable) -> None:
    """超时 → TIMEOUT 且 proc.kill() / wait() 被调用。"""
    cfg = _make_config(timeout_seconds=1)
    adapter = SubprocessComputeAdapter(cfg)

    mock_proc = _make_mock_proc(timeout=True)

    async def short_timeout(_coro: Any, timeout: float) -> Any:
        raise TimeoutError()

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.wait_for",
            new=short_timeout,
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy

        result = await adapter.execute(
            ComputeRequest(operation="compute_shock", params={"mach": 6.5})
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.TIMEOUT
    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_awaited_once()


@pytest.mark.asyncio()
async def test_execute_per_request_timeout_overrides(
    resolved_dummy: ResolvedExecutable,
) -> None:
    """ComputeRequest.timeout_ms 优先于 yaml.timeout_seconds。"""
    adapter = SubprocessComputeAdapter(_make_config(timeout_seconds=100))

    captured_timeouts: list[float] = []

    async def capturing_wait_for(coro: Any, timeout: float) -> tuple[bytes, bytes]:
        captured_timeouts.append(timeout)
        return await coro

    mock_proc = _make_mock_proc(stdout=b"{}", return_code=0)

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.wait_for",
            new=capturing_wait_for,
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        await adapter.execute(
            ComputeRequest(
                operation="compute_shock",
                params={"mach": 6.5},
                timeout_ms=5000,
            )
        )

    assert captured_timeouts == [5.0]  # 5000ms → 5s


# ---------- 错误:PROCESS_FAILED (exit_code != 0,!= 2) ----------


@pytest.mark.asyncio()
async def test_execute_process_failed(resolved_dummy: ResolvedExecutable) -> None:
    """退出码 1 → PROCESS_FAILED,error.message 来自 stderr。"""
    adapter = SubprocessComputeAdapter(_make_config())

    mock_proc = _make_mock_proc(
        stdout=b"",
        stderr=b"computation diverged",
        return_code=1,
    )

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        result = await adapter.execute(
            ComputeRequest(operation="compute_shock", params={"mach": 6.5})
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.PROCESS_FAILED
    assert "computation diverged" in result.error.message
    assert result.exit_code == 1


# ---------- 错误:INVALID_PARAMS (exit_code == 2) ----------


@pytest.mark.asyncio()
async def test_execute_invalid_params(resolved_dummy: ResolvedExecutable) -> None:
    """退出码 2 → INVALID_PARAMS(argparse 错误)。"""
    adapter = SubprocessComputeAdapter(_make_config())

    mock_proc = _make_mock_proc(
        stderr=b"error: argument --mach is required",
        return_code=2,
    )

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        result = await adapter.execute(
            ComputeRequest(operation="compute_shock", params={"mach": 6.5})
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.INVALID_PARAMS


# ---------- 错误:OUTPUT_PARSE_ERROR ----------


@pytest.mark.asyncio()
async def test_execute_output_parse_error(resolved_dummy: ResolvedExecutable) -> None:
    """exit_code=0 但 stdout 非 JSON → OUTPUT_PARSE_ERROR。"""
    adapter = SubprocessComputeAdapter(_make_config())

    mock_proc = _make_mock_proc(
        stdout=b"not valid json {{{",
        return_code=0,
    )

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        result = await adapter.execute(
            ComputeRequest(operation="compute_shock", params={"mach": 6.5})
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.OUTPUT_PARSE_ERROR
    assert result.raw_stdout == "not valid json {{{"


@pytest.mark.asyncio()
async def test_execute_output_not_object(resolved_dummy: ResolvedExecutable) -> None:
    """exit_code=0 但 stdout 是 JSON 数组(非 dict)→ OUTPUT_PARSE_ERROR。"""
    adapter = SubprocessComputeAdapter(_make_config())

    mock_proc = _make_mock_proc(stdout=b"[1, 2, 3]", return_code=0)

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        result = await adapter.execute(
            ComputeRequest(operation="compute_shock", params={"mach": 6.5})
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.OUTPUT_PARSE_ERROR


# ---------- 异常包裹:意外异常 → INTERNAL_ERROR ----------


@pytest.mark.asyncio()
async def test_execute_unexpected_exception_swallowed(
    resolved_dummy: ResolvedExecutable,
) -> None:
    """spawn 子进程时抛非预期异常 → 收敛为 INTERNAL_ERROR,不冒泡。"""
    adapter = SubprocessComputeAdapter(_make_config())

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=OSError("permission denied")),
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        result = await adapter.execute(
            ComputeRequest(operation="compute_shock", params={"mach": 6.5})
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.type == ComputeErrorType.INTERNAL_ERROR
    assert "OSError" in result.error.message


# ---------- argv 拼装 ----------


@pytest.mark.asyncio()
async def test_argv_includes_subcommand_and_flags(
    resolved_dummy: ResolvedExecutable,
) -> None:
    """spawn argv 应包含:resolver 前缀 + subcommand + flags + --json。"""
    adapter = SubprocessComputeAdapter(_make_config())

    captured_argv: list[str] = []
    mock_proc = _make_mock_proc(stdout=b"{}", return_code=0)

    async def capture_exec(*argv: str, **_kwargs: Any) -> Any:
        captured_argv.extend(argv)
        return mock_proc

    with (
        patch.object(adapter, "_resolver") as mock_resolver,
        patch(
            "backend.adapters.out.compute.subprocess_adapter.asyncio.create_subprocess_exec",
            new=capture_exec,
        ),
    ):
        mock_resolver.resolve.return_value = resolved_dummy
        await adapter.execute(
            ComputeRequest(
                operation="compute_shock",
                params={"mach": 6.5, "gamma": 1.4, "p1": 1000, "t1": 250},
            )
        )

    assert captured_argv[:3] == ["/usr/bin/python3", "-m", "ghm"]
    assert "core" in captured_argv
    assert "shock" in captured_argv
    assert "--mach" in captured_argv
    assert "6.5" in captured_argv
    assert captured_argv[-1] == "--json"


# ---------- _params_to_args 单元 ----------


def test_params_to_args_basic() -> None:
    """普通数值与字符串字段。"""
    schema = {"properties": {"mach": {"type": "number"}, "name": {"type": "string"}}}
    result = _params_to_args({"mach": 6.5, "name": "test"}, schema)

    # 顺序无所谓,但 (flag, value) 必须成对
    assert "--mach" in result
    assert "6.5" in result
    assert "--name" in result
    assert "test" in result


def test_params_to_args_kebab_case() -> None:
    """snake_case → kebab-case 转换。"""
    schema = {"properties": {"area_ratio": {"type": "number"}}}
    result = _params_to_args({"area_ratio": 2.5}, schema)

    assert "--area-ratio" in result
    assert "2.5" in result


def test_params_to_args_boolean_true() -> None:
    """boolean True → 仅 flag,无 value。"""
    schema = {"properties": {"verbose": {"type": "boolean"}}}
    result = _params_to_args({"verbose": True}, schema)

    assert result == ["--verbose"]


def test_params_to_args_boolean_false_skipped() -> None:
    """boolean False → 跳过。"""
    schema = {"properties": {"verbose": {"type": "boolean"}}}
    result = _params_to_args({"verbose": False}, schema)

    assert result == []


def test_params_to_args_list_expansion() -> None:
    """list/tuple → flag 后跟多个 value。"""
    schema = {"properties": {"config": {"type": "array"}}}
    result = _params_to_args({"config": ["k1=v1", "k2=v2"]}, schema)

    assert result == ["--config", "k1=v1", "k2=v2"]


def test_params_to_args_empty_list_skipped() -> None:
    """空列表 → 跳过。"""
    schema = {"properties": {"items": {"type": "array"}}}
    result = _params_to_args({"items": []}, schema)

    assert result == []


def test_params_to_args_no_schema_fallback() -> None:
    """schema 缺失/不规范时,仍能按字符串拼。"""
    result = _params_to_args({"x": 1}, {})

    assert result == ["--x", "1"]


# ---------- _parse_success / _parse_failure 单元 ----------


def test_parse_success_empty_stdout() -> None:
    """空 stdout → output={} 不报错。"""
    result = _parse_success("", "", 100)

    assert result.success is True
    assert result.output == {}


def test_parse_failure_exit_2_is_invalid_params() -> None:
    result = _parse_failure(2, "", "argparse error", 100)

    assert result.error is not None
    assert result.error.type == ComputeErrorType.INVALID_PARAMS


def test_parse_failure_exit_1_is_process_failed() -> None:
    result = _parse_failure(1, "", "err", 100)

    assert result.error is not None
    assert result.error.type == ComputeErrorType.PROCESS_FAILED


def test_parse_failure_message_fallback() -> None:
    """stderr 与 stdout 都为空 → 错误消息走 'exit code N' 回退。"""
    result = _parse_failure(1, "", "", 100)

    assert result.error is not None
    assert "exit code 1" in result.error.message


# ---------- _OperationDef ----------


def test_operation_def_construction() -> None:
    op = _OperationDef(
        name="x",
        cli_subcommand=["core", "x"],
        description="d",
        params_schema={"type": "object"},
    )

    assert op.name == "x"
    assert op.cli_subcommand == ["core", "x"]
