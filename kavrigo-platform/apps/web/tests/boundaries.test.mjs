import { test } from "node:test";
import assert from "node:assert/strict";
import {
  allowedRoute,
  bodylessPostRoute,
  controlPlaneOrigin,
} from "../src/lib/proxy-policy.ts";
import { decimal, money } from "../src/lib/client.ts";

const ws = `v1/workspaces/ws_${"1".repeat(32)}`;
test("proxy only exposes the allowlisted control plane", () => {
  for (const suffix of ["runs", "paper/accounts", "audit", "agents"])
    assert.ok(allowedRoute(`${ws}/${suffix}`, "GET"));
  assert.ok(allowedRoute(`${ws}/agents`, "POST"));
  assert.ok(
    allowedRoute(
      `${ws}/agents/ag_${"2".repeat(32)}/versions/1/rehearsals`,
      "POST",
    ),
  );
  assert.ok(
    bodylessPostRoute(
      `${ws}/agents/ag_${"2".repeat(32)}/versions/1/rehearsals`,
    ),
  );
  assert.equal(bodylessPostRoute(`${ws}/agents`), false);
  for (const method of ["POST", "DELETE", "PATCH", "PUT"])
    assert.equal(allowedRoute(`${ws}/runs`, method), false);
  for (const path of [
    "https://evil.example/v1/me",
    "v1/../healthz",
    `${ws}/paper/accounts/a/orders`,
    `${ws}/agents/../../secrets`,
    "v1/workspaces/not-a-workspace/agents",
  ])
    assert.equal(allowedRoute(path, "GET"), false);
});
test("backend origin is fixed and rejects unsafe protocols and embedded credentials", () => {
  assert.equal(
    controlPlaneOrigin("http://127.0.0.1:58300"),
    "http://127.0.0.1:58300",
  );
  assert.equal(
    controlPlaneOrigin("https://control.example"),
    "https://control.example",
  );
  for (const url of [
    "file:///etc/passwd",
    "http://remote.example",
    "https://user:pass@example.com",
    "https://example.com/path",
    "https://example.com?target=other",
  ])
    assert.throws(() => controlPlaneOrigin(url));
});
test("monetary strings keep every digit beyond IEEE-754 precision", () => {
  assert.equal(
    decimal("9007199254740993.123456789012"),
    "9,007,199,254,740,993.123456789012",
  );
  assert.equal(
    money({ amount: "-1234567.000001", currency: "USD" }),
    "-1,234,567.000001 USD",
  );
  assert.equal(decimal("0.000000000001"), "0.000000000001");
});
