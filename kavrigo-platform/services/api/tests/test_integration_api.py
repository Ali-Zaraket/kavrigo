"""End-to-end control-plane API tests against a real database.

Covers the properties that only appear when routing, authorization, RLS and versioning run
together: a non-member cannot discover a workspace, a viewer cannot write, a retry does not
create a second agent, and editing an agent appends a version rather than rewriting one.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from kavrigo_api.app import create_app
from kavrigo_api.auth.identity import DevIdentityProvider
from kavrigo_api.auth.principal import Role
from kavrigo_api.db.session import Database
from kavrigo_api.settings import Settings

APP_DSN = os.getenv(
    "TEST_POSTGRES_DSN",
    "postgresql+asyncpg://kavrigo_app:kavrigo_local_dev@localhost:55432/kavrigo_test",
)

pytestmark = pytest.mark.integration


@pytest.fixture
def client(clean_database: None) -> Iterator[TestClient]:
    """A client whose database pool lives in the app's own event loop.

    ``TestClient`` runs the ASGI app in a portal thread with its own loop. An engine whose
    connections were opened in the pytest loop cannot be closed from that one, so the pool is
    created here and disposed by the app's lifespan, inside the loop that used it.
    """
    database = Database(APP_DSN)
    app = create_app(
        Settings(kavrigo_env="local", auth_provider="dev", log_format="console"),
        database=database,
        identity_provider=DevIdentityProvider(),
    )
    with TestClient(app) as test_client:
        yield test_client


def run_sql(
    statement: str,
    params: dict[str, Any] | None = None,
    *,
    workspace_id: str | None = None,
) -> list[Any]:
    """Execute one statement on a throwaway connection, outside the app's loop.

    Used by tests that need to observe or manipulate state the API does not expose. A fresh
    engine per call keeps this independent of the app's pool and the loop that owns it.
    Pass ``workspace_id`` to scope the transaction, exactly as the application does.
    """

    async def _run() -> list[Any]:
        engine = create_async_engine(APP_DSN)
        try:
            async with engine.begin() as conn:
                if workspace_id is not None:
                    await conn.execute(
                        text("SELECT set_config('kavrigo.workspace_id', :ws, true)"),
                        {"ws": workspace_id},
                    )
                result = await conn.execute(text(statement), params or {})
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _auth(subject: str, *, mfa: bool = False) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:{subject}{':mfa' if mfa else ''}"}


def _spec(name: str = "btc-paper-baseline") -> dict[str, Any]:
    return {
        "name": name,
        "universe": {"instruments": [{"base": "BTC", "quote": "USDT", "venue": "BINANCE"}]},
        "schedule": {"decision_interval_seconds": 900},
        "data_packs": ["market_microstructure", "price_technical"],
        "model_policy": {"max_cost_per_decision_usd": "0.10"},
        "risk_policy_ref": f"rp_{0:032x}",
        "execution_policy_ref": f"ep_{0:032x}",
    }


def _create_workspace(client: TestClient, subject: str, slug: str) -> str:
    response = client.post(
        "/v1/workspaces",
        json={"name": slug.title(), "slug": slug},
        headers=_auth(subject),
    )
    assert response.status_code == 201, response.text
    return response.json()["workspace_id"]


class TestAuthentication:
    def test_an_unauthenticated_request_is_rejected(self, client: TestClient) -> None:
        response = client.get("/v1/me")
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"

    def test_an_invalid_token_is_rejected_without_detail(self, client: TestClient) -> None:
        response = client.get("/v1/me", headers={"Authorization": "Bearer garbage"})
        assert response.status_code == 401
        body = response.json()
        assert body["code"] == "unauthenticated"
        assert "garbage" not in response.text

    def test_first_sight_of_a_subject_creates_a_local_user(self, client: TestClient) -> None:
        response = client.get("/v1/me", headers=_auth("newcomer"))
        assert response.status_code == 200
        assert response.json()["user_id"].startswith("usr_")
        assert response.json()["workspaces"] == []

    def test_the_same_subject_maps_to_one_stable_user(self, client: TestClient) -> None:
        first = client.get("/v1/me", headers=_auth("stable")).json()["user_id"]
        second = client.get("/v1/me", headers=_auth("stable")).json()["user_id"]
        assert first == second


class TestWorkspaces:
    def test_the_creator_becomes_the_owner(self, client: TestClient) -> None:
        workspace_id = _create_workspace(client, "alice", "alice-team")
        me = client.get("/v1/me", headers=_auth("alice")).json()
        assert me["workspaces"][0]["workspace_id"] == workspace_id
        assert me["workspaces"][0]["role"] == Role.OWNER.value

    def test_duplicate_slugs_are_rejected(self, client: TestClient) -> None:
        _create_workspace(client, "alice", "shared-slug")
        response = client.post(
            "/v1/workspaces",
            json={"name": "Other", "slug": "shared-slug"},
            headers=_auth("bob"),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "conflict"

    def test_a_non_member_cannot_discover_a_workspace(self, client: TestClient) -> None:
        """404 rather than 403: confirming existence would let an attacker enumerate tenants."""
        workspace_id = _create_workspace(client, "alice", "private-team")
        response = client.get(f"/v1/workspaces/{workspace_id}", headers=_auth("mallory"))
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_workspaces_are_listed_per_user(self, client: TestClient) -> None:
        _create_workspace(client, "alice", "alice-only")
        assert client.get("/v1/workspaces", headers=_auth("bob")).json() == []


class TestAgentLifecycle:
    def test_creating_an_agent_creates_version_one(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "agents-team")
        response = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "btc-baseline", "description": "Baseline", "spec": _spec()},
            headers=_auth("alice"),
        )
        assert response.status_code == 201, response.text
        agent = response.json()
        assert agent["current_version"] == 1

        versions = client.get(
            f"/v1/workspaces/{ws}/agents/{agent['agent_id']}/versions", headers=_auth("alice")
        ).json()
        assert [v["version"] for v in versions["items"]] == [1]
        assert versions["items"][0]["spec_hash"].startswith("sha256:")

    def test_editing_appends_a_version_and_leaves_the_previous_one_intact(
        self, client: TestClient
    ) -> None:
        """``MASTER_BUILD_SPEC.md`` §3: runs reference immutable versions."""
        ws = _create_workspace(client, "alice", "versioning-team")
        agent_id = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "evolving", "spec": _spec()},
            headers=_auth("alice"),
        ).json()["agent_id"]

        v1 = client.get(
            f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1", headers=_auth("alice")
        ).json()

        changed = _spec()
        changed["schedule"]["decision_interval_seconds"] = 3600
        response = client.post(
            f"/v1/workspaces/{ws}/agents/{agent_id}/versions",
            json={"spec": changed, "change_summary": "Slower cadence."},
            headers=_auth("alice"),
        )
        assert response.status_code == 201, response.text
        v2 = response.json()

        assert v2["version"] == 2
        assert v2["spec_hash"] != v1["spec_hash"]

        # Version 1 is byte-for-byte what it was.
        v1_again = client.get(
            f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1", headers=_auth("alice")
        ).json()
        assert v1_again == v1

    def test_there_is_no_endpoint_that_mutates_a_version(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "no-mutation-team")
        agent_id = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "fixed", "spec": _spec()},
            headers=_auth("alice"),
        ).json()["agent_id"]

        path = f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1"
        for method in (client.put, client.patch, client.delete):
            assert method(path, headers=_auth("alice")).status_code == 405

    def test_an_invalid_spec_is_rejected_before_anything_is_written(
        self, client: TestClient
    ) -> None:
        ws = _create_workspace(client, "alice", "validation-team")
        bad = _spec()
        bad["analysis"] = {"allow_abstain": False}
        response = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "always-trades", "spec": bad},
            headers=_auth("alice"),
        )
        assert response.status_code == 422
        assert (
            client.get(f"/v1/workspaces/{ws}/agents", headers=_auth("alice")).json()["items"] == []
        )

    def test_a_live_mode_spec_is_refused(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "live-gate-team")
        live = _spec()
        live["mode"] = "live"
        response = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "live-agent", "spec": live},
            headers=_auth("alice"),
        )
        assert response.status_code == 422

    def test_duplicate_agent_names_are_rejected_within_a_workspace(
        self, client: TestClient
    ) -> None:
        ws = _create_workspace(client, "alice", "dupe-team")
        payload = {"name": "same-name", "spec": _spec()}
        assert (
            client.post(
                f"/v1/workspaces/{ws}/agents", json=payload, headers=_auth("alice")
            ).status_code
            == 201
        )
        response = client.post(f"/v1/workspaces/{ws}/agents", json=payload, headers=_auth("alice"))
        assert response.status_code == 409

    def test_archiving_hides_an_agent_without_destroying_its_history(
        self, client: TestClient
    ) -> None:
        ws = _create_workspace(client, "alice", "archive-team")
        agent_id = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "retired", "spec": _spec()},
            headers=_auth("alice"),
        ).json()["agent_id"]

        assert (
            client.delete(
                f"/v1/workspaces/{ws}/agents/{agent_id}?reason=superseded",
                headers=_auth("alice"),
            ).status_code
            == 204
        )
        assert (
            client.get(f"/v1/workspaces/{ws}/agents", headers=_auth("alice")).json()["items"] == []
        )
        # The versions remain readable, which is the point of archiving rather than deleting.
        assert (
            client.get(
                f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1", headers=_auth("alice")
            ).status_code
            == 200
        )


class TestTenantIsolationThroughTheApi:
    def test_one_workspaces_agents_are_invisible_to_another(self, client: TestClient) -> None:
        ws_a = _create_workspace(client, "alice", "iso-alpha")
        ws_b = _create_workspace(client, "bob", "iso-bravo")
        client.post(
            f"/v1/workspaces/{ws_a}/agents",
            json={"name": "alpha-secret", "spec": _spec()},
            headers=_auth("alice"),
        )

        assert (
            client.get(f"/v1/workspaces/{ws_b}/agents", headers=_auth("bob")).json()["items"] == []
        )
        # And alice's workspace is not even addressable by bob.
        assert client.get(f"/v1/workspaces/{ws_a}/agents", headers=_auth("bob")).status_code == 404

    def test_a_stranger_cannot_read_an_agent_by_id(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "iso-charlie")
        agent_id = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "confidential", "spec": _spec()},
            headers=_auth("alice"),
        ).json()["agent_id"]

        response = client.get(f"/v1/workspaces/{ws}/agents/{agent_id}", headers=_auth("mallory"))
        assert response.status_code == 404


def _demote(workspace_id: str, subject: str, role: Role) -> None:
    run_sql(
        "UPDATE kavrigo.memberships SET role = :role "
        "WHERE workspace_id = :ws AND user_id = "
        "(SELECT user_id FROM kavrigo.users WHERE external_id = :ext)",
        {"role": role.value, "ws": workspace_id, "ext": subject},
        workspace_id=workspace_id,
    )


class TestRoleEnforcement:
    def test_a_viewer_cannot_create_an_agent(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "rbac-team")
        _demote(ws, "alice", Role.VIEWER)

        response = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "not-allowed", "spec": _spec()},
            headers=_auth("alice"),
        )
        assert response.status_code == 403
        body = response.json()
        assert body["code"] == "forbidden"
        assert body["details"]["role"] == "viewer"
        # A role denial, not an MFA denial: the client must not prompt to re-authenticate.
        assert body["details"].get("reason") != "mfa_required"

    def test_a_viewer_can_still_read(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "rbac-read-team")
        client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "readable", "spec": _spec()},
            headers=_auth("alice"),
        )
        _demote(ws, "alice", Role.VIEWER)

        response = client.get(f"/v1/workspaces/{ws}/agents", headers=_auth("alice"))
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1


class TestIdempotency:
    def test_a_retried_create_returns_the_first_result(self, client: TestClient) -> None:
        """``AGENTS.md`` domain rule 7. A timeout-and-retry must not create two agents."""
        ws = _create_workspace(client, "alice", "idem-team")
        payload = {"name": "retried", "spec": _spec()}
        headers = {**_auth("alice"), "Idempotency-Key": "client-key-0001"}

        first = client.post(f"/v1/workspaces/{ws}/agents", json=payload, headers=headers)
        second = client.post(f"/v1/workspaces/{ws}/agents", json=payload, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["agent_id"] == second.json()["agent_id"]
        assert (
            len(client.get(f"/v1/workspaces/{ws}/agents", headers=_auth("alice")).json()["items"])
            == 1
        )

    def test_reusing_a_key_with_a_different_body_is_rejected(self, client: TestClient) -> None:
        """Returning the earlier response here would be worse than no idempotency at all."""
        ws = _create_workspace(client, "alice", "idem-conflict-team")
        headers = {**_auth("alice"), "Idempotency-Key": "client-key-0002"}

        client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "first-agent", "spec": _spec()},
            headers=headers,
        )
        response = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "different-agent", "spec": _spec()},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["code"] == "idempotency_key_reused"

    def test_without_a_key_a_retry_conflicts_on_the_unique_name(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "no-key-team")
        payload = {"name": "unkeyed", "spec": _spec()}
        assert (
            client.post(
                f"/v1/workspaces/{ws}/agents", json=payload, headers=_auth("alice")
            ).status_code
            == 201
        )
        assert (
            client.post(
                f"/v1/workspaces/{ws}/agents", json=payload, headers=_auth("alice")
            ).status_code
            == 409
        )


class TestPagination:
    def test_cursor_pagination_covers_every_row_exactly_once(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "paging-team")
        for i in range(7):
            client.post(
                f"/v1/workspaces/{ws}/agents",
                json={"name": f"agent-{i}", "spec": _spec()},
                headers=_auth("alice"),
            )

        seen: list[str] = []
        cursor: str | None = None
        for _ in range(10):
            url = f"/v1/workspaces/{ws}/agents?limit=3"
            if cursor:
                url += f"&cursor={cursor}"
            page = client.get(url, headers=_auth("alice")).json()
            seen.extend(a["agent_id"] for a in page["items"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]

        assert len(seen) == 7
        assert len(set(seen)) == 7

    def test_a_malformed_cursor_is_a_client_error(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "bad-cursor-team")
        response = client.get(
            f"/v1/workspaces/{ws}/agents?cursor=!!!not-base64!!!", headers=_auth("alice")
        )
        assert response.status_code == 400
        assert response.json()["code"] == "validation_failed"


class TestAuditTrail:
    def test_creating_a_version_records_an_audit_event(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "audit-team")
        client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "audited", "spec": _spec()},
            headers=_auth("alice"),
        )

        events = run_sql(
            "SELECT action, actor, payload FROM kavrigo.audit_events ORDER BY created_at",
            workspace_id=ws,
        )
        assert [e.action for e in events] == ["agent_version_created"]
        assert events[0].payload["version"] == 1
        assert events[0].actor.startswith("usr_")


class TestProductInspection:
    @pytest.mark.parametrize("suffix", ["runs", "paper/accounts", "audit"])
    def test_tenant_boundary_and_no_store(self, client: TestClient, suffix: str) -> None:
        ws = _create_workspace(client, "alice", "inspection-alice")
        path = f"/v1/workspaces/{ws}/{suffix}"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=_auth("bob")).status_code == 404
        response = client.get(path, headers=_auth("alice"))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert "items" in response.json()

    def test_runs_paginate_and_do_not_expose_frozen_inputs(self, client: TestClient) -> None:
        import json

        ws = _create_workspace(client, "alice", "inspection-runs")
        other = _create_workspace(client, "bob", "inspection-other")
        for tenant, ids in ((ws, (1, 2)), (other, (3,))):
            for number in ids:
                run_sql(
                    """INSERT INTO kavrigo.engine_runs
                    (workspace_id,run_id,definition,input_hash,created_at)
                    VALUES (:ws,:run,:definition,:hash,clock_timestamp())""",
                    {
                        "ws": tenant,
                        "run": f"run_{number:032x}",
                        "hash": "sha256:" + "ab" * 32,
                        "definition": json.dumps(
                            {
                                "workspace_id": tenant,
                                "job": {"kind": "health", "internal": "private-input"},
                            }
                        ),
                    },
                    workspace_id=tenant,
                )
        path = f"/v1/workspaces/{ws}/runs"
        first = client.get(path, params={"limit": 1}, headers=_auth("alice"))
        assert first.status_code == 200
        assert first.json()["has_more"]
        assert "private-input" not in first.text
        second = client.get(
            path, params={"limit": 1, "cursor": first.json()["next_cursor"]}, headers=_auth("alice")
        )
        assert second.json()["items"][0]["run_id"] == f"run_{2:032x}"
        assert not second.json()["has_more"]
        assert client.get(f"{path}/run_{3:032x}", headers=_auth("alice")).status_code == 404
        detail = client.get(f"{path}/run_{1:032x}", headers=_auth("alice"))
        assert detail.status_code == 200
        assert detail.json()["decisions"] == []
        assert "private-input" not in detail.text
        assert client.post(path, json={}, headers=_auth("alice")).status_code == 405

    def test_corrupt_stage_receipt_is_refused(self, client: TestClient) -> None:
        import json

        ws = _create_workspace(client, "alice", "corrupt-stage")
        run = f"run_{1:032x}"
        run_sql(
            """INSERT INTO kavrigo.engine_runs
            (workspace_id,run_id,definition,input_hash,created_at)
            VALUES (:ws,:run,:definition,:hash,clock_timestamp())""",
            {
                "ws": ws,
                "run": run,
                "hash": "sha256:" + "ab" * 32,
                "definition": json.dumps({"workspace_id": ws, "job": {"kind": "agent"}}),
            },
            workspace_id=ws,
        )
        run_sql(
            """INSERT INTO kavrigo.engine_steps
            (workspace_id,run_id,stage,status,attempt_id,input_hash,output,output_hash,started_at)
            VALUES (:ws,:run,'evaluate','completed','test',:hash,:output,:hash,clock_timestamp())""",
            {
                "ws": ws,
                "run": run,
                "hash": "sha256:" + "ab" * 32,
                "output": json.dumps({"decisions": []}),
            },
            workspace_id=ws,
        )
        response = client.get(f"/v1/workspaces/{ws}/runs/{run}", headers=_auth("alice"))
        assert response.status_code == 500
        assert response.json()["message"] == "Run receipt is inconsistent."

    def test_viewer_can_inspect_but_cannot_read_audit(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "inspection-role")
        user = client.get("/v1/me", headers=_auth("viewer")).json()["user_id"]
        run_sql(
            """INSERT INTO kavrigo.memberships (workspace_id,user_id,role)
            VALUES (:ws,:user,'viewer')""",
            {"ws": ws, "user": user},
            workspace_id=ws,
        )
        root = f"/v1/workspaces/{ws}"
        assert client.get(root + "/runs", headers=_auth("viewer")).status_code == 200
        assert client.get(root + "/audit", headers=_auth("viewer")).status_code == 403

    def test_paper_projection_preserves_exact_amounts(self, client: TestClient) -> None:
        import json

        ws = _create_workspace(client, "alice", "inspection-money")
        amount = "9007199254740993.123456789012"
        cash = {"amount": amount, "currency": "USD"}
        zero = {"amount": "0", "currency": "USD"}
        stamp = "2026-09-10T00:00:00Z"
        portfolio = {
            "workspace_id": ws,
            "mode": "paper",
            "as_of": stamp,
            "base_currency": "USD",
            "cash": cash,
            "equity": cash,
            "peak_equity": cash,
            "reserved_cash": zero,
            "realized_pnl_today": zero,
            "unrealized_pnl": zero,
            "gross_exposure": zero,
            "net_exposure": zero,
        }
        digest = "sha256:" + "ab" * 32
        receipt = {
            "sequence": 0,
            "state_hash": digest,
            "committed_at": stamp,
            "state": {
                "account_id": "paper-test",
                "portfolio": portfolio,
                "fees_paid": zero,
                "orders": [{"internal": "never-exposed"}],
            },
        }
        run_sql(
            """INSERT INTO kavrigo.engine_accounts
            (workspace_id,account_id,definition,definition_hash,head_sequence,head_hash,head_receipt,bytes_used)
            VALUES (:ws,'paper-test','{}',:hash,0,:hash,:receipt,0)""",
            {"ws": ws, "hash": digest, "receipt": json.dumps(receipt)},
            workspace_id=ws,
        )
        response = client.get(f"/v1/workspaces/{ws}/paper/accounts", headers=_auth("alice"))
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["portfolio"]["cash"]["amount"] == amount
        assert "never-exposed" not in response.text
