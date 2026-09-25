"""R126 — session-workspace 绑定错误层级单元测试。

覆盖：六个具体错误的继承关系与 code 属性、safe_message 契约
（调用方安全文案，不泄漏文件系统布局）、str(exc) 兼容、基类统一捕获。
"""

from __future__ import annotations

import pytest

from backend.office.workspace_errors import (
    WorkspaceBindingError,
    WorkspaceDocumentNotFoundError,
    WorkspaceGenerationMismatchError,
    WorkspaceNotBoundError,
    WorkspacePathMismatchError,
    WorkspaceRevokedError,
    WorkspaceSessionNotFoundError,
)

pytestmark = pytest.mark.unit


def test_all_errors_inherit_base():
    for cls in (
        WorkspaceSessionNotFoundError,
        WorkspaceNotBoundError,
        WorkspaceRevokedError,
        WorkspaceGenerationMismatchError,
        WorkspacePathMismatchError,
        WorkspaceDocumentNotFoundError,
    ):
        assert issubclass(cls, WorkspaceBindingError)
        assert issubclass(cls, Exception)


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (WorkspaceSessionNotFoundError, "session_not_found"),
        (WorkspaceNotBoundError, "workspace_not_bound"),
        (WorkspaceRevokedError, "workspace_revoked"),
        (WorkspaceGenerationMismatchError, "workspace_generation_mismatch"),
        (WorkspacePathMismatchError, "workspace_path_mismatch"),
        (WorkspaceDocumentNotFoundError, "document_not_found"),
    ],
)
def test_error_codes(cls, code):
    assert cls.code == code
    assert cls("msg").code == code  # 实例继承类级 code


def test_base_code_is_catchall():
    assert WorkspaceBindingError.code == "workspace_binding_error"


def test_safe_message_attribute_set():
    exc = WorkspacePathMismatchError("workspace no longer matches")
    assert exc.safe_message == "workspace no longer matches"
    assert exc.safe_message == str(exc)  # 两者一致，路由层可放心用 safe_message


def test_safe_message_does_not_echo_submitted_path_automatically():
    # 契约：safe_message 只含调用方显式给定的文案；异常本身不会把
    # submitted path 拼进 safe_message（路径若出现，只能是调用方显式写入）
    exc = WorkspaceBindingError("binding rejected")
    assert "C:\\" not in exc.safe_message
    assert exc.safe_message == "binding rejected"


def test_base_class_catches_all_for_500_fallback():
    with pytest.raises(WorkspaceBindingError):
        raise WorkspaceDocumentNotFoundError("doc gone")


def test_str_preserves_message():
    exc = WorkspaceSessionNotFoundError("session 42 not found")
    assert str(exc) == "session 42 not found"
