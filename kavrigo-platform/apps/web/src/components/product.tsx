"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  Database,
  FlaskConical,
  Layers,
  ShieldCheck,
} from "lucide-react";
import { type Schema, money, utc, unwrap } from "@/lib/client";
import { useMe, useSession } from "./session";
import { Empty, Notice } from "./shell";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./ui/dialog";
import { DataTable } from "./data-table";
import { Studio } from "./studio";

export function useAgents(cursor?: string) {
  const { api, workspace } = useSession();
  return useQuery({
    queryKey: [workspace, "agents", cursor],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/v1/workspaces/{workspace_id}/agents", {
          signal,
          params: {
            path: { workspace_id: workspace },
            query: { cursor, limit: 25 },
          },
        }),
      ),
  });
}
function useRuns(cursor?: string) {
  const { api, workspace } = useSession();
  return useQuery({
    queryKey: [workspace, "runs", cursor],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/v1/workspaces/{workspace_id}/runs", {
          signal,
          params: {
            path: { workspace_id: workspace },
            query: { cursor, limit: 25 },
          },
        }),
      ),
    refetchInterval: 15_000,
  });
}
function Pager({
  hasMore,
  next,
  first,
}: {
  hasMore: boolean;
  next: () => void;
  first: () => void;
}) {
  return (
    <div className="pager">
      <small>25 records per page · sorted within this page</small>
      <Button variant="ghost" onClick={first}>
        First page
      </Button>
      <Button variant="outline" disabled={!hasMore} onClick={next}>
        Next page <ArrowRight size={15} />
      </Button>
    </div>
  );
}
const titles: Record<string, [string, string, string]> = {
  overview: [
    "WORKSPACE OVERVIEW",
    "Your agents. Under control.",
    "Build, evaluate, and inspect every decision in one paper workspace.",
  ],
  studio: [
    "BUILD & VERSION",
    "Agent Studio",
    "Define the agent. Review the specification. Preserve every version.",
  ],
  research: [
    "TEST BEFORE TRUST",
    "Research",
    "Inspect reproducible backtest runs, their costs, and their limitations.",
  ],
  pulse: [
    "DECISIONS & EVIDENCE",
    "Pulse",
    "Inspect what your agents knew, why they abstained, and what they proposed.",
  ],
  portfolio: [
    "PAPER ACCOUNTING",
    "Portfolio",
    "Stored paper balances and positions, exactly as the ledger recorded them.",
  ],
  paper: [
    "SIMULATED EXECUTION",
    "Paper",
    "Inspect account receipts. Every simulated order remains subject to deterministic risk.",
  ],
  risk: [
    "DETERMINISTIC CONTROLS",
    "Risk",
    "Risk policy is enforced outside the model. A proposal is never an order.",
  ],
  integrations: [
    "DATA & CONNECTIVITY",
    "Integrations",
    "Know where your evidence comes from and when it was last observed.",
  ],
  audit: [
    "IMMUTABLE HISTORY",
    "Audit",
    "Workspace mutations with durable audit records.",
  ],
};
export function Product({ section }: { section: string }) {
  const [eyebrow, title, subtitle] = titles[section];
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          <p className="lead">{subtitle}</p>
        </div>
        <span className="scope-label">
          <ShieldCheck size={16} aria-hidden="true" /> PAPER WORKSPACE
        </span>
      </div>
      {section === "overview" && <Overview />}
      {section === "studio" && <Studio />}
      {(section === "research" || section === "pulse") && (
        <Runs research={section === "research"} />
      )}
      {(section === "portfolio" || section === "paper") && <Accounts />}
      {section === "risk" && <Risk />}
      {section === "integrations" && <Integrations />}
      {section === "audit" && <Audit />}
    </div>
  );
}
function Overview() {
  const agents = useAgents();
  const runs = useRuns();
  return (
    <>
      <div className="metric-grid">
        <Metric
          label="Agent specifications"
          value={
            agents.isError
              ? "Unavailable"
              : agents.data
                ? `${agents.data.items.length}${agents.data.has_more ? "+" : ""}`
                : "…"
          }
          detail="Versioned · draft by default"
          icon={<Layers />}
        />
        <Metric
          label="Stored runs"
          value={
            runs.isError
              ? "Unavailable"
              : runs.data
                ? `${runs.data.items.length}${runs.data.has_more ? "+" : ""}`
                : "…"
          }
          detail="First page · all workflow types"
          icon={<FlaskConical />}
        />
        <Metric
          label="Execution environment"
          value="Simulation"
          detail="No private exchange credentials"
          icon={<ShieldCheck />}
        />
      </div>
      <div className="overview-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>From specification to evidence</h2>
            <span className="chip">WORKFLOW</span>
          </div>
          <div className="build-path">
            {[
              [
                "01",
                "Define your agent",
                "Choose its universe, data, model policy, and immutable risk references.",
                "/studio",
              ],
              [
                "02",
                "Inspect the research",
                "Review stored backtests. A refused run is not a successful strategy result.",
                "/research",
              ],
              [
                "03",
                "Review every decision",
                "Follow supporting and contradicting evidence before assessing a proposal.",
                "/pulse",
              ],
            ].map(([n, title, copy, href]) => (
              <Link href={href} key={n}>
                <span className="step-number">{n}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{copy}</p>
                </div>
                <ArrowUpRight size={18} aria-hidden="true" />
              </Link>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>Control status</h2>
            <ShieldCheck size={19} aria-hidden="true" />
          </div>
          <div className="control-row">
            <span>Live execution</span>
            <span className="chip">DISABLED IN THIS RELEASE</span>
          </div>
          <div className="control-row">
            <span>Portfolio layer</span>
            <span>Required</span>
          </div>
          <div className="control-row">
            <span>Abstention</span>
            <span>Valid outcome</span>
          </div>
          <div className="control-row">
            <span>Provider freshness</span>
            <span className="warning-text">Not connected</span>
          </div>
          <p className="panel-note">
            This is the local paper platform. Hosted identity, live data
            transport, and strategy wiring remain incomplete.
          </p>
          <Link className="text-link" href="/risk">
            Inspect risk boundaries <ArrowRight size={16} />
          </Link>
        </section>
      </div>
      <Runs compact />
    </>
  );
}
function Metric({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <section className="metric">
      <div>
        <span>{label}</span>
        <span className="metric-icon" aria-hidden="true">
          {icon}
        </span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </section>
  );
}
function Runs({
  research = false,
  compact = false,
}: {
  research?: boolean;
  compact?: boolean;
}) {
  const [cursor, setCursor] = useState<string>();
  const result = useRuns(cursor);
  const [selected, select] = useState<string>();
  if (result.isPending) return <Notice>Loading stored runs…</Notice>;
  if (result.isError)
    return (
      <Notice error>
        {result.error.message}
        <Button variant="outline" onClick={() => void result.refetch()}>
          Retry runs
        </Button>
      </Notice>
    );
  const rows = result.data.items.filter(
    (r) => !research || r.kind === "backtest",
  );
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>
            {research
              ? "Backtest Lab"
              : compact
                ? "Run activity"
                : "Decision runs"}
          </h2>
          <p>
            {research
              ? "Strategy and frozen-data wiring are pending. Zero-decision runs are refused."
              : "Stored workflow state · refreshes every 15 seconds"}
          </p>
        </div>
        <Button variant="ghost" onClick={() => void result.refetch()}>
          Refresh
        </Button>
      </div>
      {rows.length ? (
        <DataTable
          data={rows}
          caption="Stored workflow runs"
          columns={[
            {
              accessorKey: "run_id",
              header: "Run",
              cell: ({ row }) => (
                <button
                  className="text-link mono"
                  onClick={() => select(row.original.run_id)}
                >
                  {row.original.run_id.slice(0, 16)}…{" "}
                  <ArrowUpRight size={14} aria-hidden="true" />
                </button>
              ),
            },
            { accessorKey: "kind", header: "Type" },
            {
              accessorKey: "input_kind",
              header: "Input",
              cell: ({ row }) =>
                row.original.input_kind === "synthetic_rehearsal"
                  ? "Synthetic rehearsal"
                  : row.original.input_kind === "testnet_rehearsal"
                    ? "Testnet rehearsal"
                    : "Recorded",
            },
            {
              accessorKey: "status",
              header: "State",
              cell: ({ row }) => (
                <span
                  className={`chip ${row.original.status === "refused" || row.original.status === "uncertain" ? "chip-warning" : ""}`}
                >
                  {row.original.status.toUpperCase()}
                </span>
              ),
            },
            {
              accessorKey: "created_at",
              header: "Created · UTC",
              cell: ({ row }) => (
                <span className="mono">{utc(row.original.created_at)}</span>
              ),
            },
          ]}
        />
      ) : (
        <Empty
          title={research ? "No backtests on this page" : "No stored runs yet"}
        >
          Runs appear after the engine records them for this workspace. No
          simulated performance has been invented.
        </Empty>
      )}
      <Pager
        hasMore={result.data.has_more ?? false}
        first={() => setCursor(undefined)}
        next={() => setCursor(result.data.next_cursor ?? undefined)}
      />
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) select(undefined);
        }}
      >
        <DialogContent>
          <DialogTitle>Run inspection</DialogTitle>
          <DialogDescription>
            Stored evidence and stage receipts. A decision is a proposal, not an
            execution confirmation.
          </DialogDescription>
          {selected && <RunDetail id={selected} />}
        </DialogContent>
      </Dialog>
    </section>
  );
}
function RunDetail({ id }: { id: string }) {
  const { api, workspace } = useSession();
  const result = useQuery({
    queryKey: [workspace, "run", id],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/v1/workspaces/{workspace_id}/runs/{run_id}", {
          signal,
          params: { path: { workspace_id: workspace, run_id: id } },
        }),
      ),
  });
  if (result.isPending) return <Notice>Loading run receipt…</Notice>;
  if (result.isError) return <Notice error>{result.error.message}</Notice>;
  const run = result.data;
  return (
    <div className="inspection">
      <p className="mono break">{id}</p>
      <span className="chip">
        {run.kind} · {run.status}
      </span>
      {run.input_kind === "synthetic_rehearsal" && (
        <Notice>
          Synthetic rehearsal only. No live market observation, approved
          strategy, or order execution is represented here.
        </Notice>
      )}
      {run.input_kind === "testnet_rehearsal" && (
        <Notice>
          Binance Spot Testnet evidence only. The market activity is simulated,
          the local model abstains, and execution remains disabled.
        </Notice>
      )}
      <p>Created {utc(run.created_at)}</p>
      <details>
        <summary>Immutable input hash</summary>
        <code className="break">{run.input_hash}</code>
      </details>
      <h3>Stage receipts</h3>
      {run.stages.map((s) => (
        <div key={s.stage} className="control-row">
          <span>{s.stage}</span>
          <span>{s.status}</span>
        </div>
      ))}
      {run.reason_codes.length > 0 && (
        <Notice>{run.reason_codes.join(" · ")}</Notice>
      )}
      {run.decisions.length === 0 && (
        <p>No structured decision is present in this receipt.</p>
      )}
      {run.decisions.map((d) => (
        <Decision key={d.decision_id} decision={d} evidence={run.evidence} />
      ))}
    </div>
  );
}
function Decision({
  decision: d,
  evidence,
}: {
  decision: Schema["AgentDecision"];
  evidence: Schema["EvidenceItem"][];
}) {
  function items(refs: string[]) {
    return refs.length ? (
      refs.map((id) => {
        const item = evidence.find((e) => e.evidence_id === id);
        return (
          <li key={id}>
            {item ? (
              <>
                <strong>{item.kind}</strong>
                <p>{item.summary}</p>
                <small>
                  {item.provider} · observed {utc(item.observed_at)} ·{" "}
                  {item.source_class}
                </small>
                <p className="mono break">{item.source_ref}</p>
              </>
            ) : (
              <span>Evidence unavailable: {id}</span>
            )}
          </li>
        );
      })
    ) : (
      <li>No evidence references recorded.</li>
    );
  }
  return (
    <article className="decision">
      <h3>
        {d.instrument_id.base}/{d.instrument_id.quote} · {d.instrument_id.venue}
      </h3>
      <div className="decision-facts">
        <span className="chip">{d.proposed_action.toUpperCase()}</span>
        <span>
          {d.state} · {d.market_regime}
        </span>
      </div>
      <p>{d.rationale}</p>
      <p>
        Confidence {Math.round(d.prediction.confidence * 100)}% · uncertainty{" "}
        {Math.round(d.prediction.uncertainty * 100)}% · horizon{" "}
        {d.prediction.horizon_minutes} min
      </p>
      <small>
        Decision time: {utc(d.decided_at)}. Evidence timestamps below describe
        this historical decision, not current freshness.
      </small>
      <h4>Supporting evidence</h4>
      <ul className="evidence-list">{items(d.evidence_refs ?? [])}</ul>
      <h4>Contradicting evidence</h4>
      <ul className="evidence-list">
        {items(d.contradicting_evidence_refs ?? [])}
      </ul>
      <p>Risk flags: {d.risk_flags?.join(", ") || "None recorded"}</p>
      <p>Estimated cost: {d.estimated_cost_bps ?? "Unknown"} bps</p>
      <details>
        <summary>Version and model cost receipts</summary>
        <p className="mono break">{d.agent_version_id}</p>
        {d.model_calls?.map((call) => (
          <p key={call.model_call_id}>
            {call.profile}: {money(call.cost)} · {call.latency_ms} ms
          </p>
        ))}
      </details>
    </article>
  );
}
function Accounts() {
  const { api, workspace } = useSession();
  const [cursor, setCursor] = useState<string>();
  const result = useQuery({
    queryKey: [workspace, "accounts", cursor],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/v1/workspaces/{workspace_id}/paper/accounts", {
          signal,
          params: {
            path: { workspace_id: workspace },
            query: { cursor, limit: 25 },
          },
        }),
      ),
    refetchInterval: 15_000,
  });
  if (result.isPending) return <Notice>Loading paper receipts…</Notice>;
  if (result.isError)
    return (
      <Notice error>
        {result.error.message}
        <Button variant="outline" onClick={() => void result.refetch()}>
          Retry accounts
        </Button>
      </Notice>
    );
  return (
    <>
      <Notice>
        Historical receipt view. Balances and P&amp;L are supplied by the
        server; the browser does not calculate account authority.
      </Notice>
      {result.data.items.length === 0 ? (
        <section className="panel">
          <Empty title="No paper account receipts">
            An account will appear when the engine creates one in this
            workspace. Account creation and command controls are not available
            in this UI yet.
          </Empty>
        </section>
      ) : (
        result.data.items.map((account) => (
          <section className="panel" key={account.account_id}>
            <div className="panel-heading">
              <h2>{account.account_id}</h2>
              <span className="chip">PAPER · RECEIPT {account.sequence}</span>
            </div>
            <p className="panel-note">
              Ledger as of {utc(account.portfolio.as_of)} · committed{" "}
              {utc(account.committed_at)}
            </p>
            <div className="metric-grid">
              <Metric
                label="Recorded equity"
                value={money(account.portfolio.equity)}
                detail="Simulated valuation at receipt time"
                icon={<WalletIcon />}
              />
              <Metric
                label="Cash"
                value={money(account.portfolio.cash)}
                detail={`Reserved: ${money(account.portfolio.reserved_cash)}`}
                icon={<Database />}
              />
              <Metric
                label="Unrealized P&L"
                value={money(account.portfolio.unrealized_pnl)}
                detail={`Fees paid: ${money(account.fees_paid)}`}
                icon={<Layers />}
              />
            </div>
            <p className="panel-note">
              Reconciled at receipt:{" "}
              {account.portfolio.is_reconciled ? "Yes" : "No"} ·{" "}
              {account.portfolio.reconciled_at
                ? utc(account.portfolio.reconciled_at)
                : "Time unavailable"}
              . This does not assert current health.
            </p>
            {account.portfolio.positions?.length ? (
              <DataTable
                data={account.portfolio.positions}
                caption="Recorded paper positions"
                columns={[
                  {
                    id: "instrument",
                    header: "Instrument",
                    accessorFn: (p) =>
                      `${p.instrument_id.base}-${p.instrument_id.quote}.${p.instrument_id.venue}`,
                  },
                  {
                    id: "quantity",
                    header: "Quantity",
                    enableSorting: false,
                    accessorFn: (p) => p.quantity.value,
                    cell: ({ row }) => (
                      <span className="mono">
                        {row.original.quantity.value}{" "}
                        {row.original.quantity.asset}
                      </span>
                    ),
                  },
                  {
                    id: "pnl",
                    header: "Unrealized P&L",
                    cell: ({ row }) => (
                      <span className="mono">
                        {money(row.original.unrealized_pnl)}
                      </span>
                    ),
                  },
                ]}
              />
            ) : (
              <Empty title="No positions in this receipt">
                The account has no recorded open positions.
              </Empty>
            )}
            <details className="panel-note">
              <summary>State hash</summary>
              <code className="break">{account.state_hash}</code>
            </details>
          </section>
        ))
      )}
      <Pager
        hasMore={result.data.has_more ?? false}
        first={() => setCursor(undefined)}
        next={() => setCursor(result.data.next_cursor ?? undefined)}
      />
    </>
  );
}
const WalletIcon = Database;
function Risk() {
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <h2>Execution gates</h2>
          <span className="chip">ENFORCED BY ENGINE</span>
        </div>
        {[
          [
            "Version approval",
            "Immutable agent and policy versions must be approved for the target environment.",
          ],
          [
            "Freshness & evidence",
            "Stale data, unknown exposure, or insufficient evidence causes refusal.",
          ],
          [
            "Portfolio limits",
            "Account-wide reservations and concentration limits constrain every proposal.",
          ],
          [
            "Fencing & reconciliation",
            "A valid execution lease and reconciled state are required.",
          ],
          ["Abstention", "UNKNOWN and NO_TRADE are successful outcomes."],
        ].map(([title, body]) => (
          <div className="risk-row" key={title}>
            <ShieldCheck size={20} aria-hidden="true" />
            <div>
              <h3>{title}</h3>
              <p>{body}</p>
            </div>
            <span className="chip">REQUIRED</span>
          </div>
        ))}
      </section>
      <Notice>
        These are engine requirements, not a live health report. Policy editing,
        kill-switch controls, and account approval are not exposed by this UI.
        Inspect versioned policy references in Studio.
      </Notice>
      <Link className="text-link" href="/studio">
        Inspect agent policy references <ArrowRight size={16} />
      </Link>
    </>
  );
}
function Integrations() {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Provider freshness</h2>
        <span className="chip chip-warning">NO LIVE FEED</span>
      </div>
      {[
        "BTC / ETH market data",
        "News intelligence",
        "Network context",
        "Model gateway",
      ].map((source) => (
        <div className="integration-row" key={source}>
          <Database size={22} aria-hidden="true" />
          <div>
            <h3>{source}</h3>
            <p>
              {source === "Model gateway"
                ? "Local mock available to the engine. Hosted provider not configured."
                : "Live transport is not connected to this product view."}
            </p>
          </div>
          <div>
            <span className="chip">UNAVAILABLE</span>
            <small>Last observed: unknown</small>
          </div>
        </div>
      ))}
      <p className="panel-note">
        Stored evidence retains its original source and observation timestamp.
        No heartbeat or configuration flag is presented as proof of fresh market
        data.
      </p>
    </section>
  );
}
function Audit() {
  const { api, workspace } = useSession();
  const me = useMe();
  const [cursor, setCursor] = useState<string>();
  const allowed = me.data?.permissions[workspace]?.includes("audit:read");
  const result = useQuery({
    queryKey: [workspace, "audit", cursor],
    enabled: !!allowed,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/v1/workspaces/{workspace_id}/audit", {
          signal,
          params: {
            path: { workspace_id: workspace },
            query: { cursor, limit: 25 },
          },
        }),
      ),
  });
  if (!allowed)
    return (
      <Notice>Audit access requires a workspace administrator or owner.</Notice>
    );
  if (result.isPending) return <Notice>Loading audit history…</Notice>;
  if (result.isError) return <Notice error>{result.error.message}</Notice>;
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Workspace history</h2>
        <span className="chip">APPEND ONLY</span>
      </div>
      {result.data.items.length ? (
        <DataTable
          data={result.data.items}
          caption="Workspace audit records"
          columns={[
            { accessorKey: "action", header: "Action" },
            { accessorKey: "resource_type", header: "Resource" },
            {
              accessorKey: "resource_id",
              header: "Identifier",
              cell: ({ row }) => (
                <span className="mono break">{row.original.resource_id}</span>
              ),
            },
            {
              accessorKey: "occurred_at",
              header: "Recorded · UTC",
              cell: ({ row }) => utc(row.original.occurred_at),
            },
          ]}
        />
      ) : (
        <Empty title="No audit records on this page">
          Mutations appear here after the API commits them.
        </Empty>
      )}
      <Pager
        hasMore={result.data.has_more ?? false}
        first={() => setCursor(undefined)}
        next={() => setCursor(result.data.next_cursor ?? undefined)}
      />
    </section>
  );
}
