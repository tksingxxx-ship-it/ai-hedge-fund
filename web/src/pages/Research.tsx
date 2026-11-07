import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorText, Mode } from "../components";
import { pct, signed } from "../api";
import { useData } from "./data";

interface Strategy { name: string; display_name: string; description: string; models: { name: string }[] }
interface Preset { id: string; name: string; as_of: string; count: number; survivorship_warning: string; source: string; note: string }
interface Mission {
  id: string; title: string; status: string; as_of: string; execution_mode: string; fixture: boolean;
  universe: string[]; brief: string; summary?: Summary | null; error?: string | null;
  tasks?: Task[];
}
interface Task {
  id: string; agent: string; ticker?: string; kind: string; status: string; strategy?: string;
  result?: { signal?: { value: number; reasoning?: string }; data?: { source?: string; price?: number | null; as_of?: string; coverage?: string }; fixture?: boolean };
  payload?: { conflicts?: { agent: string; value: number; reasoning?: string }[] };
}
interface Summary {
  proposal?: { final_weights?: Record<string, number>; note?: string; orders_placed?: boolean; clamps?: { limit: string; ticker?: string | null }[] };
  conflicts?: { conflicts?: { agent: string; value: number }[] }[];
  completed?: number; failed?: number;
}

export function Research() {
  const strategies = useData<{ strategies: Strategy[] }>("/api/strategies");
  const universes = useData<{ presets: Preset[] }>("/api/universes");
  const missions = useData<{ missions: Mission[] }>("/api/missions");
  const health = useData<{ completed_through: string; fixtures_allowed: boolean }>("/api/health");
  const [error, setError] = useState<string | null>(null);
  const [presetOn, setPresetOn] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [mode, setMode] = useState("");
  useEffect(() => {
    if (!health.data) return;
    setAsOf((current) => current || health.data!.completed_through);
    setMode((current) => current || (health.data!.fixtures_allowed ? "fixture" : "live"));
  }, [health.data]);
  const preset = universes.data?.presets[0];

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const selected = form.getAll("strategy").map(String);
    try {
      await api("/api/cio/coordinate", {
        method: "POST",
        body: JSON.stringify({
          title: String(form.get("title") || "Research mission"),
          brief: String(form.get("brief") || ""),
          strategies: selected,
          tickers: String(form.get("tickers") || "").split(/[\s,]+/).filter(Boolean),
          preset: presetOn ? preset?.id : null,
          as_of: String(form.get("as_of")),
          execution_mode: String(form.get("mode")),
          rebalance: String(form.get("rebalance")),
          capital: Number(form.get("capital") || 100000),
          max_calls: Number(form.get("max_calls") || 24),
          max_symbols: Number(form.get("max_symbols") || 20),
          timeout_seconds: Number(form.get("timeout") || 180),
        }),
      });
      missions.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed");
    }
  }

  return (
    <>
      <ErrorText error={error || strategies.error} />
      <div className="grid two">
        <form className="panel stack" onSubmit={onSubmit}>
          <h3>New mission</h3>
          <label>Title<input name="title" required placeholder="US swing review" /></label>
          <label>Brief<textarea name="brief" placeholder="What should the desk look at?" /></label>
          <div className="checks">
            {strategies.data?.strategies.map((strategy) => (
              <label key={strategy.name}><input type="checkbox" name="strategy" value={strategy.name} /> {strategy.display_name}</label>
            ))}
          </div>
          <label>Symbols<input name="tickers" placeholder="AAPL MSFT NVDA" /></label>
          <label className="checks"><input type="checkbox" checked={presetOn} onChange={(e) => setPresetOn(e.target.checked)} /> Use {preset?.name || "preset"}</label>
          {presetOn && preset && <div className="banner">{preset.survivorship_warning} Source: {preset.source} Snapshot {preset.as_of}. {preset.count} symbols. {preset.note}</div>}
          <label>As of<input name="as_of" required value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label>
          <label>Rebalance
            <select name="rebalance" defaultValue="weekly"><option>daily</option><option>weekly</option><option>monthly</option></select>
          </label>
          <label>Capital<input name="capital" type="number" defaultValue={100000} /></label>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
            <label>Max calls<input name="max_calls" type="number" defaultValue={24} /></label>
            <label>Max symbols<input name="max_symbols" type="number" defaultValue={20} /></label>
            <label>Timeout s<input name="timeout" type="number" defaultValue={180} /></label>
          </div>
          <label>Execution
            <select name="mode" value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="live">live</option>
              {health.data?.fixtures_allowed && <option value="fixture">fixture</option>}
            </select>
          </label>
          <button className="primary" type="submit">Run native analysts</button>
          <p className="empty">This dispatches the registry analysts. It does not place an order.</p>
        </form>
        <section className="panel">
          <h3>Missions</h3>
          {!missions.data?.missions.length && <p className="empty">No missions stored.</p>}
          {missions.data?.missions.map((mission) => (
            <Link key={mission.id} to={`/research/${mission.id}`} className="block">
              <div className="row"><strong>{mission.title}</strong><Mode mode={mission.execution_mode} /></div>
              <div className="empty">{mission.status} · {mission.as_of} · {mission.universe.length} symbols</div>
            </Link>
          ))}
        </section>
      </div>
    </>
  );
}

