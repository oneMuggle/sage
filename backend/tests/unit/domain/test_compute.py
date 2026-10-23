"""R133 — 外部计算领域模型单元测试。

覆盖：ComputeSpec/ComputeRequest 工厂缺省字段、ComputeErrorType 六分类
及 str 枚举比较、ComputeError details 缺省、ComputeResult 成功/失败形态
与 error 往返。
"""

from __future__ import annotations

import pytest

from backend.domain.compute import (
    ComputeError,
    ComputeErrorType,
    ComputeRequest,
    ComputeResult,
    ComputeSpec,
)

pytestmark = pytest.mark.unit


def test_compute_spec_defaults():
    spec = ComputeSpec(name="shock_tube", description="激波管计算")
    assert spec.params_schema == {}


def test_compute_request_defaults():
    req = ComputeRequest(operation="shock_tube")
    assert req.params == {}
    assert req.timeout_ms is None
    assert req.request_id is None


def test_error_type_six_classifications():
    assert ComputeErrorType.OPERATION_NOT_FOUND == "operation_not_found"
    assert ComputeErrorType.INVALID_PARAMS == "invalid_params"
    assert ComputeErrorType.TIMEOUT == "timeout"
    assert ComputeErrorType.PROCESS_FAILED == "process_failed"
    assert ComputeErrorType.OUTPUT_PARSE_ERROR == "output_parse_error"
    assert ComputeErrorType.INTERNAL_ERROR == "internal_error"
    assert len(ComputeErrorType) == 6


def test_error_details_default_empty():
    err = ComputeError(type=ComputeErrorType.TIMEOUT, message="超时")
    assert err.details == {}
    assert str(err.type) == "ComputeErrorType.TIMEOUT" or err.type == ComputeErrorType.TIMEOUT


def test_result_success_shape():
    result = ComputeResult(success=True, output={"Mach": 2.1}, duration_ms=120)
    assert result.success is True
    assert result.output == {"Mach": 2.1}
    assert result.error is None
    assert result.raw_stdout is None
    assert result.exit_code is None


def test_result_failure_shape():
    err = ComputeError(type=ComputeErrorType.PROCESS_FAILED, message="exit 1", details={"exit_code": 1})
    result = ComputeResult(success=False, error=err, exit_code=1)
    assert result.success is False
    assert result.error.type == ComputeErrorType.PROCESS_FAILED
    assert result.error.details == {"exit_code": 1}


def test_error_enum_is_str_subclass():
    assert ComputeErrorType.TIMEOUT == "timeout"  # str 枚举可直接比较


def test_request_full_fields():
    req = ComputeRequest(
        operation="wind_tunnel",
        params={"mach": 3},
        timeout_ms=5000,
        request_id="req-1",
    )
    assert req.params == {"mach": 3}
    assert req.timeout_ms == 5000
    assert req.request_id == "req-1"
