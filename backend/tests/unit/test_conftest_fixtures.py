"""验证 conftest fixtures (P0-T7) 可用。"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_sample_messages_shape(sample_messages):
    """sample_messages fixture 包含 system + user 两条"""
    assert len(sample_messages) == 2
    assert sample_messages[0]["role"] == "system"
    assert sample_messages[1]["role"] == "user"
    assert "helpful" in sample_messages[0]["content"]


def test_sample_user_query_nonempty(sample_user_query):
    """sample_user_query 非空"""
    assert isinstance(sample_user_query, str)
    assert len(sample_user_query) > 0


def test_tmp_data_dir_is_pathlib(tmp_data_dir):
    """tmp_data_dir 是 pathlib.Path 实例"""
    assert isinstance(tmp_data_dir, Path)


def test_mock_llm_ok_fixture_works(mock_llm_ok):
    """mock_llm_ok 上下文管理器工作正常"""
    assert mock_llm_ok is not None
    # respx 至少注册了一个路由
    assert len(mock_llm_ok.calls) == 0  # 调用前为空


def test_mock_llm_rate_limit_fixture_works(mock_llm_rate_limit):
    """mock_llm_rate_limit fixture 不抛错"""
    assert mock_llm_rate_limit is not None


def test_mock_llm_timeout_fixture_works(mock_llm_timeout):
    """mock_llm_timeout fixture 不抛错"""
    assert mock_llm_timeout is not None


def test_mock_llm_server_error_fixture_works(mock_llm_server_error):
    """mock_llm_server_error fixture 不抛错"""
    assert mock_llm_server_error is not None