export function MissionPage() {
  const { id = "" } = useParams();
  const { data, error } = useData<Mission>(`/api/missions/${id}`);
  if (error) return <div className="banner danger">{error}</div>;
  if (!data) return <p className="empty">Loading mission…</p>;
  const weights = data.summary?.proposal?.final_weights || {};
  return (
    <>
      <div className="row">
        <h3 style={{ margin: 0 }}>{data.title}</h3>
        <Mode mode={data.execution_mode} />
        <span className="tag">{data.status}</span>
      </div>
      {data.fixture && <div className="banner">This mission ran in fixture mode.</div>}
      {data.error && <div className="banner danger">{data.error}</div>}
      <p>{data.brief || "No brief."} As of {data.as_of}. Universe {data.universe.join(", ")}.</p>
      <section className="panel">
        <h3>Proposal</h3>
        <p className="empty">{data.summary?.proposal?.note || "No proposal stored."}</p>
        <p>Orders placed: {String(data.summary?.proposal?.orders_placed ?? false)}. Completed tasks {data.summary?.completed ?? "—"}, failed {data.summary?.failed ?? "—"}.</p>
        {!!Object.keys(weights).length && (
          <table>
            <thead><tr><th>Symbol</th><th className="num">Final weight</th></tr></thead>
            <tbody>
              {Object.entries(weights).map(([ticker, weight]) => (
                <tr key={ticker}><td>{ticker}</td><td className="num">{pct(weight)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="panel">
        <h3>Findings</h3>
        {data.tasks?.filter((task) => task.kind === "analyze").map((task) => (
          <Link key={task.id} to={`/tasks/${task.id}`} className="block">
            <div className="row">
              <strong>{task.agent} · {task.ticker}</strong>
              <span>{task.result?.signal ? signed(task.result.signal.value) : task.status}</span>
            </div>
            <div className="empty">{task.result?.signal?.reasoning || task.status}</div>
          </Link>
        ))}
        <h3>Conflicts escalated to the CIO</h3>
        {!data.tasks?.some((task) => task.kind === "challenge") && <p className="empty">No sign conflict above the band.</p>}
        {data.tasks?.filter((task) => task.kind === "challenge").map((task) => (
          <div key={task.id} className="finding">
            <Link to={`/tasks/${task.id}`}>{task.ticker}</Link>
            <div className="empty">{task.payload?.conflicts?.map((row) => `${row.agent} ${signed(row.value)}`).join(" · ")}</div>
          </div>
        ))}
      </section>
    </>
  );
}
