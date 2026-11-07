import { Link, useParams } from "react-router-dom";
import { Chart, Mode, Stat, money, pct, tone } from "../components";
import { useData } from "./data";

interface Row { name: string; nav: number | null; capital?: number; last_session?: string | null; halted?: string | null; execution_mode: string; sessions?: number; error?: string }
interface Book {
  name: string; mandate: string; execution_mode: string; fixture: boolean; capital: number;
  nav: number | null; nav_is_marked: boolean; cash: number | null; total_pnl: number | null;
  realized_pnl: number | null; unrealized_pnl: number | null; trading_cost: number | null;
  pnl_reconstruction?: string; halted?: string | null; ledger_error?: string | null; mismatch?: string | null;
  last_session?: string | null; sessions: number; marks_note?: string; marks_as_of?: string;
  definitions: Record<string, string>;
  positions: { ticker: string; shares: number; mark: number | null; market_value: number | null }[];
  daily_returns: { session: string; nav: number; return: number | null }[];
  exposure?: { gross: number; net: number; as_of: string } | null;
  drawdown?: { max: number; as_of: string } | null;
  metrics?: Record<string, number> | null;
  metrics_source?: string;
  scorecard?: { analysts: Analyst[]; strategies: Sleeve[]; fund_pnl: number } | null;
  scorecard_source?: string | null;
  allocation?: { strategies?: { name: string; slice: number }[]; final_weights?: Record<string, number>; source?: string };
  allocation_source?: string;
  benchmark: string;
  factor_exposures?: { book_beta: number; book_volatility: number; benchmark: string; benchmark_volatility: number; sector_nets: Record<string, number>; source: string; fixture: boolean } | null;
  factor_exposures_error?: string | null;
}
interface Analyst { name: string; hit_rate: number | null; n_views: number; ic_mean: number | null; n_dates: number }
interface Sleeve { name: string; pnl: number; return_pct: number; n_periods: number }

export function PortfolioList() {
  const { data, error } = useData<{ funds: Row[]; note: string }>("/api/portfolio");
  return (
    <>
      {error && <div className="banner danger">{error}</div>}
      <p className="empty">{data?.note}</p>
      <div className="grid cards">
        {data?.funds.map((fund) => (
          <Link key={fund.name} to={`/portfolio/${fund.name}`} className="desk">
            <header><div className="who">{fund.name}</div><Mode mode={fund.execution_mode} /></header>
            {fund.error ? <p className="error">{fund.error}</p> : (
              <>
                <div className="v" style={{ fontFamily: "var(--mono)", fontSize: 22 }}>{fund.nav == null ? "Unmarked" : money(fund.nav)}</div>
                <p className="empty">{fund.sessions || 0} sessions · last {fund.last_session || "none"}{fund.halted ? ` · halted` : ""}</p>
              </>
            )}
          </Link>
        ))}
      </div>
    </>
  );
}

