"use client";
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Play, Plus } from "lucide-react";
import { type Schema, unwrap } from "@/lib/client";
import { useMe, useMode, useSession } from "./session";
import { useAgents } from "./product";
import { Empty, Notice } from "./shell";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./ui/dialog";

export function Studio() {
  const [cursor, setCursor] = useState<string>();
  const agents = useAgents(cursor);
  const [editing, setEditing] = useState<string>();
  const [creating, setCreating] = useState(false);
  const { workspace } = useSession();
  const me = useMe();
  const canCreate = !!me.data?.permissions[workspace]?.includes("agent:create");
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Agent specifications</h2>
            <p>Every edit creates a new immutable version.</p>
          </div>
          <Button onClick={() => setCreating(true)} disabled={!canCreate}>
            <Plus size={17} aria-hidden="true" />
            Create agent
          </Button>
        </div>
        {agents.isPending ? (
          <Notice>Loading agents…</Notice>
        ) : agents.isError ? (
          <Notice error>
            {agents.error.message}
            <Button variant="outline" onClick={() => void agents.refetch()}>
              Retry agents
            </Button>
          </Notice>
        ) : agents.data.items.length ? (
          <div className="agent-grid">
            {agents.data.items.map((agent) => (
              <button
                className="agent-card"
                key={agent.agent_id}
                onClick={() => setEditing(agent.agent_id)}
              >
                <span className="chip">VERSION {agent.current_version}</span>
                <ArrowUpRight size={17} aria-hidden="true" />
                <h3>{agent.name}</h3>
                <p>{agent.description || "No description provided."}</p>
                <small>Inspect specification and version history</small>
              </button>
            ))}
          </div>
        ) : (
          <Empty title="Your first agent starts with a specification">
            Define its universe, decision interval, evidence requirements, and
            policy references. Saving a draft does not run it.
          </Empty>
        )}
        {agents.data && (
          <div className="pager">
            <Button variant="ghost" onClick={() => setCursor(undefined)}>
              First page
            </Button>
            <Button
              variant="outline"
              disabled={!agents.data.has_more}
              onClick={() => setCursor(agents.data.next_cursor ?? undefined)}
            >
              Next page
            </Button>
          </div>
        )}
      </section>
      <Notice>
        Conversational specification generation is not configured. The reviewed
        structured specification is authoritative; the model cannot change risk
        controls.
      </Notice>
      <Dialog
        open={creating || !!editing}
        onOpenChange={(open) => {
          if (!open) {
            setCreating(false);
            setEditing(undefined);
          }
        }}
      >
        <DialogContent>
          <DialogTitle>
            {editing ? "Inspect agent versions" : "Create an agent"}
          </DialogTitle>
          <DialogDescription>
            Paper draft only. Approval and run activation are separate engine
            gates.
          </DialogDescription>
          {editing ? (
            <VersionEditor id={editing} />
          ) : creating ? (
            <CreateAgent onSaved={() => setCreating(false)} />
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function CreateAgent({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [btc, setBtc] = useState(true);
  const [eth, setEth] = useState(true);
  const [interval, setInterval] = useState("900");
  const [risk, setRisk] = useState(
    () => `rp_${crypto.randomUUID().replaceAll("-", "")}`,
  );
  const [execution, setExecution] = useState(
    () => `ep_${crypto.randomUUID().replaceAll("-", "")}`,
  );
  const [budget, setBudget] = useState("0.10");
  const [key] = useState(() => crypto.randomUUID());
  const { api, workspace } = useSession();
  const mode = useMode();
  const client = useQueryClient();
  const spec: Schema["AgentSpec"] = {
    api_version: "agents.kavrigo/v1",
    kind: "TradingAgent",
    analysis: {
      market_scanner: true,
      network_context: true,
      asset_analyzer: true,
      portfolio_layer: true,
      horizons_minutes: [60],
      allow_abstain: true,
    },
    evidence: {
      min_source_quality: 0.65,
      require_timestamps: true,
      require_contradicting_evidence: true,
      min_evidence_items: 2,
    },
    name,
    description,
    mode: "paper",
    universe: {
      market_type: "spot",
      instruments: [btc ? "BTC" : "", eth ? "ETH" : ""]
        .filter(Boolean)
        .map((base) => ({
          base,
          quote: "USD",
          venue: "SIM",
          instrument_class: "spot",
        })),
    },
    schedule: {
      decision_interval_seconds: Number(interval),
      event_triggers: [],
      max_decisions_per_day: 96,
    },
    data_packs: ["price_technical"],
    model_policy: {
      max_cost_per_decision_usd: budget,
      profile: "reason_balanced",
      max_tool_calls: 12,
      max_output_tokens: 4096,
      timeout_seconds: 60,
    },
    risk_policy_ref: risk,
    execution_policy_ref: execution,
  };
  const mutation = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/workspaces/{workspace_id}/agents", {
          params: { path: { workspace_id: workspace } },
          headers: { "Idempotency-Key": key },
          body: {
            name,
            description,
            spec,
            change_summary: "Initial paper draft",
            author_kind: "human",
          },
        }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: [workspace, "agents"] });
      onSaved();
    },
  });
  const verified =
    !mode.isError &&
    mode.data?.default_trading_mode === "paper" &&
    mode.data.live_trading_enabled === false;
  return (
    <form
      className="editor"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <fieldset disabled={mutation.isPending || mutation.isError}>
        <label htmlFor="agent-name">Agent name</label>
        <input
          id="agent-name"
          required
          pattern="[a-z0-9][a-z0-9-]*"
          maxLength={64}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="btc-eth-evidence"
        />
        <label htmlFor="agent-description">Purpose</label>
        <textarea
          id="agent-description"
          maxLength={1000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe the question this agent will investigate."
        />
        <fieldset>
          <legend>Asset universe · simulated USD spot instruments</legend>
          <label className="check-label">
            <input
              type="checkbox"
              checked={btc}
              onChange={(e) => setBtc(e.target.checked)}
            />{" "}
            BTC-USD.SIM
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={eth}
              onChange={(e) => setEth(e.target.checked)}
            />{" "}
            ETH-USD.SIM
          </label>
        </fieldset>
        <div className="form-grid">
          <div>
            <label htmlFor="interval">Decision interval · seconds</label>
            <input
              id="interval"
              type="number"
              min={60}
              max={86400}
              step={1}
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="budget">Cost cap per decision · USD</label>
            <input
              id="budget"
              inputMode="decimal"
              pattern="[0-9]+(\.[0-9]+)?"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              required
            />
          </div>
        </div>
        <label htmlFor="risk-ref">
          Risk policy reference · rehearsal placeholder
        </label>
        <input
          id="risk-ref"
          pattern="rp_[0-9a-f]{32}"
          value={risk}
          onChange={(e) => setRisk(e.target.value)}
          required
          placeholder="rp_…"
        />
        <label htmlFor="execution-ref">
          Execution policy reference · rehearsal placeholder
        </label>
        <input
          id="execution-ref"
          pattern="ep_[0-9a-f]{32}"
          value={execution}
          onChange={(e) => setExecution(e.target.value)}
          required
          placeholder="ep_…"
        />
        <small>
          Local placeholder IDs are generated for a synthetic rehearsal. Saving
          a draft validates their format only. Replace them with provisioned,
          immutable policy IDs before any separately approved paper activation.
        </small>
      </fieldset>
      <details>
        <summary>Review structured specification</summary>
        <pre>{JSON.stringify(spec, null, 2)}</pre>
      </details>
      <Notice>
        Default evidence requires timestamps, supporting and contradicting
        evidence. Abstention and the portfolio layer remain enabled.
      </Notice>
      {mutation.isError && (
        <Notice error>
          {mutation.error.message} The request is frozen. Retry uses the same
          idempotency key; close and reopen to edit.
        </Notice>
      )}
      <Button
        type="submit"
        disabled={!verified || (!btc && !eth) || mutation.isPending}
      >
        {mutation.isPending
          ? "Saving draft…"
          : mutation.isError
            ? "Retry same draft"
            : "Save paper draft"}
      </Button>
    </form>
  );
}

