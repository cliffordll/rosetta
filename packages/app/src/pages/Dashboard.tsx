import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type ApiError, type StatusResponse } from "@/lib/api";

type FetchState =
  | { kind: "loading" }
  | { kind: "ok"; status: StatusResponse }
  | { kind: "err"; message: string };

export default function Dashboard() {
  const [state, setState] = useState<FetchState>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const status = await api.status();
      setState({ kind: "ok", status });
    } catch (e) {
      const msg =
        e instanceof Error ? (e as ApiError).message || e.message : String(e);
      setState({ kind: "err", message: msg });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          Refresh
        </Button>
      </div>

      {state.kind === "loading" && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}

      {state.kind === "err" && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6">
          <div className="mb-2 flex items-center gap-2">
            <Badge variant="destructive">server unreachable</Badge>
          </div>
          <p className="mb-3 text-sm text-muted-foreground">
            先跑 <code className="rounded bg-muted px-1.5 py-0.5">rosetta start</code>,或设置{" "}
            <code className="rounded bg-muted px-1.5 py-0.5">VITE_API_URL</code> 环境变量后重启 vite。
          </p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </div>
      )}

      {state.kind === "ok" && (
        <div className="grid max-w-2xl grid-cols-2 gap-4">
          <Stat label="status" value={<Badge>running</Badge>} />
          <Stat label="version" value={state.status.version} />
          <Stat label="uptime" value={formatUptime(state.status.uptime_ms)} />
          <Stat label="upstreams" value={String(state.status.upstreams_count)} />
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-lg font-medium">{value}</div>
    </div>
  );
}

function formatUptime(ms: number): string {
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}
