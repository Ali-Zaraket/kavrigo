/** Fixed control-plane surface; never a general URL or execution proxy. */
export function allowedRoute(path: string, method: string): boolean {
  if (method === "GET" && /^v1\/(platform\/mode|me|workspaces)$/.test(path))
    return true;
  if (method === "POST" && path === "v1/workspaces") return true;
  const root = "v1/workspaces/ws_[0-9a-f]{32}";
  const agent = `${root}/agents/ag_[0-9a-f]{32}`;
  if (method === "GET")
    return new RegExp(
      `^(?:${root}/(?:agents|runs|paper/accounts|audit)|${agent}(?:/versions(?:/[1-9][0-9]*)?)?|${root}/runs/run_[0-9a-f]{32})$`,
    ).test(path);
  return (
    method === "POST" &&
    new RegExp(`^(?:${root}/agents|${agent}/versions)$`).test(path)
  );
}

export function controlPlaneOrigin(raw: string): string {
  const url = new URL(raw);
  if (
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error("Invalid control-plane origin");
  const local = ["localhost", "127.0.0.1", "api"].includes(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local))
    throw new Error("Control plane requires HTTPS outside local development");
  return url.origin;
}