function RehearsalLauncher({
  detail,
  agentId,
}: {
  detail: Schema["AgentVersionResponse"];
  agentId: string;
}) {
  const { api, workspace } = useSession();
  const mode = useMode();
  const me = useMe();
  const client = useQueryClient();
  const [key] = useState(() => crypto.randomUUID());
  const [launched, setLaunched] = useState<Schema["RehearsalLaunch"]>();
  const spec = detail.spec as Schema["AgentSpec"];
  const instruments = spec.universe?.instruments ?? [];
  const supported =
    spec.mode === "paper" &&
    instruments.length >= 1 &&
    instruments.length <= 2 &&
    instruments.every((i) => i.quote === "USD" && i.venue === "SIM");
  const permitted = me.data?.permissions[workspace]?.includes("run:start");
  const paperVerified =
    !mode.isError &&
    mode.data?.default_trading_mode === "paper" &&
    mode.data.live_trading_enabled === false;
  const launch = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST(
          "/v1/workspaces/{workspace_id}/agents/{agent_id}/versions/{version}/rehearsals",
          {
            params: {
              path: {
                workspace_id: workspace,
                agent_id: agentId,
                version: detail.version,
              },
            },
            headers: { "Idempotency-Key": key },
          },
        ),
      ),
    onSuccess: async (result) => {
      setLaunched(result);
      await client.invalidateQueries({ queryKey: [workspace, "runs"] });
    },
  });
  return (
    <section className="rehearsal-launch" aria-label="Local paper rehearsal">
      <h3>Local paper rehearsal</h3>
      <p>
        Run this saved version through a durable workflow with clearly marked
        synthetic evidence and an abstaining local model. The isolated account
        has a global risk stop; no order can be submitted. This is not market
        data, a backtest, or an approved paper agent.
      </p>
      {!supported && (
        <Notice>
          This rehearsal supports one or two USD spot instruments on SIM. The
          saved version remains unchanged.
        </Notice>
      )}
      {!permitted && (
        <Notice>Launching requires run permission in this workspace.</Notice>
      )}
      {launch.isError && (
        <Notice error>
          {launch.error.message} Retry keeps the same request key and frozen
          input.
        </Notice>
      )}
      {launched && (
        <Notice>
          {launched.dispatch_state === "dispatched"
            ? "Rehearsal dispatched."
            : "Rehearsal saved; dispatch is pending. Retry dispatch with the same key."}{" "}
          <span className="mono break">{launched.run_id}</span>{" "}
          <Link className="text-link" href="/pulse">
            Inspect in Pulse <ArrowUpRight size={14} aria-hidden="true" />
          </Link>
        </Notice>
      )}
      <Button
        type="button"
        variant="outline"
        onClick={() => launch.mutate()}
        disabled={
          !supported ||
          !permitted ||
          !paperVerified ||
          launch.isPending ||
          launched?.dispatch_state === "dispatched"
        }
      >
        <Play size={16} aria-hidden="true" />
        {launch.isPending
          ? "Submitting rehearsal…"
          : launched?.dispatch_state === "queued"
            ? "Retry dispatch"
            : "Run local rehearsal"}
      </Button>
    </section>
  );
}

