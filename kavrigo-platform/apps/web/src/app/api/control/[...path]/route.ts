import { NextRequest, NextResponse } from "next/server";
import { allowedRoute, controlPlaneOrigin } from "@/lib/proxy-policy";

export const dynamic = "force-dynamic";

async function handle(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const path = (await context.params).path.join("/");
  if (!allowedRoute(path, request.method))
    return NextResponse.json(
      { message: "Route unavailable." },
      { status: 404 },
    );
  if (
    request.method !== "GET" &&
    request.headers.get("origin") !==
      (process.env.KAVRIGO_WEB_ORIGIN ?? "http://localhost:3000")
  ) {
    return NextResponse.json({ message: "Origin refused." }, { status: 403 });
  }
  const headers = new Headers({ Accept: "application/json" });
  const bearer = request.headers.get("authorization");
  if (bearer && /^Bearer [\x21-\x7e]{1,8192}$/.test(bearer))
    headers.set("Authorization", bearer);
  const key = request.headers.get("idempotency-key");
  if (key && /^[\w.-]{1,128}$/.test(key)) headers.set("Idempotency-Key", key);
  let body: string | undefined;
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.startsWith("application/json"))
      return NextResponse.json({ message: "JSON required." }, { status: 415 });
    // Bound streaming input before buffering; Content-Length alone is untrusted.
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader)
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 65_536) {
          await reader.cancel();
          return NextResponse.json(
            { message: "Specification is too large." },
            { status: 413 },
          );
        }
        chunks.push(value);
      }
    body = Buffer.concat(chunks).toString("utf8");
    headers.set("Content-Type", "application/json");
  }
  const started = Date.now();
  try {
    const origin = controlPlaneOrigin(
      process.env.KAVRIGO_API_ORIGIN ?? "http://127.0.0.1:58300",
    );
    const url = new URL(`${origin}/${path}`);
    for (const name of ["cursor", "limit"]) {
      const value = request.nextUrl.searchParams.get(name);
      if (value) url.searchParams.set(name, value);
    }
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(10_000),
    });
    console.info(
      JSON.stringify({
        event: "control_plane_response",
        status: upstream.status,
        duration_ms: Date.now() - started,
      }),
    );
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        ...(upstream.headers.get("x-request-id")
          ? { "X-Request-ID": upstream.headers.get("x-request-id")! }
          : {}),
      },
    });
  } catch {
    console.warn(
      JSON.stringify({
        event: "control_plane_unavailable",
        duration_ms: Date.now() - started,
      }),
    );
    return NextResponse.json(
      {
        message:
          "Control plane unavailable. Try again; check existing records before retrying a mutation.",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export { handle as GET, handle as POST };
