"""r60 — MCP OAuth 纯函数库层单测（PKCE / 发现 URL / 元数据 / 回调 / token）。"""

import base64
import hashlib

import pytest

from backend.mcp.oauth import (
    CODE_VERIFIER_CHARSET,
    MAX_CODE_VERIFIER_LENGTH,
    MIN_CODE_VERIFIER_LENGTH,
    OAuthAuthorizeError,
    OAuthMetadataError,
    OAuthStateError,
    build_authorization_server_discovery_urls,
    build_authorization_url,
    build_protected_resource_discovery_urls,
    code_challenge_s256,
    generate_code_verifier,
    generate_pkce_pair,
    generate_state,
    parse_authorization_server_metadata,
    parse_protected_resource_metadata,
    parse_token_response,
    validate_authorization_callback,
)

pytestmark = pytest.mark.unit


class TestPkce:
    def test_verifier_default_length_and_charset(self):
        verifier = generate_code_verifier()
        assert len(verifier) == 64
        assert set(verifier) <= set(CODE_VERIFIER_CHARSET)

    @pytest.mark.parametrize("length", [MIN_CODE_VERIFIER_LENGTH, MAX_CODE_VERIFIER_LENGTH])
    def test_verifier_length_bounds_accepted(self, length):
        assert len(generate_code_verifier(length)) == length

    @pytest.mark.parametrize("length", [0, 42, 129, -1])
    def test_verifier_length_out_of_bounds_rejected(self, length):
        with pytest.raises(ValueError, match="长度"):
            generate_code_verifier(length)

    def test_verifier_uniqueness(self):
        assert generate_code_verifier() != generate_code_verifier()

    def test_challenge_matches_rfc7636_formula(self):
        verifier = generate_code_verifier(64)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        assert code_challenge_s256(verifier) == expected.decode("ascii").rstrip("=")

    def test_pair_verifier_and_challenge_consistent(self):
        verifier, challenge = generate_pkce_pair(43)
        assert len(verifier) == 43
        assert challenge == code_challenge_s256(verifier)

    def test_state_is_urlsafe_and_unique(self):
        s1, s2 = generate_state(), generate_state()
        assert s1 != s2
        assert len(s1) >= 32


class TestDiscoveryUrls:
    def test_authorization_server_root_url(self):
        urls = build_authorization_server_discovery_urls("https://mcp.example.com")
        assert urls == ["https://mcp.example.com/.well-known/oauth-authorization-server"]

    def test_authorization_server_path_url_inserts_wellknown(self):
        urls = build_authorization_server_discovery_urls("https://mcp.example.com/api/mcp")
        assert urls == [
            "https://mcp.example.com/.well-known/oauth-authorization-server/api/mcp",
            "https://mcp.example.com/.well-known/oauth-authorization-server/api",
            "https://mcp.example.com/.well-known/oauth-authorization-server",
        ]

    def test_protected_resource_discovery_urls(self):
        urls = build_protected_resource_discovery_urls("https://mcp.example.com/mcp/")
        assert urls == [
            "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
            "https://mcp.example.com/.well-known/oauth-protected-resource",
        ]

    def test_invalid_server_url_rejected(self):
        with pytest.raises(ValueError, match="无效"):
            build_authorization_server_discovery_urls("not-a-url")


