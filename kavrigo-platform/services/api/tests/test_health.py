"""Control-plane API tests, including the live-trading gate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kavrigo_api.app import create_app
from kavrigo_api.auth.identity import DevIdentityProvider
from kavrigo_api.db.session import EXPECTED_SCHEMA_REVISION
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

    def test_injected_dev_provider_is_refused_outside_local(self) -> None:
        settings = Settings(
            kavrigo_env="paper-prod",
            auth_provider="jwks",
            auth_issuer="https://identity.example.test",
            auth_jwks_url="https://identity.example.test/.well-known/jwks.json",
            auth_session_profile="clerk_v2",
            auth_allowed_parties=["https://app.example.test"],
        )
        with pytest.raises(ValueError, match="development identity provider is refused"):
            create_app(settings, identity_provider=DevIdentityProvider())

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

    @pytest.mark.parametrize("environment", ["dev", "staging", "paper-prod"])
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("auth_issuer", "http://identity.example.test"),
            ("auth_jwks_url", "http://identity.example.test/jwks.json"),
            ("auth_jwks_url", "https://user:password@identity.example.test/jwks.json"),
            ("auth_jwks_url", "https://identity.example.test/jwks.json#fragment"),
            ("auth_jwks_url", "not-a-url"),
        ],
    )
    def test_nonlocal_jwks_rejects_insecure_endpoints(
        self, environment: str, field: str, value: str
    ) -> None:
        config = {
            "kavrigo_env": environment,
            "auth_provider": "jwks",
            "auth_issuer": "https://identity.example.test",
            "auth_jwks_url": "https://identity.example.test/jwks.json",
        }
        config[field] = value
        with pytest.raises(ValidationError, match="credential-free HTTPS URL"):
            Settings(**config)

    def test_local_jwks_can_use_http_for_development(self) -> None:
        settings = Settings(
            kavrigo_env="local",
            auth_provider="jwks",
            auth_issuer="http://localhost:4000",
            auth_jwks_url="http://localhost:4000/jwks.json",
        )
        assert settings.auth_provider == "jwks"

    def test_paper_prod_requires_clerk_session_profile_and_allowed_party(self) -> None:
        config = {
            "kavrigo_env": "paper-prod",
            "auth_provider": "jwks",
            "auth_issuer": "https://identity.example.test",
            "auth_jwks_url": "https://identity.example.test/.well-known/jwks.json",
        }
        with pytest.raises(ValidationError, match="Clerk v2 session profile"):
            Settings(**config)
        with pytest.raises(ValidationError, match="AUTH_ALLOWED_PARTIES"):
            Settings(**config, auth_session_profile="clerk_v2")
        settings = Settings(
            **config,
            auth_session_profile="clerk_v2",
            auth_allowed_parties=["https://app.example.test"],
        )
        assert settings.auth_session_profile == "clerk_v2"

    @pytest.mark.parametrize(
        ("issuer", "jwks_url", "error"),
        [
            (
                "https://example.clerk.accounts.dev",
                "https://example.clerk.accounts.dev/.well-known/jwks.json",
                "production Clerk issuer",
            ),
            (
                "https://identity.example.test",
                "https://other.example.test/.well-known/jwks.json",
                "one Frontend API origin",
            ),
            (
                "https://identity.example.test/path",
                "https://identity.example.test/path/.well-known/jwks.json",
                "one Frontend API origin",
            ),
        ],
    )
    def test_hosted_clerk_rejects_development_or_mismatched_issuer(
        self, issuer: str, jwks_url: str, error: str
    ) -> None:
        with pytest.raises(ValidationError, match=error):
            Settings(
                kavrigo_env="paper-prod",
                auth_provider="jwks",
                auth_issuer=issuer,
                auth_jwks_url=jwks_url,
                auth_session_profile="clerk_v2",
                auth_allowed_parties=["https://app.example.test"],
            )

    def test_local_clerk_development_issuer_is_allowed(self) -> None:
        settings = Settings(
            kavrigo_env="local",
            auth_provider="jwks",
            auth_issuer="https://example.clerk.accounts.dev",
            auth_jwks_url="https://example.clerk.accounts.dev/.well-known/jwks.json",
            auth_session_profile="clerk_v2",
            auth_allowed_parties=["http://localhost:3000"],
        )
        assert settings.auth_session_profile == "clerk_v2"

    def test_hosted_dev_can_use_a_clerk_development_instance(self) -> None:
        settings = Settings(
            kavrigo_env="dev",
            auth_provider="jwks",
            auth_issuer="https://example.clerk.accounts.dev",
            auth_jwks_url="https://example.clerk.accounts.dev/.well-known/jwks.json",
            auth_session_profile="clerk_v2",
            auth_allowed_parties=["https://dev.example.test"],
        )
        assert settings.auth_session_profile == "clerk_v2"

    @pytest.mark.parametrize(
        "party",
        [
            "http://app.example.test",
            "https://app.example.test/path",
            "https://user:pass@app.example.test",
            "https://localhost:3000",
        ],
    )
    def test_paper_prod_rejects_insecure_authorized_parties(self, party: str) -> None:
        with pytest.raises(ValidationError, match="AUTH_ALLOWED_PARTIES"):
            Settings(
                kavrigo_env="paper-prod",
                auth_provider="jwks",
                auth_issuer="https://identity.example.test",
                auth_jwks_url="https://identity.example.test/.well-known/jwks.json",
                auth_session_profile="clerk_v2",
                auth_allowed_parties=[party],
            )

    def test_platform_mode_is_server_authoritative(self, client: TestClient) -> None:
        response = client.get("/v1/platform/mode")
        assert response.status_code == 200
        body = response.json()
        assert body["live_trading_enabled"] is False
        assert body["default_trading_mode"] == "paper"
        assert "Simulated results only" in body["disclosure"]
        assert "synthetic or testnet evidence" in body["disclosure"]


class TestProbes:
    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readyz_reports_unconfigured_dependencies_honestly(self, client: TestClient) -> None:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["checks"]["postgres"] == "not_configured"
        assert response.json()["checks"]["schema"] == "not_configured"

    def test_readyz_does_not_call_configured_services_healthy(self, settings: Settings) -> None:
        configured = settings.model_copy(
            update={
                "clickhouse_url": "http://clickhouse.test:8123",
                "redpanda_bootstrap_servers": "redpanda.test:9092",
                "temporal_address": "temporal.test:7233",
                "valkey_url": "redis://valkey.test:6379",
            }
        )
        response = TestClient(create_app(configured)).get("/readyz")
        assert response.status_code == 503
        for service in ("clickhouse", "redpanda", "temporal", "valkey"):
            assert response.json()["checks"][service] == "configured_unverified"

    @pytest.mark.parametrize("available", [True, False])
    def test_readyz_http_status_tracks_postgres(self, settings: Settings, available: bool) -> None:
        database = SimpleNamespace(
            ping=AsyncMock(return_value=available),
            schema_status=AsyncMock(return_value="ok"),
            dispose=AsyncMock(),
        )
        response = TestClient(create_app(settings, database=database)).get("/readyz")
        assert response.status_code == (200 if available else 503)
        assert response.json()["status"] == ("ready" if available else "degraded")
        assert response.json()["checks"]["postgres"] == ("ok" if available else "unavailable")
        assert response.json()["checks"]["schema"] == ("ok" if available else "unavailable")
        if available:
            database.schema_status.assert_awaited_once()
        else:
            database.schema_status.assert_not_awaited()

    @pytest.mark.parametrize("schema_state", ["mismatch", "unavailable"])
    def test_readyz_rejects_a_database_without_usable_schema(
        self, settings: Settings, schema_state: str
    ) -> None:
        database = SimpleNamespace(
            ping=AsyncMock(return_value=True),
            schema_status=AsyncMock(return_value=schema_state),
            dispose=AsyncMock(),
        )
        response = TestClient(create_app(settings, database=database)).get("/readyz")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["checks"]["postgres"] == "ok"
        assert response.json()["checks"]["schema"] == schema_state

    def test_expected_schema_revision_is_the_migration_head(self) -> None:
        configuration = Config()
        migration_dir = Path(__file__).resolve().parents[1] / "migrations"
        configuration.set_main_option("script_location", str(migration_dir))
        assert ScriptDirectory.from_config(configuration).get_heads() == [EXPECTED_SCHEMA_REVISION]

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
        assert "503" in schema["paths"]["/readyz"]["get"]["responses"]

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
                auth_session_profile="clerk_v2",
                auth_allowed_parties=["https://app.example.test"],
            )
        )
        assert app.docs_url is None
