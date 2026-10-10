// The Next.js client bundle freezes public environment values during the image build.
// Check the deployment against that build before starting the standalone server.
const { createHash } = require("node:crypto");
const { readFileSync, writeFileSync } = require("node:fs");

const policyPath = "/app/web-build-policy.json";

function buildPolicy(environment) {
  for (const name of [
    "KAVRIGO_ENV",
    "KAVRIGO_WEB_AUTH_PROVIDER",
    "KAVRIGO_WEB_ORIGIN",
  ]) {
    if (!environment[name])
      throw new Error(`Web build policy requires ${name}`);
  }
  return {
    schemaVersion: 1,
    environment: environment.KAVRIGO_ENV,
    authProvider: environment.KAVRIGO_WEB_AUTH_PROVIDER,
    webOrigin: environment.KAVRIGO_WEB_ORIGIN,
    publishableKeySha256: createHash("sha256")
      .update(environment.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "")
      .digest("hex"),
  };
}

function assertRuntimePolicy(policy, environment) {
  if (policy?.schemaVersion !== 1)
    throw new Error("Web build/runtime policy mismatch: schemaVersion");
  const runtime = buildPolicy(environment);
  for (const name of [
    "environment",
    "authProvider",
    "webOrigin",
    "publishableKeySha256",
  ]) {
    if (policy[name] !== runtime[name])
      throw new Error(`Web build/runtime policy mismatch: ${name}`);
  }
}

module.exports = { buildPolicy, assertRuntimePolicy };

if (require.main === module) {
  try {
    if (process.argv[2] === "stamp") {
      writeFileSync(
        policyPath,
        `${JSON.stringify(buildPolicy(process.env))}\n`,
        {
          mode: 0o644,
        },
      );
    } else if (process.argv[2] === "start") {
      assertRuntimePolicy(
        JSON.parse(readFileSync(policyPath, "utf8")),
        process.env,
      );
    } else {
      throw new Error("Web build policy requires a stamp or start action");
    }
  } catch (error) {
    // Do not log runtime values, especially the Clerk publishable key or secret.
    console.error(error.message);
    process.exit(1);
  }
  if (process.argv[2] === "start") require("./server.js");
}
