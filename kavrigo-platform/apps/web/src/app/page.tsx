import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  CircleDashed,
  DatabaseZap,
  FileClock,
  Layers3,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";

export const metadata: Metadata = {
  title: "Kavrigo · Build AI trading agents you can test, inspect, and govern",
  description:
    "Kavrigo is a paper-first operating system for versioned AI trading agents, evidence-backed decisions, deterministic risk controls, and inspectable research.",
};

const steps = [
  {
    number: "01",
    title: "Specify the agent",
    description:
      "Set the assets, evidence requirements, decision horizon, and risk policy in a versioned AgentSpec.",
    icon: Layers3,
  },
  {
    number: "02",
    title: "Test the reasoning",
    description:
      "Rehearse against frozen evidence and inspect the decision, contradictions, and uncertainty.",
    icon: FileClock,
  },
  {
    number: "03",
    title: "Enforce the boundary",
    description:
      "Deterministic portfolio and risk checks decide whether an intent can reach the paper broker.",
    icon: ShieldCheck,
  },
];

function SignalMark({ size = 34 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M4 7h8l8 11-8 11H4M20 4v28M26 9h6M26 18h6M26 27h6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="4" cy="7" r="2" fill="currentColor" />
      <circle cx="4" cy="29" r="2" fill="currentColor" />
    </svg>
  );
}

