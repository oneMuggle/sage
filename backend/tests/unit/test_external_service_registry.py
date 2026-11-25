"""声明式外部服务注册表 —— MinerU spec 声明契约。"""

from backend.services.external_services.registry import get_by_preference_key, get_service


def test_mineru_registered_as_spec():
    spec = get_service("mineru")
    assert spec is not None
    assert spec.preference_key == "mineru_service"
    assert get_by_preference_key("mineru_service") is spec
    assert any(
        f.json_field == "apiKey" and f.account == "mineru:api_key" for f in spec.secret_fields
    )


def test_unknown_service_returns_none():
    assert get_service("does-not-exist") is None
    assert get_by_preference_key("nope") is None
