import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, money } from "../api";
import { ErrorText, Mode } from "../components";
import { useData } from "./data";

interface Mandate { name: string; error?: string | null }
interface Fund {
  name: string; mandate?: string; universe?: string[]; capital?: number; rebalance?: string;
  execution_mode: string; fixture?: boolean; sessions?: number; last_session?: string | null;
  nav?: number | null; halted?: string | null; error?: string;
}
interface Plan {
  runnable: boolean; action?: string | null; session?: string | null; reason?: string | null;
  fixture?: boolean; execution_mode?: string; halted?: string | null; nav?: number | null;
  pending_weights?: Record<string, number> | null; plan_hash?: string;
}
interface SessionRow { session: string; nav: number; rebalance: boolean }

export function Paper() {
  const mandates = useData<{ mandates: Mandate[] }>("/api/mandates");
  const funds = useData<{ funds: Fund[] }>("/api/paper/funds");
  const health = useData<{ fixtures_allowed: boolean }>("/api/health");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState("");
  useEffect(() => {
    if (health.data) setMode((current) => current || (health.data!.fixtures_allowed ? "fixture" : "live"));
  }, [health.data]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/paper/funds", {
        method: "POST",
        body: JSON.stringify({
          name: String(form.get("name")),
          mandate_name: String(form.get("mandate")),
          tickers: String(form.get("tickers") || "").split(/[\s,]+/).filter(Boolean),
          execution_mode: String(form.get("mode")),
          max_symbols: 30,
        }),
      });
      funds.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "deploy failed");
    }
  }

  return (
    <>
      <ErrorText error={error} />
      <div className="banner info">Deploying a fund does not run a session. Each session needs its own approval. The kill switch is the engine ledger, not a button that only hides the UI.</div>
      <div className="grid two">
        <form className="panel stack" onSubmit={onSubmit}>
          <h3>Deploy</h3>
          <label>Name<input name="name" required placeholder="alpha" /></label>
          <label>Mandate
            <select name="mandate" required>
              <option value="">Select</option>
              {mandates.data?.mandates.filter((row) => !row.error).map((row) => <option key={row.name}>{row.name}</option>)}
            </select>
          </label>
          <label>Symbols<input name="tickers" required placeholder="AAPL MSFT" /></label>
          <label>Execution
            <select name="mode" value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="live">live</option>
              {health.data?.fixtures_allowed && <option value="fixture">fixture</option>}
            </select>
          </label>
          <button className="primary" type="submit">Deploy paper fund</button>
        </form>
        <section className="panel">
          <h3>Funds</h3>
          {!funds.data?.funds.length && <p className="empty">No paper funds in this office root.</p>}
          {funds.data?.funds.map((fund) => (
            <Link key={fund.name} to={`/paper/${fund.name}`} className="block">
              <div className="row"><strong>{fund.name}</strong><Mode mode={fund.execution_mode} /></div>
              <div className="empty">{fund.error || `${fund.sessions ?? 0} sessions · NAV ${fund.nav == null ? "unmarked" : money(fund.nav)}`}</div>
            </Link>
          ))}
        </section>
      </div>
    </>
  );
}

export function PaperFund() {
  const { name = "" } = useParams();
  const plan = useData<Plan>(`/api/paper/funds/${name}/plan`);
  const sessions = useData<{ sessions: SessionRow[]; events: { time?: string; kind?: string; reason?: string }[] }>(`/api/paper/funds/${name}/sessions`);
  const [approval, setApproval] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [record, setRecord] = useState<string | null>(null);

  async function approve() {
    setError(null);
    try {
      const body = await api<{ id: string }>(`/api/paper/funds/${name}/approvals`, {
        method: "POST",
        body: JSON.stringify({ action: plan.data?.action }),
      });
      setApproval(body.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "approval failed");
    }
  }

  async function run() {
    if (!approval) return;
    setError(null);
    try {
      const body = await api<{ record: { session: string; nav: number; fixture: boolean } }>(`/api/paper/funds/${name}/tick`, {
        method: "POST",
        body: JSON.stringify({ approval_id: approval }),
      });
      setRecord(`${body.record.session} NAV ${money(body.record.nav)}${body.record.fixture ? " (fixture)" : ""}`);
      setApproval(null);
      plan.load();
      sessions.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "tick failed");
    }
  }

  async function halt() {
    const reason = window.prompt("Halt reason");
    if (!reason) return;
    await api(`/api/paper/funds/${name}/halt`, { method: "POST", body: JSON.stringify({ reason }) });
    plan.load();
  }

  async function resume() {
    await api(`/api/paper/funds/${name}/resume`, { method: "POST" });
    plan.load();
  }

  return (
    <>
      <ErrorText error={error || plan.error} />
      {plan.data?.fixture && <div className="banner">Plan prices come from the fixture client.</div>}
      <section className="panel stack">
        <h3>Next session</h3>
        <p>{plan.data?.reason || "Loading plan…"}</p>
        <p className="empty">Action {plan.data?.action || "—"} · session {plan.data?.session || "—"} · hash {plan.data?.plan_hash?.slice(0, 12) || "—"}</p>
        {plan.data?.pending_weights && <p className="empty">Pending weights {JSON.stringify(plan.data.pending_weights)}</p>}
        <div className="actions">
          <button className="primary" disabled={!plan.data?.runnable} onClick={approve}>Approve this plan</button>
          <button className="primary" disabled={!approval} onClick={run}>Run approved session</button>
          <button className="danger" onClick={halt}>Halt</button>
          <button className="ghost" onClick={resume}>Resume</button>
        </div>
        {approval && <p className="empty">Approval {approval} is unused until you run it. Refreshing the plan after the market moves will make it stale.</p>}
        {record && <p>Recorded {record}</p>}
      </section>
      <section className="panel">
        <h3>Ledger</h3>
        {!sessions.data?.sessions.length && <p className="empty">No sessions recorded.</p>}
        <table>
          <tbody>
            {sessions.data?.sessions.map((row) => (
              <tr key={row.session}><td><Link to={`/paper/${name}/sessions/${row.session}`}>{row.session}</Link></td><td className="num">{money(row.nav)}</td><td>{row.rebalance ? "rebalance" : "mark"}</td></tr>
            ))}
          </tbody>
        </table>
        <h3>Engine events</h3>
        {sessions.data?.events.map((event, index) => (
          <div key={index} className="empty">{event.time} · {event.kind} {event.reason || ""}</div>
        ))}
      </section>
    </>
  );
}

export function SessionPage() {
  const { name = "", session = "" } = useParams();
  const { data, error } = useData<Record<string, unknown>>(`/api/paper/funds/${name}/sessions/${session}`);
  if (error) return <div className="banner danger">{error}</div>;
  if (!data) return <p className="empty">Loading session…</p>;
  return (
    <section className="panel">
      <h3>Session record</h3>
      {data.fixture === true && <div className="banner">Fixture execution.</div>}
      <pre className="mono">{JSON.stringify(data, null, 2)}</pre>
    </section>
  );
}
