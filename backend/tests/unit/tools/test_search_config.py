"""R149 — 搜索配置加载器单元测试。

覆盖：fail-safe 全路径（读取异常/非法 JSON/非 dict/空值回退默认链）、
order 引擎过滤（未知条目剔除、全未知回退）、parallel 与
parallel_first_n 解析、enc: 密钥解包成功/失败/普通透传。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.tools import search_config as sc
from backend.tools.search_config import DEFAULT_ENGINE_ORDER, SearchConfig, load_search_config

pytestmark = pytest.mark.unit


def _repo(raw):
    def get(key):
        assert key == "search_config"
        return raw

    return SimpleNamespace(get=get)


# ---------------------------------------------------------------------------
# fail-safe：全部回退默认链
# ---------------------------------------------------------------------------


def test_missing_raw_returns_default():
    assert load_search_config(_repo(None)) == SearchConfig()


def test_repo_raises_returns_default():
    class _Boom:
        def get(self, key):
            raise RuntimeError("kv broken")

    result = load_search_config(_Boom())
    assert result.engine_order == DEFAULT_ENGINE_ORDER
    assert result.tavily_key == ""


def test_invalid_json_returns_default():
    result = load_search_config(_repo("{not json"))
    assert result.engine_order == DEFAULT_ENGINE_ORDER


def test_non_dict_json_returns_default():
    result = load_search_config(_repo(json.dumps(["bing", "ddg"])))
    assert result.engine_order == DEFAULT_ENGINE_ORDER


# ---------------------------------------------------------------------------
# 合法配置解析
# ---------------------------------------------------------------------------


def test_valid_config_parsed():
    raw = json.dumps(
        {
            "order": ["tavily", "ddg", "bing"],
            "tavily_key": "tv-key",
            "zhipu_key": "zp-key",
            "parallel": True,
            "parallel_first_n": 3,
        }
    )
    result = load_search_config(_repo(raw))
    assert result.engine_order == ("tavily", "ddg", "bing")
    assert result.tavily_key == "tv-key"
    assert result.zhipu_key == "zp-key"
    assert result.parallel is True
    assert result.parallel_first_n == 3


def test_unknown_engines_filtered_out():
    raw = json.dumps({"order": ["bing", "nope", "tavily"]})
    result = load_search_config(_repo(raw))
    assert result.engine_order == ("bing", "tavily")


def test_all_unknown_engines_fall_back_to_default():
    raw = json.dumps({"order": ["nope1", "nope2"]})
    result = load_search_config(_repo(raw))
    assert result.engine_order == DEFAULT_ENGINE_ORDER


def test_parallel_defaults_and_first_n_validation():
    raw = json.dumps({"order": ["bing"], "parallel": "yes", "parallel_first_n": 0})
    result = load_search_config(_repo(raw))
    assert result.parallel is True  # bool("yes") 真值
    assert result.parallel_first_n == 2  # 0 非法 → 回退 2

    raw2 = json.dumps({"order": ["bing"], "parallel": 1, "parallel_first_n": -1})
    result2 = load_search_config(_repo(raw2))
    assert result2.parallel is True
    assert result2.parallel_first_n == 2


def test_parallel_absent_defaults_false():
    raw = json.dumps({"order": ["bing"]})
    result = load_search_config(_repo(raw))
    assert result.parallel is False


# --- enc: 密钥解包 ---


def test_unwrap_plain_passthrough():
    assert sc._unwrap_secret("plain-key") == "plain-key"


def test_unwrap_non_string_returns_empty():
    assert sc._unwrap_secret(None) == ""
    assert sc._unwrap_secret(123) == ""


def test_unwrap_enc_decrypts(monkeypatch):
    from backend.services import secret_box

    monkeypatch.setattr(secret_box, "decrypt_secret", lambda v: "decrypted-key")
    assert sc._unwrap_secret("enc:v1:payload") == "decrypted-key"


def test_unwrap_decrypt_failure_returns_empty(monkeypatch):
    from backend.services import secret_box

    def boom(_v):
        raise RuntimeError("no key")

    monkeypatch.setattr(secret_box, "decrypt_secret", boom)
    assert sc._unwrap_secret("enc:v1:payload") == ""


def test_config_with_enc_wrapped_key(monkeypatch):
    from backend.services import secret_box

    monkeypatch.setattr(secret_box, "decrypt_secret", lambda v: "tv-dec")
    raw = json.dumps({"order": ["tavily"], "tavily_key": "enc:v1:xx"})
    result = load_search_config(_repo(raw))
    assert result.tavily_key == "tv-dec"