export default function HomePage() {
  return (
    <div className="marketing">
      <a className="marketing-skip" href="#marketing-main">
        Skip to content
      </a>
      <header className="marketing-header">
        <Link className="marketing-brand" href="/" aria-label="Kavrigo home">
          <SignalMark />
          <span>KAVRIGO</span>
        </Link>
        <nav className="marketing-nav" aria-label="Site navigation">
          <a href="#how-it-works">How it works</a>
          <a href="#principles">Principles</a>
          <Link className="marketing-nav-app" href="/app">
            Open app <ArrowUpRight size={16} aria-hidden="true" />
          </Link>
        </nav>
      </header>

      <main id="marketing-main">
        <section className="marketing-hero" aria-labelledby="marketing-title">
          <div className="marketing-hero-copy">
            <div className="marketing-eyebrow">
              <span className="marketing-eyebrow-dot" />
              PAPER-FIRST · PRIVATE PREVIEW
            </div>
            <h1 id="marketing-title">
              Build AI trading agents you can{" "}
              <em>test, inspect, and govern.</em>
            </h1>
            <p>
              Kavrigo brings agent design, market research, backtesting, and
              deterministic risk controls into one evidence-first workspace.
              Every decision has a trail. Every trade starts in simulation.
            </p>
            <div className="marketing-actions">
              <Link className="marketing-primary" href="/app">
                Start in paper mode <ArrowRight size={19} aria-hidden="true" />
              </Link>
              <a className="marketing-secondary" href="#how-it-works">
                Explore the workflow{" "}
                <ArrowUpRight size={17} aria-hidden="true" />
              </a>
            </div>
            <div className="marketing-hero-note">
              <LockKeyhole size={16} aria-hidden="true" />
              Paper trading is simulated. No exchange credentials are needed.
            </div>
          </div>

          <div
            className="marketing-system"
            aria-label="Kavrigo decision workflow"
          >
            <div className="marketing-system-head">
              <span className="marketing-system-title">
                DECISION CONTROL PLANE
              </span>
              <span className="marketing-system-mode">PAPER · SIMULATED</span>
            </div>
            <div className="marketing-system-body">
              <div className="marketing-system-source">
                <span className="marketing-node-icon">
                  <DatabaseZap size={18} aria-hidden="true" />
                </span>
                <span>
                  <strong>Evidence snapshot</strong>
                  <small>Frozen context · source + freshness</small>
                </span>
                <CheckCircle2 size={17} aria-hidden="true" />
              </div>
              <div className="marketing-connector" aria-hidden="true" />
              <div className="marketing-system-source">
                <span className="marketing-node-icon">
                  <CircleDashed size={18} aria-hidden="true" />
                </span>
                <span>
                  <strong>Structured decision</strong>
                  <small>Rationale · uncertainty · abstention</small>
                </span>
                <CheckCircle2 size={17} aria-hidden="true" />
              </div>
              <div className="marketing-connector" aria-hidden="true" />
              <div className="marketing-system-source marketing-system-gate">
                <span className="marketing-node-icon">
                  <ShieldCheck size={18} aria-hidden="true" />
                </span>
                <span>
                  <strong>Deterministic risk gate</strong>
                  <small>Policy before any paper order intent</small>
                </span>
                <span className="marketing-gate-label">ENFORCED</span>
              </div>
              <div className="marketing-connector" aria-hidden="true" />
              <div className="marketing-system-output">
                <span>OUTCOME</span>
                <strong>Paper result or NO_TRADE</strong>
                <small>Both are valid decisions.</small>
              </div>
            </div>
            <div className="marketing-system-foot">
              <span>AGENT → PORTFOLIO → RISK → PAPER</span>
              <span>01 / 04</span>
            </div>
          </div>
        </section>

        <section className="marketing-promise" aria-label="Kavrigo principles">
          <span>VERSIONED AGENTS</span>
          <span>EVIDENCE-BACKED DECISIONS</span>
          <span>DETERMINISTIC RISK</span>
          <span>SIMULATED EXECUTION</span>
        </section>

        <section
          className="marketing-section marketing-process"
          id="how-it-works"
          aria-labelledby="how-title"
        >
          <div className="marketing-section-intro">
            <span className="marketing-kicker">THE WORKFLOW</span>
            <h2 id="how-title">
              Build the idea. Inspect the evidence. Keep control.
            </h2>
            <p>
              An agent can interpret context, but its output is never an order.
              Kavrigo makes the handoffs visible so you can review what happened
              before a simulated fill appears.
            </p>
          </div>
          <div className="marketing-step-grid">
            {steps.map(({ number, title, description, icon: Icon }) => (
              <article className="marketing-step" key={number}>
                <div className="marketing-step-top">
                  <span>{number} / 03</span>
                  <Icon size={22} aria-hidden="true" />
                </div>
                <h3>{title}</h3>
                <p>{description}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          className="marketing-section marketing-principles"
          id="principles"
          aria-labelledby="principles-title"
        >
          <div>
            <span className="marketing-kicker">BUILT TO BE QUESTIONED</span>
            <h2 id="principles-title">
              A trading agent should be inspectable.
            </h2>
          </div>
          <div className="marketing-principles-list">
            <p>
              <strong>Evidence over assertion.</strong> Supporting and
              contradicting inputs sit beside the decision.
            </p>
            <p>
              <strong>Risk outside the model.</strong> Prompts cannot change
              account limits or bypass deterministic checks.
            </p>
            <p>
              <strong>Uncertainty is useful.</strong> NO_TRADE and UNKNOWN are
              valid outcomes when the data does not support action.
            </p>
          </div>
        </section>

        <section
          className="marketing-final"
          aria-labelledby="marketing-final-title"
        >
          <SignalMark size={44} />
          <div>
            <span className="marketing-kicker">KAVRIGO WORKSPACE</span>
            <h2 id="marketing-final-title">
              Build agents. Prove the edge. Enforce the risk.
            </h2>
            <p>Explore the paper workspace and its current research tools.</p>
          </div>
          <Link className="marketing-primary" href="/app">
            Open paper workspace <ArrowRight size={19} aria-hidden="true" />
          </Link>
        </section>
      </main>

      <footer className="marketing-footer">
        <span>KAVRIGO © {new Date().getUTCFullYear()}</span>
        <span>
          Paper results are simulated and do not predict future performance.
        </span>
        <Link href="/app">Open app</Link>
      </footer>
    </div>
  );
}
