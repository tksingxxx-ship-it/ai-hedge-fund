import { Link } from "react-router-dom";
import { Mode, Stat, money, pct, tone } from "../components";
import { useData } from "./data";

export function Executive() {
  const decisions = useData<{ decisions: Decision[] }>("/api/cio/decisions");
  const missions = useData<{ missions: Mission[] }>("/api/missions");
  const portfolio = useData<{ funds: Fund[]; note: string }>("/api/portfolio");
  const floor = useData<{ cio: Desk }>("/api/office/floor");
  const cio = floor.data?.cio;
  const latest = decisions.data?.decisions?.[0];
  return (
    <>
      <div className="grid stats">
        <Stat k="CIO state" v={cio?.state || "idle"} d="Office layer. Not a native analyst." />
        <Stat k="Missions" v={String(missions.data?.missions.length ?? "—")} d="Research tasks stored in the office database." />
        <Stat k="Paper funds" v={String(portfolio.data?.funds.length ?? "—")} d="Counts come from the engine ledger directories." />
        <Stat
          k="Latest proposal"
          v={latest ? "Recorded" : "None"}
          d={latest?.body || "No CIO decision has been stored."}
        />
      </div>
      <div className="grid two">
        <section className="panel">
          <h3>Decisions</h3>
          {!decisions.data?.decisions.length && <p className="empty">No decisions yet. Coordinate a mission from the research laboratory.</p>}
          {decisions.data?.decisions.map((row) => (
            <article key={row.id} className="finding">
              <div className="row">
                <strong>{row.kind}</strong>
                <Mode mode={row.execution_mode} />
              </div>
              <p>{row.body}</p>
              {row.payload?.final_weights && (
                <table>
                  <thead><tr><th>Symbol</th><th className="num">Final weight</th></tr></thead>
                  <tbody>
                    {Object.entries(row.payload.final_weights).map(([ticker, weight]) => (
                      <tr key={ticker}><td>{ticker}</td><td className="num">{pct(Number(weight))}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="empty">{row.payload?.note}</p>
            </article>
          ))}
        </section>
        <section className="panel">
          <h3>Books</h3>
          <p className="empty">{portfolio.data?.note}</p>
          {portfolio.data?.funds.map((fund) => (
            <Link key={fund.name} className="block" to={`/portfolio/${fund.name}`}>
              <div className="row">
                <strong>{fund.name}</strong>
                <Mode mode={fund.execution_mode} />
              </div>
              <div className="empty">
                NAV {money(fund.nav)} · sessions {fund.sessions ?? 0}
                {fund.halted ? ` · halted: ${fund.halted}` : ""}
              </div>
            </Link>
          ))}
          <div className="actions" style={{ marginTop: 12 }}>
            <Link to="/research">Open the research laboratory</Link>
          </div>
          {missions.error && <p className="error">{missions.error}</p>}
          {decisions.data?.decisions.some((d) => d.payload?.conflicts) && (
            <p className={tone(null) ? "" : "empty"}>Conflicts, when present, are listed on the decision payload and were not turned into orders.</p>
          )}
        </section>
      </div>
    </>
  );
}

interface Decision {
  id: string;
  kind: string;
  body: string;
  execution_mode: string;
  payload?: { final_weights?: Record<string, number>; note?: string; conflicts?: unknown };
}
interface Mission { id: string; title: string; status: string }
interface Fund { name: string; nav: number | null; sessions?: number; halted?: string | null; execution_mode: string }
interface Desk { state: string }
