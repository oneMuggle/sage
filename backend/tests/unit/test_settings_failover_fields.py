"""2026-11-26: 端点优先级故障转移设置字段的白名单校验测试。

覆盖:
- ``endpoints[].priority`` 必须是正整数（bool/0/负数/字符串/浮点都拒收）。
- ``failover`` 顶层段只接受 4 个合法子键，值与范围校验。
"""

import pytest

from backend.data.settings_canonicalizer import validate_settings_shape


def _base():
    return {"endpoints": [{"id": "e1", "name": "a", "baseUrl": "http://x", "priority": 2}]}


def test_priority_and_failover_accepted():
    settings = _base()
    settings["failover"] = {
        "enabled": True,
        "probeIntervalMs": 300000,
        "cooldownMs": 60000,
        "consecutiveFailThreshold": 2,
    }
    validate_settings_shape(settings)  # 不抛


def test_priority_optional():
    settings = {"endpoints": [{"id": "e1", "name": "a", "baseUrl": "http://x"}]}
    validate_settings_shape(settings)


@pytest.mark.parametrize("bad", [0, -1, True, "1", 1.5])
def test_priority_must_be_positive_int(bad):
    settings = _base()
    settings["endpoints"][0]["priority"] = bad
    with pytest.raises(ValueError):
        validate_settings_shape(settings)


def test_unknown_failover_key_rejected():
    settings = _base()
    settings["failover"] = {"enabled": True, "foo": 1}
    with pytest.raises(ValueError):
        validate_settings_shape(settings)


def test_failover_must_be_dict():
    settings = _base()
    settings["failover"] = "enabled"
    with pytest.raises(ValueError):
        validate_settings_shape(settings)


@pytest.mark.parametrize(
    "key,value",
    [
        ("probeIntervalMs", 1000),
        ("cooldownMs", 100),
        ("consecutiveFailThreshold", 0),
        ("consecutiveFailThreshold", 11),
        ("enabled", "yes"),
        ("probeIntervalMs", True),
    ],
)
def test_failover_values_validated(key, value):
    settings = _base()
    settings["failover"] = {key: value}
    with pytest.raises(ValueError):
        validate_settings_shape(settings)
