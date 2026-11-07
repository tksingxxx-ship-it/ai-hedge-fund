import { Link } from "react-router-dom";
import { Lamp } from "../components";
import { useData } from "./data";

interface Desk {
  name: string;
  display_name: string;
  department: string;
  kind: string;
  state: string;
  detail?: string | null;
  task_id?: string | null;
  strategies: string[];
}
interface Cio { display_name: string; state: string; detail?: string | null; summary: string; layer: string }

export function VirtualOffice() {
  const { data, error } = useData<{ desks: Desk[]; cio: Cio; note: string }>("/api/office/floor");
  const groups = ["Discretionary", "Systematic"];
  return (
    <>
      {error && <div className="banner danger">{error}</div>}
      <p className="empty">{data?.note}</p>
      <div className="floor grid">
        {data?.cio && (
          <Link to="/" className="desk">
            <header>
              <div>
                <div className="who">{data.cio.display_name}</div>
                <div className="role">Office coordination layer · {data.cio.layer}</div>
              </div>
              <Lamp state={data.cio.state} />
            </header>
            <p>{data.cio.summary}</p>
            <div className="row"><span className="tag office">NOT A NATIVE ANALYST</span><span className="tag">{data.cio.state}</span></div>
            <p className="empty">{data.cio.detail || "Idle until a mission is started."}</p>
          </Link>
        )}
        {groups.map((department) => (
          <section key={department}>
            <h3 style={{ color: "var(--muted)", letterSpacing: "0.08em", fontSize: 12 }}>{department}</h3>
            <div className="grid cards">
              {data?.desks.filter((desk) => desk.department === department).map((desk) => (
                <Link key={desk.name} to={`/agents/${desk.name}`} className="desk">
                  <header>
                    <div>
                      <div className="who">{desk.display_name}</div>
                      <div className="role">{desk.kind} · {desk.strategies.join(", ") || "unassigned"}</div>
                    </div>
                    <Lamp state={desk.state} />
                  </header>
                  <div className="row">
                    <span className="tag">{desk.state}</span>
                    <span className="tag">native</span>
                  </div>
                  <p className="empty">{desk.detail || "No live task."}</p>
                  {desk.task_id && <span>Open the current task</span>}
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
