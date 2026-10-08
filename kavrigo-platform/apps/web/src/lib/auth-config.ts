/** Deployment boundary shared by the web server and Clerk proxy. No key values enter errors. */
export function webAuthConfiguration(
  environment: Record<string, string | undefined> = process.env,
): { mode: "dev" | "clerk"; webOrigin: string } {
  const stage = environment.KAVRIGO_ENV;
  if (stage && !["local", "dev", "staging", "paper-prod"].includes(stage))
    throw new Error("KAVRIGO_ENV must name a supported paper environment");
  if (!stage && environment.NODE_ENV === "production")
    throw new Error("KAVRIGO_ENV must be explicit in production builds");

  const hosted = stage !== undefined && stage !== "local";
  const productionIdentity = stage === "staging" || stage === "paper-prod";
  const mode = environment.KAVRIGO_WEB_AUTH_PROVIDER ?? "dev";
  if (mode !== "dev" && mode !== "clerk")
    throw new Error("KAVRIGO_WEB_AUTH_PROVIDER must be dev or clerk");
  if (hosted && mode !== "clerk")
    throw new Error("Hosted web environments require Clerk authentication");

  const webOrigin = environment.KAVRIGO_WEB_ORIGIN ?? "http://localhost:3000";
  const url = new URL(webOrigin);
  if (
    url.origin !== webOrigin ||
    url.username ||
    url.password ||
    (hosted &&
      (url.protocol !== "https:" ||
        ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)))
  )
    throw new Error("KAVRIGO_WEB_ORIGIN must be the deployed HTTPS origin");

  if (mode === "clerk") {
    const publishable = environment.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
    const secret = environment.CLERK_SECRET_KEY;
    const prefix = productionIdentity ? "live" : "test";
    if (
      !publishable?.startsWith(`pk_${prefix}_`) ||
      !secret?.startsWith(`sk_${prefix}_`)
    )
      throw new Error(
        `Clerk ${prefix} publishable and secret keys are required together`,
      );
  }
  return { mode, webOrigin };
}
