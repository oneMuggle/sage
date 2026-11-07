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
    authorize_mcp_server,
    build_authorization_server_discovery_urls,
    build_authorization_url,
    build_dynamic_registration_request,
    build_protected_resource_discovery_urls,
    code_challenge_s256,
    exchange_authorization_code,
    generate_code_verifier,
    generate_pkce_pair,
    generate_state,
    parse_authorization_server_metadata,
    parse_protected_resource_metadata,
    parse_registration_response,
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


# ============================================================================
# r62: 动态注册 / code 交换 / 授权编排
# ============================================================================


class TestDynamicRegistration:
    def test_request_shape(self):
        headers, body = build_dynamic_registration_request(
            "sage", "http://127.0.0.1:0/callback", scope="mcp:tools"
        )
        assert headers["Content-Type"] == "application/json"
        assert body["client_name"] == "sage"
        assert body["redirect_uris"] == ["http://127.0.0.1:0/callback"]
        assert body["grant_types"] == ["authorization_code", "refresh_token"]
        assert body["response_types"] == ["code"]
        assert body["token_endpoint_auth_method"] == "none"
        assert body["scope"] == "mcp:tools"

    def test_parse_ok(self):
        reg = parse_registration_response({"client_id": "cid-1", "client_secret": "s"})
        assert reg["client_id"] == "cid-1"

    def test_parse_missing_client_id_raises(self):
        with pytest.raises(OAuthMetadataError, match="client_id"):
            parse_registration_response({"client_secret": "s"})


class TestExchangeAuthorizationCode:
    def test_request_shape(self):
        url, headers, body = exchange_authorization_code(
            "https://auth.example.com/token",
            client_id="cid",
            code="abc",
            redirect_uri="http://127.0.0.1:0/callback",
            code_verifier="v" * 43,
        )
        assert url == "https://auth.example.com/token"
        assert "grant_type=authorization_code" in body
        assert "code=abc" in body
        assert "code_verifier=" in body
        assert "client_id=cid" in body
        assert "client_secret" not in body

    def test_optional_secret_and_resource(self):
        _, _, body = exchange_authorization_code(
            "https://a/t",
            client_id="cid",
            code="abc",
            redirect_uri="http://x/cb",
            code_verifier="v" * 43,
            client_secret="sec",
            resource="https://mcp.example.com",
        )
        assert "client_secret=sec" in body
        assert "resource=" in body


class TestAuthorizeOrchestration:
    SERVER = "https://mcp.example.com/mcp"

    def _fakes(self, *, include_resource_meta=True, include_registration=True):
        calls = {"get": [], "post": [], "auth_url": None}

        async def get_json(url):
            calls["get"].append(url)
            if "oauth-protected-resource" in url and include_resource_meta:
                return {
                    "resource": self.SERVER,
                    "authorization_servers": ["https://auth.example.com"],
                }
            if "oauth-authorization-server" in url:
                meta = {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                }
                if include_registration:
                    meta["registration_endpoint"] = "https://auth.example.com/register"
                return meta
            raise AssertionError(f"unexpected GET {url}")

        async def post_json(url, headers, body):
            calls["post"].append((url, headers, body))
            if url.endswith("/register"):
                return {"client_id": "cid-77"}
            if url.endswith("/token"):
                return {
                    "access_token": "at-final",
                    "refresh_token": "rt-final",
                    "expires_in": 3600,
                    "scope": "mcp:tools",
                }
            raise AssertionError(f"unexpected POST {url}")

        async def wait_callback(authorization_url):
            calls["auth_url"] = authorization_url
            from urllib.parse import parse_qs, urlparse

            state = parse_qs(urlparse(authorization_url).query)["state"][0]
            return f"http://127.0.0.1:8765/callback?code=xyz&state={state}"

        return get_json, post_json, wait_callback, calls

    async def test_full_flow_produces_record(self):
        get_json, post_json, wait_callback, calls = self._fakes()
        record = await authorize_mcp_server(
            self.SERVER,
            redirect_uri="http://127.0.0.1:8765/callback",
            scope="mcp:tools",
            http_get_json=get_json,
            http_post_json=post_json,
            wait_for_callback=wait_callback,
        )
        assert record.access_token == "at-final"
        assert record.refresh_token == "rt-final"
        assert record.client_id == "cid-77"
        assert record.token_endpoint == "https://auth.example.com/token"
        assert record.expires_at > 0
        assert record.scope == "mcp:tools"
        assert "code_challenge_method=S256" in calls["auth_url"]
        assert "client_id=cid-77" in calls["auth_url"]
        token_posts = [p for p in calls["post"] if p[0].endswith("/token")]
        assert "code_verifier=" in token_posts[0][2]

    async def test_fallback_direct_discovery_without_resource_meta(self):
        get_json, post_json, wait_callback, _ = self._fakes(include_resource_meta=False)
        record = await authorize_mcp_server(
            self.SERVER,
            redirect_uri="http://127.0.0.1:8765/callback",
            http_get_json=get_json,
            http_post_json=post_json,
            wait_for_callback=wait_callback,
        )
        assert record.access_token == "at-final"

    async def test_no_metadata_raises(self):
        async def get_json(url):
            raise OSError("no metadata here")

        async def post_json(url, headers, body):
            raise AssertionError("should not post")

        async def wait_callback(url):
            raise AssertionError("should not authorize")

        with pytest.raises(OAuthMetadataError, match="元数据"):
            await authorize_mcp_server(
                self.SERVER,
                redirect_uri="http://x/cb",
                http_get_json=get_json,
                http_post_json=post_json,
                wait_for_callback=wait_callback,
            )

    async def test_no_registration_endpoint_raises(self):
        get_json, post_json, wait_callback, _ = self._fakes(include_registration=False)
        with pytest.raises(OAuthMetadataError, match="registration_endpoint"):
            await authorize_mcp_server(
                self.SERVER,
                redirect_uri="http://127.0.0.1:8765/callback",
                http_get_json=get_json,
                http_post_json=post_json,
                wait_for_callback=wait_callback,
            )

    async def test_state_tamper_aborts(self):
        get_json, post_json, _, calls = self._fakes()

        async def evil_callback(authorization_url):
            return "http://127.0.0.1:8765/callback?code=xyz&state=evil"

        with pytest.raises(OAuthStateError):
            await authorize_mcp_server(
                self.SERVER,
                redirect_uri="http://127.0.0.1:8765/callback",
                http_get_json=get_json,
                http_post_json=post_json,
                wait_for_callback=evil_callback,
            )
        assert not [p for p in calls["post"] if p[0].endswith("/token")]
