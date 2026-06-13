"""``backend.domain.compute`` 与 ``backend.ports.compute`` 单测。

覆盖：

- ``ComputeSpec`` / ``ComputeRequest`` / ``ComputeResult`` / ``ComputeError``
  dataclass 构造与默认值
- ``ComputeErrorType`` 枚举值正确
- ``ComputePort`` Protocol 的结构性类型校验（``runtime_checkable``）
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.domain.compute import (
    ComputeError,
    ComputeErrorType,
    ComputeRequest,
    ComputeResult,
    ComputeSpec,
)
from backend.ports.compute import ComputePort

# ---------- ComputeSpec ----------


def test_compute_spec_minimal() -> None:
    """ComputeSpec 仅 name + description 必填。"""
    spec = ComputeSpec(name="compute_shock", description="正激波计算")

    assert spec.name == "compute_shock"
    assert spec.description == "正激波计算"
    assert spec.params_schema == {}


def test_compute_spec_with_schema() -> None:
    """ComputeSpec 可携带完整 JSON Schema。"""
    schema = {
        "type": "object",
        "required": ["mach"],
        "properties": {"mach": {"type": "number"}},
    }
    spec = ComputeSpec(
        name="compute_shock",
        description="正激波计算",
        params_schema=schema,
    )

    assert spec.params_schema == schema


# ---------- ComputeRequest ----------


def test_compute_request_defaults() -> None:
    """ComputeRequest 仅 operation 必填，其余有默认值。"""
    req = ComputeRequest(operation="compute_shock")

    assert req.operation == "compute_shock"
    assert req.params == {}
    assert req.timeout_ms is None
    assert req.request_id is None


def test_compute_request_full() -> None:
    """ComputeRequest 携带全部字段。"""
    req = ComputeRequest(
        operation="compute_shock",
        params={"mach": 6.5, "gamma": 1.4},
        timeout_ms=5000,
        request_id="req-abc-123",
    )

    assert req.params == {"mach": 6.5, "gamma": 1.4}
    assert req.timeout_ms == 5000
    assert req.request_id == "req-abc-123"


# ---------- ComputeErrorType ----------


def test_compute_error_type_values() -> None:
    """所有错误分类均为 str 枚举（便于 JSON 序列化）。"""
    assert ComputeErrorType.OPERATION_NOT_FOUND.value == "operation_not_found"
    assert ComputeErrorType.INVALID_PARAMS.value == "invalid_params"
    assert ComputeErrorType.TIMEOUT.value == "timeout"
    assert ComputeErrorType.PROCESS_FAILED.value == "process_failed"
    assert ComputeErrorType.OUTPUT_PARSE_ERROR.value == "output_parse_error"
    assert ComputeErrorType.INTERNAL_ERROR.value == "internal_error"


def test_compute_error_type_is_str_enum() -> None:
    """ComputeErrorType 应继承自 str（支持直接拼接）。"""
    assert isinstance(ComputeErrorType.TIMEOUT, str)
    assert ComputeErrorType.TIMEOUT == "timeout"


# ---------- ComputeError ----------


def test_compute_error_minimal() -> None:
    """ComputeError 仅 type + message 必填。"""
    err = ComputeError(
        type=ComputeErrorType.TIMEOUT,
        message="timeout after 30s",
    )

    assert err.type == ComputeErrorType.TIMEOUT
    assert err.message == "timeout after 30s"
    assert err.details == {}


def test_compute_error_with_details() -> None:
    """ComputeError 可携带 details 上下文（如 tried 列表）。"""
    err = ComputeError(
        type=ComputeErrorType.INTERNAL_ERROR,
        message="executable not found",
        details={"tried": ["python_module", "path_lookup"]},
    )

    assert err.details["tried"] == ["python_module", "path_lookup"]


# ---------- ComputeResult ----------


def test_compute_result_success() -> None:
    """成功结果填 output，error=None。"""
    result = ComputeResult(
        success=True,
        output={"p2": 51000, "t2": 1456.8, "m2": 0.4},
        raw_stdout='{"p2": 51000}',
        exit_code=0,
        duration_ms=1234,
    )

    assert result.success is True
    assert result.output == {"p2": 51000, "t2": 1456.8, "m2": 0.4}
    assert result.exit_code == 0
    assert result.duration_ms == 1234
    assert result.error is None


def test_compute_result_failure() -> None:
    """失败结果填 error，output=None。"""
    result = ComputeResult(
        success=False,
        exit_code=2,
        raw_stderr="invalid argument: --mach",
        error=ComputeError(
            type=ComputeErrorType.INVALID_PARAMS,
            message="bad argument",
        ),
    )

    assert result.success is False
    assert result.output is None
    assert result.error is not None
    assert result.error.type == ComputeErrorType.INVALID_PARAMS


def test_compute_result_defaults_all_optional() -> None:
    """ComputeResult 只 success 必填，其他都是 None。"""
    result = ComputeResult(success=False)

    assert result.success is False
    assert result.output is None
    assert result.raw_stdout is None
    assert result.raw_stderr is None
    assert result.exit_code is None
    assert result.duration_ms is None
    assert result.error is None


# ---------- ComputePort 协议一致性 ----------


class _FakeComputePort:
    """一个最小的 ``ComputePort`` 结构性实现（仅用于测试）。"""

    def list_operations(self) -> list[ComputeSpec]:
        return [ComputeSpec(name="noop", description="no-op")]

    async def execute(self, req: ComputeRequest) -> ComputeResult:
        return ComputeResult(success=True, output={"echo": req.operation})


def test_compute_port_runtime_checkable() -> None:
    """符合签名的类应通过 isinstance 检查（runtime_checkable Protocol）。"""
    fake = _FakeComputePort()
    assert isinstance(fake, ComputePort)


def test_compute_port_missing_method_fails() -> None:
    """缺少 ``execute`` 方法的类不应通过协议检查。"""

    class _PartialImpl:
        def list_operations(self) -> list[ComputeSpec]:
            return []

    assert not isinstance(_PartialImpl(), ComputePort)


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_fake_compute_port_execute() -> None:
    """``_FakeComputePort.execute`` 能正确返回 ``ComputeResult``。"""
    fake = _FakeComputePort()
    req = ComputeRequest(operation="add", params={"a": 1, "b": 2})
    result: ComputeResult = await fake.execute(req)

    assert result.success is True
    assert result.output == {"echo": "add"}


# ---------- 静态协议一致性声明（mypy / 文档） ----------


_protocol_check: ComputePort = _FakeComputePort()  # type: ignore[assignment]
_unused_for_lint: Any = _protocol_check  # 避免 ruff F841 未使用变量警告
