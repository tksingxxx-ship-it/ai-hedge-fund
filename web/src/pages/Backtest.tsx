import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Chart, ErrorText, Mode } from "../components";
import { pct } from "../api";
import { useData } from "./data";

interface Mandate { name: string; error?: string | null }
interface Job {
  id: string; status: string; execution_mode: string; fixture: boolean; error?: string | null;
  progress?: { sessions?: number; total?: number; nav?: number } | null;
  result?: {
    start: string; end: string; rebalance: string; metrics: Record<string, number>;
    metrics_source: string; nav: number[]; benchmark_nav: number[]; dates: string[];
    n_records: number; path: string;
    decisions: { session: string; nav: number; orders: number; final_weights: Record<string, number> | null }[];
  } | null;
}

export function Backtests() {
  const mandates = useData<{ mandates: Mandate[] }>("/api/mandates");
  const jobs = useData<{ backtests: Job[] }>("/api/backtests");
  const health = useData<{ completed_through: string; fixtures_allowed: boolean }>("/api/health");
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
      await api("/api/backtests", {
        method: "POST",
        body: JSON.stringify({
          mandate_name: String(form.get("mandate")),
          tickers: String(form.get("tickers") || "").split(/[\s,]+/).filter(Boolean),
          start: String(form.get("start")),
          end: String(form.get("end")),
          execution_mode: String(form.get("mode")),
          max_symbols: Number(form.get("max_symbols") || 30),
          idempotency_key: String(form.get("idempotency") || "") || null,
        }),
      });
      jobs.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "backtest failed");
    }
  }

  return (
    <>
      <ErrorText error={error} />
      <div className="grid two">
        <form className="panel stack" onSubmit={onSubmit}>
          <h3>Run backtest_fund</h3>
          <label>Mandate
            <select name="mandate" required>
              <option value="">Select</option>
              {mandates.data?.mandates.filter((row) => !row.error).map((row) => <option key={row.name}>{row.name}</option>)}
            </select>
          </label>
          <label>Symbols<input name="tickers" required placeholder="AAPL MSFT" /></label>
          <label>Start<input name="start" required defaultValue="2024-06-03" /></label>
          <label>End<input name="end" required defaultValue="2024-06-21" /></label>
          <p className="empty">Latest completed session is {health.data?.completed_through || "unknown"}. Keep the window short unless you mean to replay it.</p>
          <label>Max symbols<input name="max_symbols" type="number" defaultValue={30} /></label>
          <label>Idempotency key<input name="idempotency" placeholder="optional" /></label>
          <label>Execution
            <select name="mode" value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="live">live</option>
              {health.data?.fixtures_allowed && <option value="fixture">fixture</option>}
            </select>
          </label>
          <button className="primary" type="submit">Run historical job</button>
          <p className="empty">Uses hedge_fund.backtesting.backtest_fund. A long window is capped by the office. The CLI is not.</p>
        </form>
        <section className="panel">
          <h3>Jobs</h3>
          {!jobs.data?.backtests.length && <p className="empty">No backtests stored.</p>}
          {jobs.data?.backtests.map((job) => (
            <Link key={job.id} to={`/backtests/${job.id}`} className="block">
              <div className="row"><strong>{job.status}</strong><Mode mode={job.execution_mode} /></div>
              <div className="empty">{job.result ? `${job.result.start} → ${job.result.end}` : job.error || "in progress"}</div>
            </Link>
          ))}
        </section>
      </div>
    </>
  );
}

export function BacktestJob() {
  const { id = "" } = useParams();
  const { data, error, load } = useData<Job>(`/api/backtests/${id}`);
  if (error) return <div className="banner danger">{error}</div>;
  if (!data) return <p className="empty">Loading job…</p>;
  return (
    <>
      <div className="row"><h3 style={{ margin: 0 }}>{data.status}</h3><Mode mode={data.execution_mode} /></div>
      {data.fixture && <div className="banner">Fixture inputs. The curve is the engine's, the prices are not.</div>}
      {data.error && <div className="banner danger">{data.error}</div>}
      {data.progress && <p className="empty">Progress {data.progress.sessions ?? 0} / {data.progress.total ?? "?"} · last NAV {data.progress.nav ?? "—"}</p>}
      {data.status === "running" && <button className="danger" onClick={async () => { await api(`/api/backtests/${id}/cancel`, { method: "POST" }); load(); }}>Cancel</button>}
      {data.result && (
        <section className="panel">
          <h3>{data.result.rebalance} · {data.result.n_records} sessions</h3>
          <Chart nav={data.result.nav} bench={data.result.benchmark_nav} />
          <p className="mono">
            total {pct(data.result.metrics.total_return_pct)} · benchmark {pct(data.result.metrics.benchmark_return_pct)} · sharpe {data.result.metrics.sharpe_ratio} · max DD {pct(data.result.metrics.max_drawdown_pct)}
          </p>
          <p className="empty">{data.result.metrics_source}. File {data.result.path}</p>
          <table>
            <thead><tr><th>Session</th><th className="num">NAV</th><th className="num">Orders</th><th>Targets</th></tr></thead>
            <tbody>
              {data.result.decisions.filter((row) => row.final_weights || row.orders).map((row) => (
                <tr key={row.session}>
                  <td>{row.session}</td>
                  <td className="num">{row.nav.toFixed(2)}</td>
                  <td className="num">{row.orders}</td>
                  <td className="empty">{row.final_weights ? Object.entries(row.final_weights).map(([t, w]) => `${t} ${pct(w)}`).join(", ") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
