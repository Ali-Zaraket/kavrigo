"""Control-plane API tests, including the live-trading gate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kavrigo_api.app import create_app
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(kavrigo_env="local", log_format="console")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


class TestLiveTradingGate:
    """ADR 0001. The gate is a startup refusal, not a runtime branch."""

    def test_enabling_live_trading_refuses_to_start(self) -> None:
        with pytest.raises(ValidationError, match="LIVE_TRADING_ENABLED=true is refused"):
            Settings(live_trading_enabled=True)

    def test_live_prod_environment_does_not_exist(self) -> None:
        with pytest.raises(ValidationError, match="live-prod environment does not exist"):
            Settings(kavrigo_env="live-prod")

    def test_defaults_are_paper(self, settings: Settings) -> None:
        assert settings.live_trading_enabled is False
        assert settings.default_trading_mode == "paper"


class TestAuthConfigurationGate:
    """The development identity provider accepts unsigned tokens (see auth/identity.py)."""

    def test_dev_auth_is_refused_outside_local(self) -> None:
        for environment in ("dev", "staging", "paper-prod"):
            with pytest.raises(ValidationError, match="AUTH_PROVIDER=dev is refused"):
                Settings(kavrigo_env=environment, auth_provider="dev")

    def test_dev_auth_is_allowed_locally(self) -> None:
        assert Settings(kavrigo_env="local", auth_provider="dev").auth_provider == "dev"

    def test_jwks_auth_requires_issuer_and_jwks_url(self) -> None:
        with pytest.raises(ValidationError, match="AUTH_ISSUER, AUTH_JWKS_URL"):
            Settings(kavrigo_env="staging", auth_provider="jwks")

    def test_jwks_auth_accepts_a_complete_configuration(self) -> None:
        settings = Settings(
            kavrigo_env="staging",
            auth_provider="jwks",
            auth_issuer="https://identity.example.test",
            auth_jwks_url="https://identity.example.test/.well-known/jwks.json",
            auth_audience="kavrigo-api",
        )
        assert settings.auth_provider == "jwks"

    def test_platform_mode_is_server_authoritative(self, client: TestClient) -> None:
        response = client.get("/v1/platform/mode")
        assert response.status_code == 200
        body = response.json()
        assert body["live_trading_enabled"] is False
        assert body["default_trading_mode"] == "paper"
        assert "Simulated results only" in body["disclosure"]


class TestProbes:
    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readyz_reports_unconfigured_dependencies_honestly(self, client: TestClient) -> None:
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["checks"]["postgres"] == "not_configured"

    def test_every_response_carries_a_request_id(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.headers["x-request-id"]

    def test_supplied_request_id_is_echoed(self, client: TestClient) -> None:
        response = client.get("/healthz", headers={"x-request-id": "abc123"})
        assert response.headers["x-request-id"] == "abc123"


class TestErrors:
    def test_unknown_route_is_a_structured_404(self, client: TestClient) -> None:
        assert client.get("/does-not-exist").status_code == 404

    def test_api_errors_carry_a_stable_code_and_request_id(self, settings: Settings) -> None:
        app = create_app(settings)

        @app.get("/_test/api-error")
        async def _raise() -> None:
            raise ApiError(
                ErrorCode.WORKSPACE_REQUIRED,
                "A workspace context is required.",
                http_status=403,
                details={"header": "x-workspace-id"},
            )

        response = TestClient(app).get("/_test/api-error")
        assert response.status_code == 403
        body = response.json()
        assert body["code"] == "workspace_required"
        assert body["details"] == {"header": "x-workspace-id"}
        assert body["request_id"] == response.headers["x-request-id"]

    def test_unexpected_errors_leak_no_internal_detail(self, settings: Settings) -> None:
        """An exception message can carry internal structure or payload fragments."""
        app = create_app(settings)

        @app.get("/_test/boom")
        async def _boom() -> None:
            raise RuntimeError("connection string postgres://user:hunter2@db/kavrigo failed")

        response = TestClient(app, raise_server_exceptions=False).get("/_test/boom")
        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "internal_error"
        assert body["message"] == "An unexpected error occurred."
        assert "hunter2" not in response.text
        assert "postgres" not in response.text
        assert body["request_id"]


class TestOpenApi:
    def test_schema_is_generated(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "Kavrigo Control Plane"
        assert "/v1/platform/mode" in schema["paths"]

    def test_description_carries_the_simulation_disclosure(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "paper and research only" in schema["info"]["description"]

    def test_docs_are_disabled_in_production_like_environments(self) -> None:
        app = create_app(
            Settings(
                kavrigo_env="paper-prod",
                auth_provider="jwks",
                auth_issuer="https://identity.example.test",
                auth_jwks_url="https://identity.example.test/.well-known/jwks.json",
            )
        )
        assert app.docs_url is None
