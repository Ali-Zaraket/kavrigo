"""End-to-end control-plane API tests against a real database.

Covers the properties that only appear when routing, authorization, RLS and versioning run
together: a non-member cannot discover a workspace, a viewer cannot write, a retry does not
create a second agent, and editing an agent appends a version rather than rewriting one.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from kavrigo_api.app import create_app
from kavrigo_api.auth.identity import DevIdentityProvider
from kavrigo_api.auth.principal import Role
from kavrigo_api.db.session import Database
from kavrigo_api.routers import rehearsals as rehearsal_router
from kavrigo_api.services.provider_entitlements import (
    DataEntitlementEventDocument,
    entitlement_event_hash,
)
from kavrigo_api.settings import Settings
from kavrigo_domain import (
    BookTicker,
    DataPack,
    InstrumentId,
    MarketSnapshot,
    MarketTrade,
    Price,
    Quantity,
    content_hash,
)
from kavrigo_runtime.validation import snapshot_hash
from kavrigo_workflows.contracts import AgentJob, RunDefinition

APP_DSN = os.getenv(
    "TEST_POSTGRES_DSN",
    "postgresql+asyncpg://kavrigo_app:kavrigo_local_dev@localhost:55432/kavrigo_test",
)
OWNER_DSN = os.getenv(
    "TEST_POSTGRES_OWNER_DSN",
    "postgresql+asyncpg://kavrigo:kavrigo_local_dev@localhost:55432/kavrigo_test",
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
        Settings(
            kavrigo_env="local", auth_provider="dev", log_format="console", postgres_dsn=APP_DSN
        ),
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
    owner: bool = False,
) -> list[Any]:
    """Execute one statement on a throwaway connection, outside the app's loop.

    Used by tests that need to observe or manipulate state the API does not expose. A fresh
    engine per call keeps this independent of the app's pool and the loop that owns it.
    Pass ``workspace_id`` to scope the transaction, exactly as the application does.
    """

    async def _run() -> list[Any]:
        engine = create_async_engine(OWNER_DSN if owner else APP_DSN)
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


def _record_entitlement(document: DataEntitlementEventDocument) -> str:
    event_hash = entitlement_event_hash(document)
    values = document.model_dump(mode="python")
    run_sql(
        """INSERT INTO kavrigo.data_entitlement_events
        (event_id,workspace_id,scope,action,provider,license_ref,rights,data_packs,
         contract_hash,effective_at,expires_at,reason,event_hash,recorded_by)
        VALUES (:event_id,:workspace_id,:scope,:action,:provider,:license_ref,:rights,:data_packs,
                :contract_hash,:effective_at,:expires_at,:reason,:event_hash,:recorded_by)""",
        {
            **values,
            "rights": list(document.rights),
            "data_packs": [item.value for item in document.data_packs],
            "event_hash": event_hash,
        },
        owner=True,
    )
    return event_hash


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


class TestLocalPaperRehearsal:
    def test_launch_is_tenant_scoped_idempotent_and_explicitly_synthetic(
        self, client: TestClient
    ) -> None:
        ws = _create_workspace(client, "alice", "rehearsal-owner")
        spec = _spec("btc-rehearsal")
        spec["universe"] = {"instruments": [{"base": "BTC", "quote": "USD", "venue": "SIM"}]}
        spec["data_packs"] = ["price_technical"]
        created = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "btc-rehearsal", "spec": spec},
            headers={**_auth("alice"), "Idempotency-Key": "create-rehearsal-agent"},
        )
        assert created.status_code == 201, created.text
        agent_id = created.json()["agent_id"]
        route = f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1/rehearsals"
        headers = {**_auth("alice"), "Idempotency-Key": str(uuid4())}
        launched = client.post(route, headers=headers)
        assert launched.status_code == 202, launched.text
        payload = launched.json()
        assert payload["dispatch_state"] == "queued"
        assert payload["input_kind"] == "synthetic_rehearsal"
        assert payload["execution_enabled"] is False
        assert payload["replayed"] is False
        again = client.post(route, headers=headers)
        assert again.status_code == 202, again.text
        assert again.json()["run_id"] == payload["run_id"]
        assert again.json()["input_hash"] == payload["input_hash"]
        assert again.json()["replayed"] is True
        stored = client.get(f"/v1/workspaces/{ws}/runs/{payload['run_id']}", headers=_auth("alice"))
        assert stored.status_code == 200, stored.text
        assert stored.json()["kind"] == "agent"
        assert stored.json()["input_kind"] == "synthetic_rehearsal"
        assert all(item["provider"] == "kavrigo-synthetic" for item in stored.json()["evidence"])
        listed = client.get(f"/v1/workspaces/{ws}/runs", headers=_auth("alice"))
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"][0]["input_kind"] == "synthetic_rehearsal"
        next_version = client.post(
            f"/v1/workspaces/{ws}/agents/{agent_id}/versions",
            json={"spec": spec, "change_summary": "Same spec, separate version"},
            headers=_auth("alice"),
        )
        assert next_version.status_code == 201, next_version.text
        conflict = client.post(route.replace("/versions/1/", "/versions/2/"), headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_key_reused"
        assert client.post(route, headers=_auth("alice")).status_code == 400
        assert (
            client.post(route, headers={**_auth("mallory"), "Idempotency-Key": "x"}).status_code
            == 404
        )

    def test_testnet_source_is_frozen_and_labeled(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        observed = datetime.now(UTC)
        instrument = InstrumentId.parse("BTC-USDT.BINANCE_TESTNET")

        async def sample(bases: tuple[str, ...]) -> tuple[MarketTrade | BookTicker, ...]:
            assert bases == ("BTC",)
            return (
                MarketTrade(
                    instrument_id=instrument,
                    price=Price(value=Decimal("100"), base="BTC", quote="USDT"),
                    quantity=Quantity(value=Decimal("0.1"), asset="BTC"),
                    venue_time=observed,
                    received_at=observed,
                ),
                BookTicker(
                    instrument_id=instrument,
                    bid_price=Price(value=Decimal("99"), base="BTC", quote="USDT"),
                    bid_size=Quantity(value=Decimal("1"), asset="BTC"),
                    ask_price=Price(value=Decimal("101"), base="BTC", quote="USDT"),
                    ask_size=Quantity(value=Decimal("1"), asset="BTC"),
                    received_at=observed,
                ),
            )

        monkeypatch.setattr(rehearsal_router, "collect_testnet_sample", sample)
        ws = _create_workspace(client, "alice", "testnet-rehearsal-owner")
        spec = _spec("btc-testnet-rehearsal")
        spec["universe"] = {"instruments": [{"base": "BTC", "quote": "USD", "venue": "SIM"}]}
        spec["data_packs"] = ["price_technical"]
        created = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "btc-testnet-rehearsal", "spec": spec},
            headers={**_auth("alice"), "Idempotency-Key": "create-testnet-agent"},
        )
        agent_id = created.json()["agent_id"]
        route = f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1/rehearsals"

        launched = client.post(
            route,
            params={"source": "binance_testnet"},
            headers={**_auth("alice"), "Idempotency-Key": str(uuid4())},
        )

        assert launched.status_code == 202, launched.text
        payload = launched.json()
        assert payload["input_kind"] == "testnet_rehearsal"
        assert payload["execution_enabled"] is False
        stored = client.get(f"/v1/workspaces/{ws}/runs/{payload['run_id']}", headers=_auth("alice"))
        assert stored.json()["input_kind"] == "testnet_rehearsal"
        assert all(item["provider"] == "binance-spot-testnet" for item in stored.json()["evidence"])


class TestPaperPolicyCandidates:
    @staticmethod
    def _body() -> dict[str, Any]:
        return {
            "limits": {
                "max_gross_exposure_pct": "10",
                "max_single_asset_exposure_pct": "5",
                "max_network_exposure_pct": "10",
                "max_open_positions": 1,
                "max_daily_loss_pct": "1",
                "max_drawdown_pct": "2",
                "min_liquidity_usd": "1000000",
                "max_spread_bps": 20,
                "min_order_notional_usd": "10",
                "max_order_notional_usd": "100",
            },
            "freshness": {
                "required_families": ["trades", "book"],
                "max_age_ms": {"trades": 5000, "book": 2000},
            },
            "execution": {
                "fee_bps": "10",
                "slippage_bps": "10",
                "notional_increment_usd": "0.01",
                "max_snapshot_age_ms": 5000,
                "max_portfolio_age_ms": 5000,
                "max_reconciliation_age_ms": 5000,
                "max_market_age_ms": 5000,
                "max_approval_age_ms": 5000,
            },
            "reason": "Conservative paper candidate for review",
        }

    def test_create_requires_mfa_and_remains_unapproved(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "policy-owner")
        route = f"/v1/workspaces/{ws}/paper/policy-bundles"
        body = self._body()
        headers = {**_auth("alice"), "Idempotency-Key": "candidate-one"}
        refused = client.post(route, json=body, headers=headers)
        assert refused.status_code == 403
        assert "multi-factor" in refused.json()["message"].lower()

        headers = {**_auth("alice", mfa=True), "Idempotency-Key": "candidate-one"}
        created = client.post(route, json=body, headers=headers)
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["approval_status"] == "unapproved"
        assert payload["execution_enabled"] is False
        assert payload["risk"]["risk_policy_id"].startswith("rp_")
        assert payload["execution"]["execution_policy_id"].startswith("ep_")
        assert payload["risk"]["content_hash"] == payload["risk_hash"]

        repeated = client.post(route, json=body, headers=headers)
        assert repeated.status_code == 201
        assert repeated.json() == payload
        changed = {**body, "reason": "Another candidate must use another key"}
        conflict = client.post(route, json=changed, headers=headers)
        assert conflict.status_code == 409

        listed = client.get(route, headers=_auth("alice"))
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 1
        detail = client.get(f"{route}/{payload['bundle_id']}", headers=_auth("alice"))
        assert detail.status_code == 200
        assert detail.json() == payload
        other = client.get(f"{route}/{payload['bundle_id']}", headers=_auth("bob"))
        assert other.status_code == 404

    def test_untrusted_numbers_and_missing_freshness_fail(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "policy-validation")
        route = f"/v1/workspaces/{ws}/paper/policy-bundles"
        headers = {**_auth("alice", mfa=True), "Idempotency-Key": "invalid-candidate"}
        body = self._body()
        body["limits"]["max_gross_exposure_pct"] = 0.1
        assert client.post(route, json=body, headers=headers).status_code == 422
        body = self._body()
        body["freshness"]["required_families"] = ["news"]
        assert client.post(route, json=body, headers=headers).status_code == 422

    def test_second_person_review_is_immutable_and_never_activates(
        self, client: TestClient
    ) -> None:
        ws = _create_workspace(client, "alice", "policy-review")
        route = f"/v1/workspaces/{ws}/paper/policy-bundles"
        candidate = client.post(
            route,
            json=self._body(),
            headers={**_auth("alice", mfa=True), "Idempotency-Key": "review-candidate"},
        ).json()
        review_route = f"{route}/{candidate['bundle_id']}/review"
        body = {
            "recommendation": "advance_to_evaluation",
            "reason": "Independent review supports further paper evaluation only.",
            "risk_hash": candidate["risk_hash"],
            "execution_hash": candidate["execution_hash"],
        }
        owner_headers = {**_auth("alice", mfa=True), "Idempotency-Key": "review-one"}
        assert client.post(review_route, json=body, headers=owner_headers).status_code == 403

        reviewer = client.get("/v1/me", headers=_auth("bob")).json()["user_id"]
        run_sql(
            "INSERT INTO kavrigo.memberships (workspace_id,user_id,role) "
            "VALUES (:ws,:user,'admin')",
            {"ws": ws, "user": reviewer},
            workspace_id=ws,
        )
        assert (
            client.post(
                review_route,
                json=body,
                headers={**_auth("bob"), "Idempotency-Key": "review-one"},
            ).status_code
            == 403
        )
        reviewer_headers = {**_auth("bob", mfa=True), "Idempotency-Key": "review-one"}
        wrong_hash = {**body, "risk_hash": "sha256:" + "0" * 64}
        assert (
            client.post(review_route, json=wrong_hash, headers=reviewer_headers).status_code == 409
        )
        created = client.post(review_route, json=body, headers=reviewer_headers)
        assert created.status_code == 201, created.text
        review = created.json()
        assert review["recommendation"] == "advance_to_evaluation"
        assert review["risk_hash"] == candidate["risk_hash"]
        assert review["execution_hash"] == candidate["execution_hash"]
        assert review["approval_status"] == "reviewed"
        assert review["execution_enabled"] is False
        assert client.post(review_route, json=body, headers=reviewer_headers).json() == review
        changed = {**body, "recommendation": "changes_requested"}
        assert client.post(review_route, json=changed, headers=reviewer_headers).status_code == 409
        assert client.get(review_route, headers=_auth("alice")).json() == review
        assert client.get(review_route, headers=_auth("mallory")).status_code == 404
        assert (
            client.get(f"{route}/{candidate['bundle_id']}", headers=_auth("alice")).json()[
                "approval_status"
            ]
            == "reviewed"
        )
        assert (
            run_sql(
                "SELECT count(*) FROM kavrigo.paper_policy_reviews WHERE bundle_id = :bundle",
                {"bundle": candidate["bundle_id"]},
                workspace_id=ws,
            )[0][0]
            == 1
        )

    def test_reviewer_can_approve_exact_hashes_without_activating(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "policy-approval")
        route = f"/v1/workspaces/{ws}/paper/policy-bundles"
        candidate = client.post(
            route,
            json=self._body(),
            headers={**_auth("alice", mfa=True), "Idempotency-Key": "approval-candidate"},
        ).json()
        reviewer = client.get("/v1/me", headers=_auth("bob")).json()["user_id"]
        run_sql(
            "INSERT INTO kavrigo.memberships (workspace_id,user_id,role) "
            "VALUES (:ws,:user,'admin')",
            {"ws": ws, "user": reviewer},
            workspace_id=ws,
        )
        review = client.post(
            f"{route}/{candidate['bundle_id']}/review",
            json={
                "recommendation": "advance_to_evaluation",
                "reason": "Independent review supports explicit approval for paper evaluation.",
                "risk_hash": candidate["risk_hash"],
                "execution_hash": candidate["execution_hash"],
            },
            headers={**_auth("bob", mfa=True), "Idempotency-Key": "approval-review"},
        ).json()
        approval_route = f"{route}/{candidate['bundle_id']}/approval"
        body = {
            "review_id": review["review_id"],
            "reason": "Approve these exact limits for later paper activation evaluation.",
            "risk_hash": candidate["risk_hash"],
            "execution_hash": candidate["execution_hash"],
        }

        no_mfa = client.post(
            approval_route,
            json=body,
            headers={**_auth("bob"), "Idempotency-Key": "approval-one"},
        )
        assert no_mfa.status_code == 403
        creator = client.post(
            approval_route,
            json=body,
            headers={**_auth("alice", mfa=True), "Idempotency-Key": "approval-one"},
        )
        assert creator.status_code == 403
        wrong_hash = {**body, "execution_hash": "sha256:" + "0" * 64}
        assert (
            client.post(
                approval_route,
                json=wrong_hash,
                headers={**_auth("bob", mfa=True), "Idempotency-Key": "approval-one"},
            ).status_code
            == 409
        )

        headers = {**_auth("bob", mfa=True), "Idempotency-Key": "approval-one"}
        approved = client.post(approval_route, json=body, headers=headers)
        assert approved.status_code == 201, approved.text
        payload = approved.json()
        assert payload["approval_status"] == "approved"
        assert payload["activation_status"] == "inactive"
        assert payload["execution_enabled"] is False
        assert payload["approved_by"] == reviewer
        assert client.post(approval_route, json=body, headers=headers).json() == payload
        changed = {**body, "reason": "A different approval reason cannot reuse this record."}
        assert client.post(approval_route, json=changed, headers=headers).status_code == 409
        assert client.get(approval_route, headers=_auth("alice")).json() == payload
        assert (
            client.get(f"{route}/{candidate['bundle_id']}", headers=_auth("alice")).json()[
                "approval_status"
            ]
            == "approved"
        )
        assert (
            client.get(f"{route}/{candidate['bundle_id']}/review", headers=_auth("alice")).json()[
                "approval_status"
            ]
            == "approved"
        )
        assert (
            run_sql(
                "SELECT count(*) FROM kavrigo.paper_policy_approvals WHERE bundle_id = :bundle",
                {"bundle": candidate["bundle_id"]},
                workspace_id=ws,
            )[0][0]
            == 1
        )

    def test_changes_requested_review_cannot_be_approved(self, client: TestClient) -> None:
        ws = _create_workspace(client, "alice", "policy-changes-requested")
        route = f"/v1/workspaces/{ws}/paper/policy-bundles"
        candidate = client.post(
            route,
            json=self._body(),
            headers={**_auth("alice", mfa=True), "Idempotency-Key": "changes-candidate"},
        ).json()
        reviewer = client.get("/v1/me", headers=_auth("bob")).json()["user_id"]
        run_sql(
            "INSERT INTO kavrigo.memberships (workspace_id,user_id,role) "
            "VALUES (:ws,:user,'admin')",
            {"ws": ws, "user": reviewer},
            workspace_id=ws,
        )
        review = client.post(
            f"{route}/{candidate['bundle_id']}/review",
            json={
                "recommendation": "changes_requested",
                "reason": "The maximum order notional needs a stricter evaluation bound.",
                "risk_hash": candidate["risk_hash"],
                "execution_hash": candidate["execution_hash"],
            },
            headers={**_auth("bob", mfa=True), "Idempotency-Key": "changes-review"},
        ).json()
        assert review["approval_status"] == "changes_requested"
        refused = client.post(
            f"{route}/{candidate['bundle_id']}/approval",
            json={
                "review_id": review["review_id"],
                "reason": "This must remain blocked because changes were requested.",
                "risk_hash": candidate["risk_hash"],
                "execution_hash": candidate["execution_hash"],
            },
            headers={**_auth("bob", mfa=True), "Idempotency-Key": "blocked-approval"},
        )
        assert refused.status_code == 409
        assert (
            client.get(f"{route}/{candidate['bundle_id']}", headers=_auth("alice")).json()[
                "approval_status"
            ]
            == "changes_requested"
        )


class TestPaperActivationAssessments:
    def test_synthetic_evaluation_is_recorded_as_blocked_and_inactive(
        self, client: TestClient
    ) -> None:
        ws = _create_workspace(client, "alice", "activation-assessment")
        policy_route = f"/v1/workspaces/{ws}/paper/policy-bundles"
        candidate = client.post(
            policy_route,
            json=TestPaperPolicyCandidates._body(),
            headers={**_auth("alice", mfa=True), "Idempotency-Key": "activation-policy"},
        ).json()
        reviewer = client.get("/v1/me", headers=_auth("bob")).json()["user_id"]
        run_sql(
            "INSERT INTO kavrigo.memberships (workspace_id,user_id,role) "
            "VALUES (:ws,:user,'admin')",
            {"ws": ws, "user": reviewer},
            workspace_id=ws,
        )
        review = client.post(
            f"{policy_route}/{candidate['bundle_id']}/review",
            json={
                "recommendation": "advance_to_evaluation",
                "reason": "Independent review permits evaluation of these exact paper limits.",
                "risk_hash": candidate["risk_hash"],
                "execution_hash": candidate["execution_hash"],
            },
            headers={**_auth("bob", mfa=True), "Idempotency-Key": "activation-review"},
        ).json()
        approval = client.post(
            f"{policy_route}/{candidate['bundle_id']}/approval",
            json={
                "review_id": review["review_id"],
                "reason": "Approve the exact reviewed policies for eligibility assessment.",
                "risk_hash": candidate["risk_hash"],
                "execution_hash": candidate["execution_hash"],
            },
            headers={**_auth("bob", mfa=True), "Idempotency-Key": "activation-approval"},
        ).json()

        spec = _spec("activation-agent")
        spec["universe"] = {"instruments": [{"base": "BTC", "quote": "USD", "venue": "SIM"}]}
        spec["risk_policy_ref"] = candidate["risk"]["risk_policy_id"]
        spec["execution_policy_ref"] = candidate["execution"]["execution_policy_id"]
        created = client.post(
            f"/v1/workspaces/{ws}/agents",
            json={"name": "activation-agent", "spec": spec},
            headers={**_auth("alice"), "Idempotency-Key": "activation-agent"},
        )
        assert created.status_code == 201, created.text
        agent_id = created.json()["agent_id"]
        version = client.get(
            f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1", headers=_auth("alice")
        ).json()
        launched = client.post(
            f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1/rehearsals",
            headers={**_auth("alice"), "Idempotency-Key": "activation-evaluation"},
        )
        assert launched.status_code == 202, launched.text
        run = launched.json()
        route = f"/v1/workspaces/{ws}/agents/{agent_id}/versions/1/paper-activation-assessments"
        body = {
            "bundle_id": candidate["bundle_id"],
            "approval_id": approval["approval_id"],
            "evaluation_run_id": run["run_id"],
            "agent_spec_hash": version["spec_hash"],
            "risk_hash": candidate["risk_hash"],
            "execution_hash": candidate["execution_hash"],
            "evaluation_input_hash": run["input_hash"],
            "reason": "Assess the reviewed version against every paper activation gate.",
        }
        plain_headers = {**_auth("alice"), "Idempotency-Key": "activation-assessment"}
        assert client.post(route, json=body, headers=plain_headers).status_code == 403

        headers = {**_auth("alice", mfa=True), "Idempotency-Key": "activation-assessment"}
        assessed = client.post(route, json=body, headers=headers)
        assert assessed.status_code == 201, assessed.text
        payload = assessed.json()
        assert payload["decision"] == "blocked"
        assert payload["activation_status"] == "inactive"
        assert payload["execution_enabled"] is False
        assert payload["providers"] == ["kavrigo-synthetic"]
        gates = {item["gate"]: item for item in payload["gate_results"]}
        assert gates["policy_approval_integrity"]["passed"] is True
        assert gates["version_policy_binding"]["passed"] is True
        assert gates["evaluation_version_binding"]["passed"] is True
        assert gates["evaluation_completion"]["reason_code"] == "evaluation_run_not_completed"
        assert gates["promotable_evidence"]["reason_code"] == "synthetic_evidence_not_promotable"
        assert gates["provider_entitlement"]["reason_code"] == "provider_scope_not_eligible"
        assert gates["activation_support"]["reason_code"] == "paper_activation_not_implemented"
        assert client.post(route, json=body, headers=headers).json() == payload

        next_version = client.post(
            f"/v1/workspaces/{ws}/agents/{agent_id}/versions",
            json={"spec": spec, "change_summary": "Same policy, separate immutable version."},
            headers=_auth("alice"),
        )
        assert next_version.status_code == 201, next_version.text
        wrong_path = client.post(
            route.replace("/versions/1/", "/versions/2/"), json=body, headers=headers
        )
        assert wrong_path.status_code == 409
        assert wrong_path.json()["code"] == "idempotency_key_reused"

        stored_definition = run_sql(
            "SELECT definition FROM kavrigo.engine_runs WHERE run_id=:run",
            {"run": run["run_id"]},
            workspace_id=ws,
        )[0][0]
        definition_document = json.loads(stored_definition)
        licensed_run_id = "run_" + uuid4().hex
        definition_document["run_id"] = licensed_run_id
        evaluation_document = definition_document["job"]["evaluation"]
        evaluation_document["snapshot"]["quality"]["notes"] = []
        for item in evaluation_document["evidence"]:
            item["provider"] = "licensed-fixture"
            item["license_ref"] = "licensed-fixture-contract-v1"
        snapshot_document = evaluation_document["snapshot"]
        snapshot_document["content_hash"] = "sha256:" + "0" * 64
        snapshot = MarketSnapshot.model_validate(snapshot_document)
        snapshot_document["content_hash"] = snapshot_hash(snapshot)
        licensed_definition = RunDefinition.model_validate(definition_document)
        assert isinstance(licensed_definition.job, AgentJob)
        licensed_input_hash = content_hash(licensed_definition)
        run_sql(
            """INSERT INTO kavrigo.engine_runs
            (workspace_id,run_id,definition,input_hash,status,created_at)
            VALUES (:ws,:run,:definition,:input_hash,'queued',:created_at)""",
            {
                "ws": ws,
                "run": licensed_run_id,
                "definition": licensed_definition.model_dump_json(),
                "input_hash": licensed_input_hash,
                "created_at": licensed_definition.job.evaluation.snapshot.as_of,
            },
            workspace_id=ws,
        )
        evidence_at = licensed_definition.job.evaluation.snapshot.as_of
        effective_at = evidence_at - timedelta(days=1)
        expires_at = datetime.now(UTC) + timedelta(days=30)
        platform_event = DataEntitlementEventDocument(
            event_id="dee_" + uuid4().hex,
            scope="platform",
            action="grant",
            provider="licensed-fixture",
            license_ref="licensed-fixture-contract-v1",
            rights=(
                "agent_decision",
                "application_display",
                "derived_data",
                "historical_storage",
            ),
            data_packs=(DataPack.MARKET_MICROSTRUCTURE, DataPack.PRICE_TECHNICAL),
            contract_hash=content_hash({"fixture_contract": "v1"}),
            effective_at=effective_at,
            expires_at=expires_at,
            reason="Test-only platform rights fixture for activation eligibility.",
            recorded_by="test-compliance-operator",
        )
        workspace_event = DataEntitlementEventDocument(
            event_id="dee_" + uuid4().hex,
            workspace_id=ws,
            scope="workspace",
            action="grant",
            provider="licensed-fixture",
            license_ref="licensed-fixture-contract-v1",
            data_packs=(DataPack.MARKET_MICROSTRUCTURE, DataPack.PRICE_TECHNICAL),
            effective_at=effective_at,
            expires_at=expires_at,
            reason="Test-only workspace data-pack entitlement fixture.",
            recorded_by="test-billing-operator",
        )
        platform_hash = _record_entitlement(platform_event)
        workspace_hash = _record_entitlement(workspace_event)
        licensed_body = {
            **body,
            "evaluation_run_id": licensed_run_id,
            "evaluation_input_hash": licensed_input_hash,
            "reason": "Assess a fixture with exact platform and workspace entitlement records.",
        }
        licensed_response = client.post(
            route,
            json=licensed_body,
            headers={**_auth("alice", mfa=True), "Idempotency-Key": "licensed-assessment"},
        )
        assert licensed_response.status_code == 201, licensed_response.text
        licensed_payload = licensed_response.json()
        licensed_gates = {item["gate"]: item for item in licensed_payload["gate_results"]}
        assert licensed_gates["promotable_evidence"]["passed"] is True
        assert licensed_gates["provider_entitlement"] == {
            "gate": "provider_entitlement",
            "passed": True,
            "reason_code": "provider_entitlement_verified",
        }
        assert licensed_payload["decision"] == "blocked"
        assert licensed_payload["execution_enabled"] is False
        assert {
            (item["scope"], item["event_hash"])
            for item in licensed_payload["entitlement_event_refs"]
        } == {("platform", platform_hash), ("workspace", workspace_hash)}

        changed = {**body, "reason": "A changed request cannot reuse this assessment key."}
        assert client.post(route, json=changed, headers=headers).status_code == 409
        detail = client.get(f"{route}/{payload['assessment_id']}", headers=_auth("alice"))
        assert detail.status_code == 200
        assert detail.json() == payload
        assert (
            client.get(f"{route}/{payload['assessment_id']}", headers=_auth("mallory")).status_code
            == 404
        )
        assert (
            run_sql(
                "SELECT count(*) FROM kavrigo.paper_activation_assessments "
                "WHERE assessment_id=:assessment",
                {"assessment": payload["assessment_id"]},
                workspace_id=ws,
            )[0][0]
            == 1
        )
