import { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { money, pct } from "./api";

export const NAV = [
  ["/", "Executive Office"],
  ["/agents", "Agent Directory"],
  ["/office", "Virtual Office"],
  ["/research", "Research Laboratory"],
  ["/strategies", "Investment Strategies"],
  ["/portfolio", "Portfolio Management"],
  ["/backtests", "Backtesting"],
  ["/paper", "Paper Trading"],
  ["/comms", "Agent Communications"],
  ["/audit", "Activity & Audit Log"],
  ["/settings", "Settings"],
] as const;

const TITLES: Record<string, string> = Object.fromEntries(NAV);

export function Shell({ health, children }: { health: Health | null; children: ReactNode }) {
  const { pathname } = useLocation();
  const base = "/" + pathname.split("/").filter(Boolean)[0];
  const title = TITLES[pathname] || TITLES[base] || "Virtual Office";
  return (
    <div className="shell">
      <aside className="nav">
        <div className="brand">
          <div className="mark">AIHF</div>
          <h1>Virtual Office</h1>
          <p>Engine desk, not a mock book</p>
        </div>
        <div className="items">
          {NAV.map(([href, label], index) => (
            <NavLink key={href} to={href} end={href === "/"} className={({ isActive }) => `item${isActive ? " active" : ""}`}>
              <span className="idx">{String(index + 1).padStart(2, "0")}</span>
              {label}
            </NavLink>
          ))}
        </div>
        <div className="foot">
          {health ? `Engine ${health.engine_version}` : "Connecting…"}
          <div>Live brokers off</div>
        </div>
      </aside>
      <section className="main">
        <header className="top">
          <div>
            <h2>{title}</h2>
            <div className="sub">Completed sessions through {health?.completed_through || "—"}</div>
          </div>
          <div className="actions">
            {health?.fixture_only && <span className="tag fixture">FIXTURE ONLY</span>}
            {!health?.fixture_only && health?.fixtures_allowed && <span className="tag fixture">FIXTURES ENABLED</span>}
            <span className={`tag ${!health?.fixture_only && health?.data_configured ? "live" : ""}`}>
              {health?.fixture_only ? "EXTERNAL CALLS OFF" : health?.data_configured ? "DATA KEY SET" : "DATA KEY MISSING"}
            </span>
          </div>
        </header>
        <div className="content">
          {health?.fixture_only && (
            <div className="banner">
              Fixture-only preview. Live market data and model calls are disabled, and inherited API keys are not used.
              Tagged fixture results are the engine on synthetic prices and canned model text, not a provider or a live print.
            </div>
          )}
          {!health?.fixture_only && health?.fixtures_allowed && (
            <div className="banner">
              Fixture mode is enabled for this process. Anything tagged fixture is the real engine running on
              synthetic prices and canned model text. It is not a market print and not a provider response.
            </div>
          )}
          {children}
        </div>
      </section>
    </div>
  );
}

export interface Health {
  status: string;
  engine_version: string;
  fixtures_allowed: boolean;
  fixture_only?: boolean;
  live_brokers_enabled: boolean;
  data_configured: boolean;
  master_key_configured: boolean;
  completed_through: string;
}

export function Stat({ k, v, d, tone }: { k: string; v: string; d?: string; tone?: "pos" | "neg" }) {
  return (
    <div className="panel stat">
      <div className="k">{k}</div>
      <div className={`v ${tone || ""}`}>{v}</div>
      {d && <div className="d">{d}</div>}
    </div>
  );
}

export function Mode({ mode }: { mode?: string | null }) {
  if (!mode) return null;
  return <span className={`tag ${mode === "fixture" ? "fixture" : mode === "live" ? "live" : ""}`}>{mode}</span>;
}

export function Lamp({ state }: { state?: string }) {
  return <span className={`lamp ${state || "idle"}`} title={state || "idle"} />;
}

export function Chart({ nav, bench }: { nav: number[]; bench?: number[] }) {
  if (!nav?.length) return <p className="empty">No marked curve yet.</p>;
  const width = 680;
  const height = 200;
  const pad = 16;
  const all = bench && bench.length === nav.length ? [...nav, ...bench] : nav;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const x = (i: number) => pad + (i * (width - pad * 2)) / Math.max(nav.length - 1, 1);
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2);
  const path = (series: number[]) => series.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart" role="img" aria-label="Equity curve">
      <path d={path(nav)} className="nav" />
      {bench && bench.length === nav.length && <path d={path(bench)} className="bench" />}
    </svg>
  );
}

export function tone(value: number | null | undefined): "pos" | "neg" | undefined {
  if (value == null || value === 0) return undefined;
  return value > 0 ? "pos" : "neg";
}

export function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="banner danger">{error}</div>;
}

export { money, pct };
