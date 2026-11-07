import { FormEvent, useState } from "react";
import { api } from "../api";
import { ErrorText } from "../components";
import { useData } from "./data";

interface Strategy { name: string; display_name: string; description: string; blend: { mode: string }; models: { name: string; weight: number }[] }
interface Mandate { name: string; error?: string | null; spec?: { capital: number; rebalance: string; strategies: { name: string }[] } | null }

export function Strategies() {
  const library = useData<{ strategies: Strategy[] }>("/api/strategies");
  const mandates = useData<{ mandates: Mandate[] }>("/api/mandates");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaved(null);
    const form = new FormData(event.currentTarget);
    try {
      const body = await api<{ path: string }>("/api/mandates", {
        method: "POST",
        body: JSON.stringify({
          name: String(form.get("name")),
          strategies: form.getAll("strategy").map(String),
          capital: Number(form.get("capital")),
          rebalance: String(form.get("rebalance")),
          benchmark: String(form.get("benchmark") || "SPY"),
        }),
      });
      setSaved(body.path);
      mandates.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save failed");
    }
  }

  return (
    <>
      <ErrorText error={error || library.error} />
      {saved && <div className="banner info">Saved {saved}. The CLI can read this mandate.</div>}
      <div className="grid two">
        <section className="panel">
          <h3>Native library</h3>
          {library.data?.strategies.map((strategy) => (
            <article key={strategy.name} className="finding">
              <strong>{strategy.display_name}</strong>
              <p className="empty">{strategy.description}</p>
              <p>{strategy.blend.mode} · {strategy.models.map((model) => `${model.name}×${model.weight}`).join(", ")}</p>
            </article>
          ))}
        </section>
        <form className="panel stack" onSubmit={onSubmit}>
          <h3>Assemble a mandate</h3>
          <label>Name<input name="name" required placeholder="swing-desk" /></label>
          <div className="checks">
            {library.data?.strategies.map((strategy) => (
              <label key={strategy.name}><input type="checkbox" name="strategy" value={strategy.name} /> {strategy.display_name}</label>
            ))}
          </div>
          <label>Capital<input name="capital" type="number" defaultValue={100000} /></label>
          <label>Rebalance<select name="rebalance" defaultValue="weekly"><option>daily</option><option>weekly</option><option>monthly</option></select></label>
          <label>Benchmark<input name="benchmark" defaultValue="SPY" /></label>
          <button className="primary" type="submit">Save mandate</button>
          <p className="empty">Risk defaults match the example mandate: 25% position, 100% gross, 10% halve, 20% stop. Saving does not deploy a fund.</p>
          <h3>Saved</h3>
          {!mandates.data?.mandates.length && <p className="empty">No mandates in the office mandate directory.</p>}
          {mandates.data?.mandates.map((mandate) => (
            <div key={mandate.name} className="finding">
              <strong>{mandate.name}</strong>
              {mandate.error && <p className="error">{mandate.error}</p>}
              {mandate.spec && <p className="empty">{mandate.spec.rebalance} · {mandate.spec.strategies.map((s) => s.name).join(", ")}</p>}
            </div>
          ))}
        </form>
      </div>
    </>
  );
}
