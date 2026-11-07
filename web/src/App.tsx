import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api } from "./api";
import { Health, Shell } from "./components";
import { Directory, TaskPage, Workspace } from "./pages/Agents";
import { BacktestJob, Backtests } from "./pages/Backtest";
import { Executive } from "./pages/Executive";
import { VirtualOffice } from "./pages/Office";
import { Audit, Comms, Settings } from "./pages/Ops";
import { Paper, PaperFund, SessionPage } from "./pages/Paper";
import { PortfolioBook, PortfolioList } from "./pages/Portfolio";
import { MissionPage, Research } from "./pages/Research";
import { Strategies } from "./pages/Strategies";

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  useEffect(() => {
    api<Health>("/api/health").then((body) => { setHealth(body); setOffline(null); }).catch((err: Error) => setOffline(err.message));
  }, []);
  return (
    <Shell health={health}>
      {offline && <div className="banner danger">API unavailable: {offline}</div>}
      <Routes>
        <Route path="/" element={<Executive />} />
        <Route path="/agents" element={<Directory />} />
        <Route path="/agents/:name" element={<Workspace />} />
        <Route path="/tasks/:id" element={<TaskPage />} />
        <Route path="/office" element={<VirtualOffice />} />
        <Route path="/research" element={<Research />} />
        <Route path="/research/:id" element={<MissionPage />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/portfolio" element={<PortfolioList />} />
        <Route path="/portfolio/:name" element={<PortfolioBook />} />
        <Route path="/backtests" element={<Backtests />} />
        <Route path="/backtests/:id" element={<BacktestJob />} />
        <Route path="/paper" element={<Paper />} />
        <Route path="/paper/:name" element={<PaperFund />} />
        <Route path="/paper/:name/sessions/:session" element={<SessionPage />} />
        <Route path="/comms" element={<Comms />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<p className="empty">That page is not part of the office.</p>} />
      </Routes>
    </Shell>
  );
}
