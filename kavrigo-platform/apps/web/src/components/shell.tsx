"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  Boxes,
  Check,
  Command,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Moon,
  Search,
  ShieldCheck,
  Sun,
  Wallet,
  Waypoints,
} from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMe, useMode, useSession } from "./session";
import { unwrap } from "@/lib/client";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./ui/dialog";

const links = [
  ["Overview", "/", LayoutDashboard],
  ["Studio", "/studio", Boxes],
  ["Research", "/research", FlaskConical],
  ["Pulse", "/pulse", Activity],
  ["Portfolio", "/portfolio", Wallet],
  ["Risk", "/risk", ShieldCheck],
  ["Paper", "/paper", BookOpen],
  ["Integrations", "/integrations", Waypoints],
  ["Audit", "/audit", Check],
] as const;

export function Notice({
  children,
  error = false,
}: {
  children: React.ReactNode;
  error?: boolean;
}) {
  return (
    <div
      className={`notice ${error ? "notice-error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-mark">
        <Waypoints aria-hidden="true" size={28} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { token, signOut, workspace, setWorkspace } = useSession();
  const mode = useMode();
  const me = useMe();
  const [light, setLight] = useState(false);
  const [command, setCommand] = useState(false);
  const [search, setSearch] = useState("");
  useEffect(() => {
    document.getElementById("main")?.focus({ preventScroll: true });
  }, [path]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        setCommand((value) => !value);
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = light ? "light" : "dark";
  }, [light]);
  const paper =
    !mode.isError &&
    mode.data?.default_trading_mode === "paper" &&
    mode.data.live_trading_enabled === false;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="Kavrigo overview">
          <svg
            width="30"
            height="30"
            viewBox="0 0 32 32"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M3 6h8l7 10-7 10H3M18 4v24M24 8h5M24 16h5M24 24h5"
              stroke="currentColor"
              strokeWidth="2"
            />
          </svg>
          <span>
            KAVRIGO<span className="brand-sub">AGENT OPERATING SYSTEM</span>
          </span>
        </Link>
        <div className="workspace-picker">
          <label htmlFor="workspace">WORKSPACE</label>
          <select
            id="workspace"
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            disabled={!token || me.isError}
          >
            <option value="">Select workspace</option>
            {me.data?.workspaces.map((w) => (
              <option key={w.workspace_id} value={w.workspace_id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
        <nav aria-label="Primary navigation">
          {links.map(([label, href, Icon]) => (
            <Link
              href={href}
              key={href}
              aria-current={path === href ? "page" : undefined}
            >
              <Icon size={18} aria-hidden="true" />
              {label}
              {href === "/studio" && <span className="nav-hint">BUILD</span>}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck size={19} aria-hidden="true" />
          <p>
            Evidence before execution.
            <br />
            <span>Risk stays in control.</span>
          </p>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span>{" "}
            {links.find(([, href]) => href === path)?.[0] ?? "Inspect"}
          </div>
          <div className="top-actions">
            <span className={`mode-badge ${paper ? "verified" : "unknown"}`}>
              {paper ? "PAPER · SIMULATED" : "MODE UNVERIFIED"}
            </span>
            <Button
              variant="ghost"
              onClick={() => setCommand(true)}
              aria-label="Search navigation"
            >
              <Search size={18} />
              <kbd>Ctrl K</kbd>
            </Button>
            <Button
              variant="ghost"
              onClick={() => setLight(!light)}
              aria-label={light ? "Use dark theme" : "Use light theme"}
            >
              {light ? <Moon size={18} /> : <Sun size={18} />}
            </Button>
            {token && (
              <Button variant="ghost" onClick={signOut} aria-label="Sign out">
                <LogOut size={18} />
              </Button>
            )}
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          {!paper && (
            <Notice error>
              Trading mode cannot be verified. Creation is unavailable until the
              control plane confirms paper mode.{" "}
              <Button variant="outline" onClick={() => void mode.refetch()}>
                Retry connection
              </Button>
            </Notice>
          )}
          {!token ? (
            <SignIn
              local={mode.data?.environment === "local" && !mode.isError}
            />
          ) : me.isPending ? (
            <Notice>Checking your workspace membership…</Notice>
          ) : me.isError ? (
            <Notice error>
              {me.error.message}
              <Button variant="outline" onClick={() => void me.refetch()}>
                Retry membership
              </Button>
            </Notice>
          ) : !workspace ? (
            <WorkspaceSetup paper={paper} />
          ) : !me.data?.workspaces.some((w) => w.workspace_id === workspace) ? (
            <Notice error>
              Workspace membership is unavailable. Select an accessible
              workspace.
            </Notice>
          ) : (
            <div key={workspace}>{children}</div>
          )}
        </main>
        <footer>
          <span>
            KAVRIGO{" "}
            <span className="muted">/ Build agents. Prove the edge.</span>
          </span>
          <span>
            Paper trading is a simulation. Results do not predict future
            performance.
          </span>
        </footer>
      </div>
      <Dialog open={command} onOpenChange={setCommand}>
        <DialogContent>
          <DialogTitle>Go to workspace page</DialogTitle>
          <DialogDescription>
            Find a page. Use Tab to move through results.
          </DialogDescription>
          <label className="sr-only" htmlFor="command-search">
            Search pages
          </label>
          <input
            id="command-search"
            placeholder="Search pages…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="command-results">
            {links
              .filter(([label]) =>
                label.toLowerCase().includes(search.toLowerCase()),
              )
              .map(([label, href, Icon]) => (
                <Button
                  variant="ghost"
                  key={href}
                  onClick={() => {
                    router.push(href);
                    setCommand(false);
                  }}
                >
                  <Icon size={18} aria-hidden="true" />
                  {label}
                  <ArrowUpRight size={16} aria-hidden="true" />
                </Button>
              ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SignIn({ local }: { local: boolean }) {
  const { signIn } = useSession();
  const [value, setValue] = useState("");
  return (
    <div className="welcome">
      <div className="eyebrow">
        <Command size={16} aria-hidden="true" /> GOVERNED BY DESIGN
      </div>
      <h1>
        Build agents.
        <br />
        <span>Prove the edge.</span>
      </h1>
      <p className="lead">
        A workspace for AI trading agents you can test, inspect, and govern.
        Start with evidence. Keep execution under deterministic risk controls.
      </p>
      <div className="welcome-flow">
        <span>Evidence</span>
        <span>→</span>
        <span>Decision</span>
        <span>→</span>
        <span>Risk</span>
        <span>→</span>
        <span>Paper</span>
      </div>
      <form
        className="panel sign-in"
        onSubmit={(event) => {
          event.preventDefault();
          signIn(local ? `dev:${value}` : value);
        }}
      >
        <div className="section-label">
          {local ? "LOCAL DEVELOPMENT" : "AUTHENTICATION"}
        </div>
        <h2>Start in paper mode</h2>
        <p>
          {local
            ? "This local environment accepts a development identity. Use the same identity to return to your workspaces."
            : "Hosted sign-in is not configured. Use a control-plane bearer token from your configured identity provider."}
        </p>
        <label htmlFor="identity">
          {local ? "Development identity" : "Session token"}
        </label>
        <input
          id="identity"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          type={local ? "text" : "password"}
          required
          maxLength={local ? 100 : 8192}
          pattern={local ? "[a-zA-Z0-9_-]+" : undefined}
          autoComplete="off"
          placeholder={local ? "your-local-name" : "Paste session token"}
        />
        <Button type="submit">
          Open workspace <ArrowUpRight size={17} aria-hidden="true" />
        </Button>
        <small>Session stays in memory. Refreshing signs you out.</small>
      </form>
    </div>
  );
}

function WorkspaceSetup({ paper }: { paper: boolean }) {
  const { api, setWorkspace } = useSession();
  const me = useMe();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/workspaces", {
          body: { name, slug },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: async (w) => {
      await client.invalidateQueries({ queryKey: ["me"] });
      setWorkspace(w.workspace_id);
    },
  });
  return (
    <div className="page">
      <div className="eyebrow">YOUR CONTROL PLANE</div>
      <h1>Choose your workspace</h1>
      <p className="lead">
        Agent versions, decisions, and paper results stay scoped to your team.
      </p>
      <div className="workspace-grid">
        {me.data?.workspaces.map((w) => (
          <Button
            variant="outline"
            key={w.workspace_id}
            onClick={() => setWorkspace(w.workspace_id)}
          >
            {w.name}
            <span className="muted">{w.role}</span>
            <ArrowUpRight size={16} />
          </Button>
        ))}
      </div>
      <form
        className="panel form-panel"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <h2>Create a workspace</h2>
        <label htmlFor="workspace-name">Name</label>
        <input
          id="workspace-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={120}
          disabled={create.isPending || create.isError}
        />
        <label htmlFor="workspace-slug">Unique slug</label>
        <input
          id="workspace-slug"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          required
          minLength={3}
          maxLength={64}
          pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
          disabled={create.isPending || create.isError}
        />
        <small>Lowercase letters, numbers, and hyphens.</small>
        {create.isError && (
          <Notice error>
            {create.error.message} Retry reuses the same request. Refresh to
            start a different request.
          </Notice>
        )}
        <Button type="submit" disabled={!paper || create.isPending}>
          {create.isPending
            ? "Creating…"
            : create.isError
              ? "Retry same request"
              : "Create workspace"}
        </Button>
      </form>
    </div>
  );
}
