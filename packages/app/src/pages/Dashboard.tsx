import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  api,
  type ApiError,
  type StatsOut,
  type StatusResponse,
  type UpstreamOut,
} from "@/lib/api";
import {
  checkForUpdate,
  installUpdate,
  isTauri,
  type UpdateCheckResult,
} from "@/lib/updater";

interface DashboardData {
  status: StatusResponse;
  stats: StatsOut;
  upstreams: UpstreamOut[];
}

type FetchState =
  | { kind: "loading" }
  | { kind: "ok"; data: DashboardData }
  | { kind: "err"; message: string };

export default function Dashboard() {
  const [state, setState] = useState<FetchState>({ kind: "loading" });
  const [guideProvider, setGuideProvider] = useState<string | null>(null);
  const [guideContent, setGuideContent] = useState<string | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);
  const [updateState, setUpdateState] = useState<
    | { kind: "idle" }
    | { kind: "checking" }
    | { kind: "up-to-date" }
    | { kind: "found"; result: UpdateCheckResult }
    | { kind: "installing" }
    | { kind: "err"; message: string }
  >({ kind: "idle" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const [status, stats, upstreams] = await Promise.all([
        api.status(),
        api.stats("today"),
        api.listUpstreams(),
      ]);
      setState({
        kind: "ok",
        data: {
          status,
          stats,
          upstreams: [...upstreams].reverse(),
        },
      });
    } catch (e) {
      const msg =
        e instanceof Error ? (e as ApiError).message || e.message : String(e);
      setState({ kind: "err", message: msg });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runCheckUpdate = useCallback(async () => {
    setUpdateState({ kind: "checking" });
    try {
      const result = await checkForUpdate();
      setUpdateState(
        result.available ? { kind: "found", result } : { kind: "up-to-date" },
      );
    } catch (e) {
      setUpdateState({ kind: "err", message: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const runInstall = useCallback(async () => {
    setUpdateState({ kind: "installing" });
    try {
      await installUpdate();
      setUpdateState({ kind: "idle" });
    } catch (e) {
      setUpdateState({ kind: "err", message: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const inTauri = isTauri();
  const updateBtnDisabled =
    updateState.kind === "checking" || updateState.kind === "installing";

  function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    return (
      <button
        className="absolute right-2 top-2 rounded px-2 py-1 text-xs bg-background/80 hover:bg-muted text-foreground border border-border transition-colors"
        onClick={() => {
          navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    );
  }

  async function loadGuide(provider: string) {
    setGuideProvider(provider);
    setGuideContent(null);
    setGuideLoading(true);
    try {
      const result = await api.getProviderGuide(provider);
      setGuideContent(result.content);
    } catch {
      setGuideContent(null);
      setGuideProvider(null);
    } finally {
      setGuideLoading(false);
    }
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex shrink-0 items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <div className="flex items-center gap-2">
          {inTauri && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void runCheckUpdate()}
              disabled={updateBtnDisabled}
            >
              {updateState.kind === "checking"
                ? "Checking…"
                : updateState.kind === "installing"
                  ? "Installing…"
                  : "Check for updates"}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => void load()}>
            Refresh
          </Button>
        </div>
      </div>

      {updateState.kind === "up-to-date" && (
        <div className="mb-4 rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
          已是最新版本。
        </div>
      )}
      {updateState.kind === "err" && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          更新检查失败:{updateState.message}
        </div>
      )}
      {updateState.kind === "found" && (
        <div className="mb-4 rounded-md border border-border bg-muted/30 p-3 text-sm">
          <div className="mb-2">
            <Badge>update available</Badge>
            <span className="ml-2 font-mono">v{updateState.result.version}</span>
          </div>
          {updateState.result.notes && (
            <pre className="mb-2 max-h-32 overflow-auto whitespace-pre-wrap text-xs text-muted-foreground">
              {updateState.result.notes}
            </pre>
          )}
          <Button size="sm" onClick={() => void runInstall()}>
            Install and restart
          </Button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-hidden">
        {state.kind === "loading" && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}

        {state.kind === "err" && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6">
            <div className="mb-2 flex items-center gap-2">
              <Badge variant="destructive">server unreachable</Badge>
            </div>
            <p className="mb-3 text-sm text-muted-foreground">
              先跑 <code className="rounded bg-muted px-1.5 py-0.5">rosetta start</code>
              ，或设置{" "}
              <code className="rounded bg-muted px-1.5 py-0.5">VITE_API_URL</code>{" "}
              环境变量后重启 vite。
            </p>
            <p className="text-xs text-muted-foreground">{state.message}</p>
          </div>
        )}

        {state.kind === "ok" && (
          <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-4">
            <div className="grid shrink-0 grid-cols-3 gap-4">
              <Stat label="version" value={state.data.status.version} />
              <Stat
                label="server url"
                value={
                  <code className="break-all font-mono text-sm">
                    {state.data.status.url || "(unknown)"}
                  </code>
                }
              />
              <Stat label="status" value={<Badge>running</Badge>} />
              <Stat
                label="upstreams"
                value={String(state.data.status.upstreams_count)}
              />
              <Stat label="period" value={state.data.stats.period} />
              <Stat
                label="uptime"
                value={formatUptime(state.data.status.uptime_ms)}
              />
              <Stat
                label="today requests"
                value={String(state.data.stats.total_requests)}
              />
              <Stat
                label="success rate"
                value={formatRate(state.data.stats.success_rate)}
              />
              <Stat
                label="avg latency"
                value={
                  state.data.stats.avg_latency_ms > 0
                    ? `${Math.round(state.data.stats.avg_latency_ms)} ms`
                    : "-"
                }
              />
            </div>

            <div className="flex min-h-0 flex-col">
              <div className="mb-3 flex shrink-0 items-center justify-between">
                <h2 className="text-sm font-medium text-muted-foreground">
                  Upstreams
                </h2>
                <Link
                  to="/upstreams"
                  className="text-xs text-muted-foreground underline hover:text-foreground"
                >
                  Manage →
                </Link>
              </div>
              {state.data.upstreams.length === 0 ? (
                <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  暂无 upstream。
                  <Link
                    to="/upstreams"
                    className="ml-1 underline hover:text-foreground"
                  >
                    添加第一个
                  </Link>
                </div>
              ) : (
                <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
                  <table className="w-full table-fixed caption-bottom text-sm">
                    <TableHeader>
                      <TableRow className="bg-muted/45 hover:bg-muted/45">
                        <TableHead className="sticky top-0 z-20 w-[22%] bg-muted">
                          name
                        </TableHead>
                        <TableHead className="sticky top-0 z-20 w-[16%] bg-muted">
                          native_api
                        </TableHead>
                        <TableHead className="sticky top-0 z-20 w-[14%] bg-muted">
                          provider
                        </TableHead>
                        <TableHead className="sticky top-0 z-20 w-[12%] bg-muted">
                          model
                        </TableHead>
                        <TableHead className="sticky top-0 z-20 w-[8%] bg-muted">
                          status
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody className="[&_tr:last-child]:border-b">
                      {state.data.upstreams.map((u) => (
                        <TableRow key={u.id}>
                          <TableCell className="truncate font-medium">
                            {u.name}
                          </TableCell>
                          <TableCell className="truncate text-xs text-muted-foreground">
                            {u.native_api}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">{u.provider}</Badge>
                          </TableCell>
                          <TableCell className="truncate font-mono text-xs text-muted-foreground">
                            {u.model ?? "-"}
                          </TableCell>
                          <TableCell>
                            <Badge variant={u.enabled ? "default" : "outline"}>
                              {u.enabled ? "enabled" : "disabled"}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </table>
                </div>
              )}
            </div>

            <div className="shrink-0">
              <h2 className="mb-3 text-sm font-medium text-muted-foreground">
                Configurations
              </h2>
              <div className="flex items-center gap-6">
                <button
                  className="text-sm text-muted-foreground underline hover:text-foreground"
                  onClick={() => void loadGuide("codex")}
                >
                  Codex
                </button>
                <button
                  className="text-sm text-muted-foreground underline hover:text-foreground"
                  onClick={() => void loadGuide("claude")}
                >
                  Claude
                </button>
                <button
                  className="text-sm text-muted-foreground underline hover:text-foreground"
                  onClick={() => void loadGuide("readme")}
                >
                  README
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
      {/* --- Guide Dialog --- */}
      <Dialog
        open={guideProvider !== null}
        onOpenChange={(open) => {
          if (!open) setGuideProvider(null);
        }}
      >
        <DialogContent className="!max-w-[70vw] max-h-[90vh] flex flex-col p-0">
          <div className="shrink-0 px-8 pt-8">
            <DialogHeader>
              <DialogTitle>Configuration Guide: {guideProvider ?? ""}</DialogTitle>
            </DialogHeader>
          </div>
          <div className="flex-1 overflow-y-auto overflow-x-hidden px-8 pb-8">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              {guideLoading ? (
                <p className="text-muted-foreground">Loading...</p>
              ) : guideContent ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    pre: ({ children }) => {
                      const codeText = extractCodeText(children);
                      return (
                        <div className="relative group">
                          <CopyButton text={codeText} />
                          <pre className="overflow-x-auto">{children}</pre>
                        </div>
                      );
                    },
                  }}
                >
                  {guideContent}
                </ReactMarkdown>
              ) : (
                <p className="text-muted-foreground">Failed to load guide content.</p>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
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

function extractCodeText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(extractCodeText).join("");
  if (children && typeof children === "object" && "props" in children) {
    const el = children as { props?: { children?: React.ReactNode } };
    if (el.props?.children) return extractCodeText(el.props.children);
  }
  return "";
}

function formatUptime(ms: number): string {
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}

function formatRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}
