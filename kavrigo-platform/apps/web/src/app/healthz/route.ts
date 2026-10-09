/** Cheap process probe. Product/API readiness is checked separately. */
export function GET() {
  return Response.json(
    { status: "ok" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