function VersionEditor({ id }: { id: string }) {
  const { api, workspace } = useSession();
  const [version, setVersion] = useState<number>();
  const [cursor, setCursor] = useState<string>();
  const versions = useQuery({
    queryKey: [workspace, "versions", id, cursor],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET(
          "/v1/workspaces/{workspace_id}/agents/{agent_id}/versions",
          {
            signal,
            params: {
              path: { workspace_id: workspace, agent_id: id },
              query: { limit: 25, cursor },
            },
          },
        ),
      ),
  });
  const selected = version ?? versions.data?.items[0]?.version;
  const detail = useQuery({
    queryKey: [workspace, "version", id, selected],
    enabled: selected !== undefined,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET(
          "/v1/workspaces/{workspace_id}/agents/{agent_id}/versions/{version}",
          {
            signal,
            params: {
              path: {
                workspace_id: workspace,
                agent_id: id,
                version: selected!,
              },
            },
          },
        ),
      ),
  });
  if (versions.isPending) return <Notice>Loading immutable versions…</Notice>;
  if (versions.isError) return <Notice error>{versions.error.message}</Notice>;
  return (
    <div className="editor">
      <label htmlFor="version">Inspect version</label>
      <select
        id="version"
        value={selected ?? ""}
        onChange={(e) => setVersion(Number(e.target.value))}
      >
        {versions.data.items.map((v) => (
          <option key={v.agent_version_id} value={v.version}>
            v{v.version} · {v.stage} · {v.approval_status}
          </option>
        ))}
      </select>
      <div className="pager">
        <Button
          variant="ghost"
          onClick={() => {
            setCursor(undefined);
            setVersion(undefined);
          }}
        >
          First page
        </Button>
        <Button
          variant="outline"
          disabled={!versions.data.has_more}
          onClick={() => {
            setCursor(versions.data.next_cursor ?? undefined);
            setVersion(undefined);
          }}
        >
          Next versions
        </Button>
      </div>
      {detail.isPending ? (
        <Notice>Loading specification…</Notice>
      ) : detail.isError ? (
        <Notice error>{detail.error.message}</Notice>
      ) : (
        <AppendVersion
          key={detail.data.agent_version_id}
          detail={detail.data}
          id={id}
          onSaved={(v) => {
            setCursor(undefined);
            setVersion(v);
          }}
        />
      )}
    </div>
  );
}
function AppendVersion({
  detail,
  id,
  onSaved,
}: {
  detail: Schema["AgentVersionResponse"];
  id: string;
  onSaved: (v: number) => void;
}) {
  const [json, setJson] = useState(JSON.stringify(detail.spec, null, 2));
  const [summary, setSummary] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  const { api, workspace } = useSession();
  const me = useMe();
  const mode = useMode();
  const client = useQueryClient();
  const canEdit = me.data?.permissions[workspace]?.includes("agent:update");
  const mutation = useMutation({
    mutationFn: async () => {
      const spec = JSON.parse(json) as Schema["AgentSpec"];
      if (spec.mode !== "paper")
        throw new Error("This editor only creates paper versions.");
      return unwrap(
        await api.POST(
          "/v1/workspaces/{workspace_id}/agents/{agent_id}/versions",
          {
            params: { path: { workspace_id: workspace, agent_id: id } },
            headers: { "Idempotency-Key": key },
            body: { spec, change_summary: summary, author_kind: "human" },
          },
        ),
      );
    },
    onSuccess: async (v) => {
      await client.invalidateQueries({ queryKey: [workspace] });
      onSaved(v.version);
    },
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <p className="chip">
        v{detail.version} · {detail.approval_status} · {detail.stage}
      </p>
      <p className="mono break">Spec hash: {detail.spec_hash}</p>
      <p className="mono break">Prompt hash: {detail.prompt_hash}</p>
      <label htmlFor="spec-json">Structured specification · JSON</label>
      <textarea
        className="spec-editor mono"
        id="spec-json"
        value={json}
        onChange={(e) => setJson(e.target.value)}
        readOnly={!canEdit || mutation.isError || mutation.isPending}
        spellCheck={false}
        maxLength={60000}
      />
      <label htmlFor="change-summary">Reason for this version</label>
      <input
        id="change-summary"
        required
        maxLength={2000}
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
        disabled={!canEdit || mutation.isError || mutation.isPending}
      />
      <p>
        <small>
          The server validates the full schema. Existing versions and historical
          decisions are never rewritten.
        </small>
      </p>
      {mutation.isError && (
        <Notice error>
          {mutation.error.message} Close and reopen to revise; retry preserves
          this request.
        </Notice>
      )}
      <Button
        type="submit"
        disabled={
          !canEdit ||
          mutation.isPending ||
          mode.isError ||
          mode.data?.default_trading_mode !== "paper" ||
          mode.data?.live_trading_enabled !== false
        }
      >
        {mutation.isPending
          ? "Saving version…"
          : mutation.isError
            ? "Retry same version"
            : "Save new draft version"}
      </Button>
      <RehearsalLauncher detail={detail} agentId={id} />
    </form>
  );
}
