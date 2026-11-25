"""通用 service JSON 字段级加解密（由 ExternalServiceSpec.secret_fields 驱动）。"""

from __future__ import annotations

import json

import pytest

from backend.services.external_services.registry import get_service
from backend.services.secret_box import unwrap_service_json, wrap_service_json

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _forced_test_scheme(monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")


def test_wrap_is_idempotent_and_preserves_non_secret():
    spec = get_service("mineru")
    assert spec is not None
    raw = '{"baseUrl":"http://x","apiKey":"k1","tier":"pro"}'
    once = wrap_service_json(spec, raw)
    twice = wrap_service_json(spec, once)
    assert once == twice
    assert "k1" not in once
    out = unwrap_service_json(spec, once)
    assert json.loads(out)["apiKey"] == "k1"
    assert json.loads(out)["baseUrl"] == "http://x"


def test_only_declared_secret_fields_are_encrypted():
    spec = get_service("mineru")
    raw = '{"baseUrl":"http://x","apiKey":"k1","other":"v"}'
    wrapped = json.loads(wrap_service_json(spec, raw))
    assert wrapped["baseUrl"] == "http://x"
    assert wrapped["other"] == "v"
    assert wrapped["apiKey"].startswith("enc:")


def test_non_json_and_non_dict_inputs_pass_through():
    spec = get_service("mineru")
    assert wrap_service_json(spec, "not json") == "not json"
    assert unwrap_service_json(spec, "[1,2]") == "[1,2]"
    assert wrap_service_json(spec, None) is None
    assert unwrap_service_json(spec, None) is None
