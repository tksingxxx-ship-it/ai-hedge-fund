import { Link, useParams } from "react-router-dom";
import { Lamp, Mode } from "../components";
import { pct, signed } from "../api";
import { useData } from "./data";

interface Agent {
  name: string;
  display_name: string;
  kind: string;
  department: string;
  state: string;
  detail?: string | null;
  summary: string;
  disclaimer: string;
  investment_approach: string;
  horizon_days: number;
  strategies: string[];
  system_prompt?: string | null;
  model?: { effective?: string | null; office_override?: string | null; override_layer?: string };
  tasks?: Task[];
  findings?: { task_id: string; ticker: string; result: Finding }[];
  performance_note?: string;
}
interface Task {
  id: string;
  ticker?: string;
  status: string;
  kind: string;
  strategy?: string;
  error?: string | null;
  result?: Finding | null;
}
interface Finding {
  fixture?: boolean;
  execution_mode?: string;
  signal?: { value: number; reasoning?: string; model_name: string; metadata?: { abstained?: boolean } };
  data?: { source?: string; as_of?: string; price?: number | null; coverage?: string; note?: string };
}

export function Directory() {
  const { data, error } = useData<{ agents: Agent[] }>("/api/agents");
  return (
    <>
      {error && <div className="banner danger">{error}</div>}
      <div className="grid cards">
        {data?.agents.map((agent) => (
          <Link key={agent.name} to={`/agents/${agent.name}`} className="desk">
            <header>
              <div>
                <div className="who">{agent.display_name}</div>
                <div className="role">{agent.department} · {agent.kind}</div>
              </div>
              <Lamp state={agent.state} />
            </header>
            <div className="row">
              <span className="tag">{agent.state}</span>
              <span className="tag">h {agent.horizon_days}d</span>
            </div>
            <p className="empty">{agent.detail || agent.investment_approach}</p>
          </Link>
        ))}
      </div>
    </>
  );
}

export function Workspace() {
  const { name = "" } = useParams();
  const { data, error } = useData<Agent>(`/api/agents/${name}`);
  if (error) return <div className="banner danger">{error}</div>;
  if (!data) return <p className="empty">Loading analyst…</p>;
  return (
    <div className="grid two">
      <section className="panel">
        <div className="row">
          <h3>{data.display_name}</h3>
          <Lamp state={data.state} />
        </div>
        <p>{data.disclaimer}</p>
        <p className="empty">{data.summary}</p>
        <p>Approach {data.investment_approach}. Horizon {data.horizon_days} trading days. Staffed on {data.strategies.join(", ") || "no library strategy"}.</p>
        <p>State {data.state}. {data.detail || "No current task detail."}</p>
        {data.model && (
          <p className="empty">
            Model {data.model.effective || "none (quant)"} · {data.model.override_layer || "native"}
            {data.model.office_override ? " · office override" : ""}
          </p>
        )}
        <p className="empty">{data.performance_note}</p>
        {data.system_prompt && <details><summary>System prompt from the source class</summary><pre className="mono">{data.system_prompt}</pre></details>}
      </section>
      <section className="panel">
        <h3>Tasks and findings</h3>
        {!data.tasks?.length && <p className="empty">No tasks have been stored for this analyst.</p>}
        {data.tasks?.map((task) => (
          <Link key={task.id} to={`/tasks/${task.id}`} className="block">
            <div className="row">
              <strong>{task.kind} {task.ticker}</strong>
              <span className="tag">{task.status}</span>
            </div>
            <div className="empty">{task.strategy} {task.error || ""}</div>
            {task.result?.signal && (
              <div>
                <Mode mode={task.result.execution_mode} /> {signed(task.result.signal.value)}
                {task.result.data?.price != null && ` · ${task.result.data.source} ${task.result.data.price} as of ${task.result.data.as_of}`}
              </div>
            )}
          </Link>
        ))}
      </section>
    </div>
  );
}

export function TaskPage() {
  const { id = "" } = useParams();
  const { data, error } = useData<Task & {
    agent?: string;
    payload?: unknown;
    events?: { id: number; ts: string; state?: string; message: string; channel: string }[];
  }>(`/api/tasks/${id}`);
  if (error) return <div className="banner danger">{error}</div>;
  if (!data) return <p className="empty">Loading task…</p>;
  const signal = data.result?.signal;
  return (
    <div className="grid two">
      <section className="panel">
        <h3>{data.agent} · {data.kind}</h3>
        <p>{data.ticker} · {data.strategy || "no strategy"} · {data.status}</p>
        {data.error && <p className="error">{data.error}</p>}
        {signal && (
          <>
            <p>Conviction {signed(signal.value)} {signal.metadata?.abstained ? "(abstained)" : ""}</p>
            <p>{signal.reasoning || "No reasoning text was stored."}</p>
            <p className="empty">
              Data {data.result?.data?.source || "unknown"} · coverage {data.result?.data?.coverage || "—"} · price {data.result?.data?.price ?? "—"} · as of {data.result?.data?.as_of}
            </p>
            <p className="empty">{data.result?.data?.note}</p>
            {data.result?.fixture && <span className="tag fixture">FIXTURE</span>}
          </>
        )}
        {data.payload != null && <pre className="mono">{JSON.stringify(data.payload, null, 2)}</pre>}
      </section>
      <section className="panel">
        <h3>Execution history</h3>
        {!data.events?.length && <p className="empty">No events for this task.</p>}
        {data.events?.map((event) => (
          <div key={event.id} className="finding">
            <div className="row"><span className="tag">{event.channel}</span><span className="empty">{event.ts}</span></div>
            <div>{event.state || "event"} — {event.message}</div>
          </div>
        ))}
        <p className="empty">Weight display elsewhere uses {pct(0.1)} style formatting. This page shows the stored signal, not a sized order.</p>
      </section>
    </div>
  );
}
