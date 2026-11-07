import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

export function useData<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<T>(path).then((body) => { setData(body); setError(null); }).catch((err: Error) => setError(err.message));
  }, [path]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const source = new EventSource("/api/events/stream");
    source.onmessage = () => load();
    const timer = window.setInterval(load, 12000);
    return () => { source.close(); window.clearInterval(timer); };
  }, [load]);
  return { data, error, load, setError };
}
