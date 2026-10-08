import { test } from "node:test";
import assert from "node:assert/strict";
import {
  allowedRoute,
  bodylessPostRoute,
  controlPlaneOrigin,
} from "../src/lib/proxy-policy.ts";
import { apiClient, decimal, money } from "../src/lib/client.ts";
import { webAuthConfiguration } from "../src/lib/auth-config.ts";

test("hosted Clerk configuration refuses unsigned auth and development keys", () => {
  const production = {
    NODE_ENV: "production",
    KAVRIGO_ENV: "paper-prod",
    KAVRIGO_WEB_AUTH_PROVIDER: "clerk",
    KAVRIGO_WEB_ORIGIN: "https://app.example.test",
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_live_example",
    CLERK_SECRET_KEY: "sk_live_example",
  };
  assert.deepEqual(webAuthConfiguration(production), {
    mode: "clerk",
    webOrigin: "https://app.example.test",
  });
  for (const override of [
    { KAVRIGO_WEB_AUTH_PROVIDER: "dev" },
    { KAVRIGO_WEB_ORIGIN: "http://app.example.test" },
    { KAVRIGO_WEB_ORIGIN: "https://localhost:3000" },
    { NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_test_example" },
    { CLERK_SECRET_KEY: "sk_test_example" },
    { CLERK_SECRET_KEY: undefined },
  ])
    assert.throws(() => webAuthConfiguration({ ...production, ...override }));
  assert.throws(() => webAuthConfiguration({ NODE_ENV: "production" }));
});

test("local Clerk sign-in keeps the development keys isolated to local", () => {
  assert.equal(
    webAuthConfiguration({
      KAVRIGO_ENV: "local",
      KAVRIGO_WEB_AUTH_PROVIDER: "clerk",
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
    }).mode,
    "clerk",
  );
  assert.throws(() =>
    webAuthConfiguration({
      KAVRIGO_ENV: "local",
      KAVRIGO_WEB_AUTH_PROVIDER: "clerk",
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_live_example",
      CLERK_SECRET_KEY: "sk_live_example",
    }),
  );
  assert.equal(
    webAuthConfiguration({
      KAVRIGO_ENV: "dev",
      KAVRIGO_WEB_AUTH_PROVIDER: "clerk",
      KAVRIGO_WEB_ORIGIN: "https://dev.example.test",
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
    }).mode,
    "clerk",
  );
});

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

test("hosted API requests use the current session token and fail closed after sign-out", async () => {
  const originalFetch = globalThis.fetch;
  const OriginalRequest = globalThis.Request;
  const forwarded = [];
  let token = "first-session";
  globalThis.Request = class extends OriginalRequest {
    constructor(input, init) {
      super(
        typeof input === "string"
          ? new URL(input, "http://localhost:3000")
          : input,
        init,
      );
    }
  };
  globalThis.fetch = async (request) => {
    forwarded.push(request.headers.get("authorization"));
    return Response.json({ mode: "paper" });
  };
  try {
    const client = apiClient(async () => token);
    await client.GET("/v1/platform/mode");
    token = "refreshed-session";
    await client.GET("/v1/platform/mode");
    token = "";
    await client.GET("/v1/platform/mode");
    assert.deepEqual(forwarded, [
      "Bearer first-session",
      "Bearer refreshed-session",
      null,
    ]);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.Request = OriginalRequest;
  }
});
