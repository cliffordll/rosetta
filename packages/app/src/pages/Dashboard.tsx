import { useCallback, useEffect, useState } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api, type ApiError, type StatusResponse } from "@/lib/api";
import {
  checkForUpdate,
  installUpdate,
  isTauri,
  type UpdateCheckResult,
} from "@/lib/updater";

type FetchState =
  | { kind: "loading" }
  | { kind: "ok"; status: StatusResponse }
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
      const status = await api.status();
      setState({ kind: "ok", status });
    } catch (e) {
      const msg =
        e instanceof Error ? (e as ApiError).message || e.message : String(e);
      setState({ kind: "err", message: msg });
    }
  }, []);

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
      // 成功时 Tauri 会触发 restart,这条 setState 不一定会被执行
      setUpdateState({ kind: "idle" });
    } catch (e) {
      setUpdateState({ kind: "err", message: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
    } catch (e) {
      setGuideContent(null);
      setGuideProvider(null);
    } finally {
      setGuideLoading(false);
    }
  }

  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
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
          <Stat
            label="server url"
            value={
              <code className="break-all font-mono text-sm">
                {state.status.url || "(unknown)"}
              </code>
            }
          />
        </div>
      )}
      {/* --- Configuration Guide --- */}
      <div className="mt-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">配置说明</h2>
        <div className="flex gap-6">
          <button
            className="text-sm underline hover:text-foreground text-muted-foreground"
            onClick={() => void loadGuide("codex")}
          >
            Codex
          </button>
          <button
            className="text-sm underline hover:text-foreground text-muted-foreground"
            onClick={() => void loadGuide("claude")}
          >
            Claude
          </button>
        </div>
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
