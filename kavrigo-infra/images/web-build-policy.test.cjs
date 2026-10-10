const assert = require("node:assert/strict");
const { test } = require("node:test");
const { buildPolicy, assertRuntimePolicy } = require("./web-build-policy.cjs");

const local = {
  KAVRIGO_ENV: "local",
  KAVRIGO_WEB_AUTH_PROVIDER: "dev",
  KAVRIGO_WEB_ORIGIN: "http://localhost:3000",
};

test("matching runtime can start without a Clerk key", () => {
  assert.doesNotThrow(() => assertRuntimePolicy(buildPolicy(local), local));
});

test("local image cannot be promoted by changing runtime stage or auth", () => {
  const policy = buildPolicy(local);
  for (const override of [
    { KAVRIGO_ENV: "staging" },
    { KAVRIGO_WEB_AUTH_PROVIDER: "clerk" },
    { KAVRIGO_WEB_ORIGIN: "https://app.example.test" },
  ]) {
    assert.throws(
      () => assertRuntimePolicy(policy, { ...local, ...override }),
      /Web build\/runtime policy mismatch/,
    );
  }
});

test("Clerk publishable key is compared without storing or logging the key", () => {
  const hosted = {
    KAVRIGO_ENV: "staging",
    KAVRIGO_WEB_AUTH_PROVIDER: "clerk",
    KAVRIGO_WEB_ORIGIN: "https://app.example.test",
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_live_first",
  };
  const policy = buildPolicy(hosted);
  assert.equal(
    JSON.stringify(policy).includes(hosted.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY),
    false,
  );
  assert.doesNotThrow(() => assertRuntimePolicy(policy, hosted));
  assert.throws(
    () =>
      assertRuntimePolicy(policy, {
        ...hosted,
        NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_live_second",
      }),
    /^Error: Web build\/runtime policy mismatch: publishableKeySha256$/,
  );
});

test("missing or unknown policy schema fails closed", () => {
  assert.throws(() => assertRuntimePolicy({}, local), /schemaVersion/);
  assert.throws(
    () =>
      assertRuntimePolicy({ ...buildPolicy(local), schemaVersion: 2 }, local),
    /schemaVersion/,
  );
  assert.throws(
    () => buildPolicy({ ...local, KAVRIGO_ENV: "" }),
    /requires KAVRIGO_ENV/,
  );
});
