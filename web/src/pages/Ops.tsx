import { FormEvent, useState } from "react";
import { api } from "../api";
import { ErrorText, Mode } from "../components";
import { useData } from "./data";

export function Comms() {
  const messages = useData<{ messages: Message[] }>("/api/messages");
  const [error, setError] = useState<string | null>(null);
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/messages", { method: "POST", body: JSON.stringify({ body: String(form.get("body")) }) });
      event.currentTarget.reset();
      messages.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "send failed");
    }
  }
  return (
    <>
      <ErrorText error={error || messages.error} />
      <form className="panel stack" onSubmit={onSubmit}>
        <h3>Note to the desk</h3>
        <label>Message<textarea name="body" required /></label>
        <button className="primary" type="submit">Record</button>
        <p className="empty">A note is stored as a user message. The CIO does not invent a chat reply or start a model call from it.</p>
      </form>
      <section className="panel">
        {(messages.data?.messages || []).slice().reverse().map((row) => (
          <article key={row.id} className="finding">
            <div className="row"><strong>{row.author}</strong><span className="tag">{row.channel}</span><Mode mode={row.execution_mode} /></div>
            <p>{row.body}</p>
            <div className="empty">{row.ts}</div>
          </article>
        ))}
      </section>
    </>
  );
}

interface Message { id: number; author: string; channel: string; body: string; ts: string; execution_mode?: string | null }

export function Audit() {
  const { data, error } = useData<{ office: EventRow[]; engine: EngineRow[] }>("/api/audit");
  if (error) return <div className="banner danger">{error}</div>;
  return (
    <div className="grid two">
      <section className="panel">
        <h3>Office events</h3>
        {!data?.office.length && <p className="empty">No office events.</p>}
        {data?.office.map((row) => (
          <div key={row.id} className="finding">
            <div className="row"><span className="tag">{row.channel}</span><span className="empty">{row.ts}</span></div>
            <div>{row.source} · {row.state || "event"} · {row.message}</div>
          </div>
        ))}
      </section>
      <section className="panel">
        <h3>Engine ledger events</h3>
        {!data?.engine.length && <p className="empty">No engine events in the paper directories.</p>}
        {data?.engine.map((row, index) => (
          <div key={index} className="finding">
            <div className="row"><strong>{row.fund}</strong><span className="tag">engine</span></div>
            <div className="empty">{row.error || `${row.time || ""} ${row.kind || ""} ${row.reason || ""}`}</div>
          </div>
        ))}
      </section>
    </div>
  );
}

interface EventRow { id: number; channel: string; ts: string; source: string; state?: string | null; message: string }
interface EngineRow { fund: string; time?: string; kind?: string; reason?: string; error?: string }

interface Provider { display_name: string; model_id: string; provider: string; env_var: string | null; supported: boolean; configured: boolean }
interface Catalog {
  default_model: string; native_assignment: string; models: Provider[];
  master_key_configured: boolean; data_configured: boolean; values_included: boolean;
}

export function Settings() {
  const catalog = useData<Catalog>("/api/providers");
  const agents = useData<{ agents: { name: string; display_name: string; kind: string }[] }>("/api/agents");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function saveModel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/settings/model", { method: "PUT", body: JSON.stringify({ model_id: String(form.get("model_id")) }) });
      setNotice("Office default model saved. The CLI process is unchanged.");
      catalog.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save failed");
    }
  }

  async function saveAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const model = String(form.get("model_id") || "");
    try {
      await api("/api/settings/agent-model", {
        method: "PUT",
        body: JSON.stringify({ agent: String(form.get("agent")), model_id: model || null }),
      });
      setNotice("Per-agent override saved for office-built funds only.");
      catalog.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save failed");
    }
  }

  async function saveKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/settings/credentials", {
        method: "POST",
        body: JSON.stringify({ env_var: String(form.get("env_var")), value: String(form.get("value")) }),
      });
      event.currentTarget.reset();
      setNotice("Credential stored. It was not returned.");
      catalog.load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "store failed");
    }
  }

  return (
    <>
      <ErrorText error={error || catalog.error} />
      {notice && <div className="banner info">{notice}</div>}
      <section className="panel">
        <h3>Providers</h3>
        <p className="empty">{catalog.data?.native_assignment}</p>
        <p className="empty">
          Data credential {catalog.data?.data_configured ? "present" : "missing"}.
          Master key {catalog.data?.master_key_configured ? "present" : "missing — the office will not store a new credential"}.
          Values included in this response: {String(catalog.data?.values_included)}.
        </p>
        <table>
          <thead><tr><th>Model</th><th>Provider</th><th>Env</th><th>Configured</th><th>Client</th></tr></thead>
          <tbody>
            {catalog.data?.models.map((row) => (
              <tr key={row.model_id}>
                <td>{row.display_name}<div className="empty">{row.model_id}</div></td>
                <td>{row.provider}</td>
                <td className="mono">{row.env_var}</td>
                <td>{row.configured ? "yes" : "no"}</td>
                <td>{row.supported ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div className="grid two">
        <form className="panel stack" onSubmit={saveModel}>
          <h3>Office default model</h3>
          <label>Model
            <select name="model_id" defaultValue={catalog.data?.default_model}>
              {catalog.data?.models.filter((row) => row.supported).map((row) => <option key={row.model_id} value={row.model_id}>{row.display_name}</option>)}
            </select>
          </label>
          <button className="primary" type="submit">Save default</button>
        </form>
        <form className="panel stack" onSubmit={saveAgent}>
          <h3>Per-agent override</h3>
          <label>Analyst
            <select name="agent">
              {agents.data?.agents.filter((row) => row.kind === "llm").map((row) => <option key={row.name} value={row.name}>{row.display_name}</option>)}
            </select>
          </label>
          <label>Model
            <select name="model_id">
              <option value="">Native default</option>
              {catalog.data?.models.filter((row) => row.supported).map((row) => <option key={row.model_id} value={row.model_id}>{row.display_name}</option>)}
            </select>
          </label>
          <button className="primary" type="submit">Save override</button>
        </form>
      </div>
      <form className="panel stack" onSubmit={saveKey}>
        <h3>Credential</h3>
        <label>Variable
          <select name="env_var">
            {["FINANCIAL_DATASETS_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "TYPESAFE_API_KEY"].map((name) => <option key={name}>{name}</option>)}
          </select>
        </label>
        <label>Value<input name="value" type="password" autoComplete="off" required /></label>
        <button className="primary" type="submit">Store on the server</button>
        <p className="empty">Requires OFFICE_MASTER_KEY in the server environment. The value is encrypted at rest and is not written to the page, the audit log, or git.</p>
      </form>
    </>
  );
}