export function PortfolioBook() {
  const { name = "" } = useParams();
  const { data, error } = useData<Book>(`/api/portfolio/${name}`);
  if (error) return <div className="banner danger">{error}</div>;
  if (!data) return <p className="empty">Loading book…</p>;
  const nav = data.daily_returns.map((row) => row.nav);
  return (
    <>
      {data.fixture && <div className="banner">Fixture-backed ledger. Marks are the fixture series, not the market.</div>}
      {data.ledger_error && <div className="banner danger">{data.ledger_error}</div>}
      {data.mismatch && <div className="banner danger">{data.mismatch}</div>}
      <div className="row"><h3 style={{ margin: 0 }}>{data.name}</h3><Mode mode={data.execution_mode} /><span className="tag">benchmark {data.benchmark}</span><span className="tag">{data.halted ? `halted: ${data.halted}` : "kill switch off"}</span></div>
      <div className="grid stats">
        <Stat k="NAV" v={data.nav_is_marked ? money(data.nav) : money(data.capital)} d={data.nav_is_marked ? data.definitions.nav : "Deployed capital. No session has been marked."} />
        <Stat k="Total P&L" v={money(data.total_pnl)} tone={tone(data.total_pnl)} d={data.definitions.total_pnl} />
        <Stat k="Drawdown" v={data.drawdown ? pct(data.drawdown.max) : "—"} d={data.definitions.drawdown} />
        <Stat k="Gross / net" v={data.exposure ? `${pct(data.exposure.gross)} / ${pct(data.exposure.net)}` : "—"} d={data.definitions.exposure} />
      </div>
      <section className="panel">
        <h3>Equity vs benchmark</h3>
        <Chart nav={nav} />
        <p className="empty">{data.marks_note || "No marks."} {data.marks_as_of || ""} {data.metrics_source || ""}</p>
        {data.metrics && (
          <p className="mono">
            total {pct(data.metrics.total_return_pct)} · benchmark {pct(data.metrics.benchmark_return_pct)} · excess {pct(data.metrics.excess_return_pct)} · sharpe {data.metrics.sharpe_ratio} · max DD {pct(data.metrics.max_drawdown_pct)}
          </p>
        )}
      </section>
      <div className="grid two">
        <section className="panel">
          <h3>Positions</h3>
          <p className="empty">Cash {money(data.cash)}. Realized {money(data.realized_pnl)}. Unrealized {money(data.unrealized_pnl)}. Costs {money(data.trading_cost)}. {data.pnl_reconstruction || ""}</p>
          {!data.positions.length && <p className="empty">No positions on the latest record.</p>}
          {!!data.positions.length && (
            <table>
              <thead><tr><th>Symbol</th><th className="num">Shares</th><th className="num">Mark</th><th className="num">Value</th></tr></thead>
              <tbody>
                {data.positions.map((row) => (
                  <tr key={row.ticker}><td>{row.ticker}</td><td className="num">{row.shares}</td><td className="num">{row.mark ?? "—"}</td><td className="num">{money(row.market_value)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="panel">
          <h3>Factor exposures</h3>
          {data.factor_exposures ? (
            <p className="empty">
              {data.factor_exposures.source}. Beta {data.factor_exposures.book_beta.toFixed(2)} vs {data.factor_exposures.benchmark}.
              Benchmark vol {pct(data.factor_exposures.benchmark_volatility)}. Book vol {pct(data.factor_exposures.book_volatility)}.
              Sectors {Object.entries(data.factor_exposures.sector_nets).map(([k, v]) => `${k} ${pct(v)}`).join(", ") || "none"}.
              {data.factor_exposures.fixture ? " Fixture prices." : ""}
            </p>
          ) : <p className="empty">{data.factor_exposures_error || "Not computed."}</p>}
          <h3>Allocation</h3>
          <p className="empty">{data.allocation_source}</p>
          {(data.allocation?.strategies || []).map((row) => (
            <div key={row.name} className="row"><span>{row.name}</span><span className="mono">{pct(row.slice)}</span></div>
          ))}
          {data.scorecard ? (
            <>
              <h3>Scorecard</h3>
              <p className="empty">{data.scorecard_source}. Fund P&L in the scorecard window {money(data.scorecard.fund_pnl)}.</p>
              <table>
                <thead><tr><th>Analyst</th><th className="num">Hit</th><th className="num">Views</th><th className="num">IC</th></tr></thead>
                <tbody>
                  {data.scorecard.analysts.map((row) => (
                    <tr key={row.name}><td>{row.name}</td><td className="num">{row.hit_rate == null ? "—" : pct(row.hit_rate)}</td><td className="num">{row.n_views}</td><td className="num">{row.ic_mean == null ? "—" : row.ic_mean.toFixed(2)}</td></tr>
                  ))}
                </tbody>
              </table>
              {data.scorecard.strategies.map((row) => (
                <div key={row.name} className="empty">{row.name}: {money(row.pnl)} over {row.n_periods} periods ({pct(row.return_pct)})</div>
              ))}
            </>
          ) : <p className="empty">No scorecard. The engine needs recorded sessions before it will grade anyone.</p>}
        </section>
      </div>
    </>
  );
}