class TestMetadataParsing:
    def test_authorization_server_metadata_ok(self):
        meta = parse_authorization_server_metadata(
            {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "scopes_supported": ["mcp:tools"],
            }
        )
        assert meta["issuer"] == "https://auth.example.com"
        assert meta["scopes_supported"] == ["mcp:tools"]

    @pytest.mark.parametrize(
        "data",
        [
            None,
            "str",
            {"issuer": "x"},  # 缺两个端点
            {"issuer": "x", "authorization_endpoint": "a"},  # 缺 token_endpoint
            {"issuer": "", "authorization_endpoint": "a", "token_endpoint": "b"},
        ],
    )
    def test_authorization_server_metadata_invalid(self, data):
        with pytest.raises(OAuthMetadataError):
            parse_authorization_server_metadata(data)

    def test_protected_resource_metadata_ok(self):
        meta = parse_protected_resource_metadata(
            {"resource": "https://mcp.example.com", "authorization_servers": ["https://auth.example.com"]}
        )
        assert meta["authorization_servers"] == ["https://auth.example.com"]

    def test_protected_resource_metadata_servers_optional(self):
        meta = parse_protected_resource_metadata({"resource": "https://mcp.example.com"})
        assert meta["authorization_servers"] == []

    def test_protected_resource_metadata_invalid_servers(self):
        with pytest.raises(OAuthMetadataError, match="authorization_servers"):
            parse_protected_resource_metadata(
                {"resource": "https://mcp.example.com", "authorization_servers": ["ok", 7]}
            )


class TestAuthorizationUrl:
    def test_url_contains_required_params(self):
        url = build_authorization_url(
            "https://auth.example.com/authorize",
            client_id="sage",
            redirect_uri="http://127.0.0.1:0/callback",
            state="st-1",
            code_challenge="cc-1",
        )
        assert url.startswith("https://auth.example.com/authorize?")
        for piece in (
            "response_type=code",
            "client_id=sage",
            "code_challenge_method=S256",
            "state=st-1",
            "code_challenge=cc-1",
        ):
            assert piece in url
        assert "scope" not in url
        assert "resource" not in url

    def test_url_appends_scope_and_resource(self):
        url = build_authorization_url(
            "https://auth.example.com/authorize",
            client_id="sage",
            redirect_uri="http://127.0.0.1:0/callback",
            state="st",
            code_challenge="cc",
            scope="mcp:tools openid",
            resource="https://mcp.example.com",
        )
        assert "scope=mcp%3Atools+openid" in url or "scope=mcp%3Atools%20openid" in url
        assert "resource=https%3A%2F%2Fmcp.example.com" in url

    def test_empty_endpoint_rejected(self):
        with pytest.raises(OAuthMetadataError):
            build_authorization_url(
                "",
                client_id="sage",
                redirect_uri="http://x/cb",
                state="s",
                code_challenge="c",
            )


class TestCallbackValidation:
    def test_valid_callback_returns_code(self):
        code = validate_authorization_callback(
            "http://127.0.0.1:8765/callback?code=abc&state=st-1", "st-1"
        )
        assert code == "abc"

    def test_error_response_raises_authorize_error(self):
        with pytest.raises(OAuthAuthorizeError, match="access_denied"):
            validate_authorization_callback(
                "http://x/cb?error=access_denied&error_description=user+said+no",
                "st-1",
            )

    def test_missing_code_raises(self):
        with pytest.raises(OAuthAuthorizeError, match="code"):
            validate_authorization_callback("http://x/cb?state=st-1", "st-1")

    def test_state_mismatch_raises(self):
        with pytest.raises(OAuthStateError):
            validate_authorization_callback(
                "http://x/cb?code=abc&state=evil", "st-1"
            )

    def test_missing_state_raises(self):
        with pytest.raises(OAuthStateError):
            validate_authorization_callback("http://x/cb?code=abc", "st-1")


class TestTokenResponse:
    def test_valid_token_response_defaults_bearer(self):
        token = parse_token_response({"access_token": "at-1", "expires_in": 3600})
        assert token["access_token"] == "at-1"
        assert token["token_type"] == "Bearer"
        assert token["expires_in"] == 3600

    def test_missing_access_token_raises(self):
        with pytest.raises(OAuthMetadataError, match="access_token"):
            parse_token_response({"token_type": "Bearer"})

    def test_invalid_expires_in_raises(self):
        with pytest.raises(OAuthMetadataError, match="expires_in"):
            parse_token_response({"access_token": "at", "expires_in": 0})

    def test_non_dict_raises(self):
        with pytest.raises(OAuthMetadataError, match="JSON 对象"):
            parse_token_response(["not", "a", "dict"])
