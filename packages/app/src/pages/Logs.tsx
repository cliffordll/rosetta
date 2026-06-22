import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type LogOut, type LogsConfigOut, type UpstreamOut } from "@/lib/api";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 20;
const DEFAULT_LOG_CONTENT = "summary";
const UPSTREAM_ALL = "__all__";

export default function Logs() {
  const [items, setItems] = useState<LogOut[] | null>(null);
  const [total, setTotal] = useState<number>(0);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [upstreams, setUpstreams] = useState<UpstreamOut[]>([]);
  const [upstreamFilter, setUpstreamFilter] = useState<string>(UPSTREAM_ALL);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [logContent, setLogContent] =
    useState<LogsConfigOut["log_content"]>(DEFAULT_LOG_CONTENT);
  const [offset, setOffset] = useState(0);
  const [configSaving, setConfigSaving] = useState(false);

  const load = useCallback(
    async (opts: { upstream: string; offset: number; limit: number }) => {
      setLoadErr(null);
      try {
        const result = await api.listLogs({
          limit: opts.limit,
          offset: opts.offset,
          upstream: opts.upstream === UPSTREAM_ALL ? undefined : opts.upstream,
        });
        setItems(result.items);
        setTotal(result.total);
      } catch (e) {
        setLoadErr(e instanceof Error ? e.message : String(e));
        setItems([]);
        setTotal(0);
      }
    },
    [],
  );

  useEffect(() => {
    (async () => {
      try {
        const [list, config] = await Promise.all([api.listUpstreams(), api.logsConfig()]);
        setUpstreams([...list].reverse());
        setPageSize(config.page_size);
        setLogContent(config.log_content);
      } catch {
        // 拉不到不致命;过滤器保持 ALL
      }
    })();
  }, []);

  useEffect(() => {
    void load({ upstream: upstreamFilter, offset, limit: pageSize });
  }, [load, upstreamFilter, offset, pageSize]);

  function onUpstreamChange(value: string) {
    setOffset(0);
    setUpstreamFilter(value);
  }

  function onPageSizeChange(value: string) {
    void saveConfig({ page_size: Number(value) as LogsConfigOut["page_size"] });
  }

  function refresh() {
    void load({ upstream: upstreamFilter, offset, limit: pageSize });
  }

  async function saveConfig(patch: Partial<LogsConfigOut>) {
    setConfigSaving(true);
    setInfo(null);
    setLoadErr(null);
    try {
      const config = await api.updateLogsConfig(patch);
      setPageSize(config.page_size);
      setLogContent(config.log_content);
      setOffset(0);
      setInfo(`logs config -> ${config.log_content}, ${config.page_size} / page`);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setConfigSaving(false);
    }
  }

  const page = Math.floor(offset / pageSize) + 1;
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 1;
  const canPrev = page > 1;
  const canNext = page < totalPages;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = items === null ? offset : offset + items.length;

  function gotoFirst() {
    setOffset(0);
  }
  function gotoPrev() {
    setOffset(Math.max(0, offset - pageSize));
  }
  function gotoNext() {
    setOffset(offset + pageSize);
  }
  function gotoLast() {
    setOffset(Math.max(0, (totalPages - 1) * pageSize));
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex shrink-0 items-center justify-between">
        <h1 className="text-2xl font-semibold">Logs</h1>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2">
            <Label className="text-xs text-muted-foreground">log content</Label>
            <Select
              value={logContent}
              onValueChange={(value) =>
                void saveConfig({ log_content: value as LogsConfigOut["log_content"] })
              }
            >
              <SelectTrigger className="h-9 w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">none</SelectItem>
                <SelectItem value="summary">summary</SelectItem>
                <SelectItem value="full">full</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Select value={upstreamFilter} onValueChange={onUpstreamChange}>
            <SelectTrigger className="w-56">
              <SelectValue placeholder="Filter upstream" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UPSTREAM_ALL}>all upstreams</SelectItem>
              {upstreams.map((u) => (
                <SelectItem key={u.id} value={u.name}>
                  {u.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={refresh} disabled={configSaving}>
            {configSaving ? "Saving…" : "Refresh"}
          </Button>
        </div>
      </div>

      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 && !loadErr ? (
        <EmptyState />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full table-fixed caption-bottom text-sm">
            <TableHeader>
              <TableRow className="hover:bg-muted/45">
                <TableHead className="sticky top-0 z-20 w-44 bg-muted">created_at</TableHead>
                <TableHead className="sticky top-0 z-20 w-[10%] bg-muted">upstream</TableHead>
                <TableHead className="sticky top-0 z-20 w-[10%] bg-muted">model</TableHead>
                <TableHead className="sticky top-0 z-20 w-[6%] bg-muted">result</TableHead>
                <TableHead className="sticky top-0 z-20 w-[6%] bg-muted text-right">
                  latency
                </TableHead>
                <TableHead className="sticky top-0 z-20 w-[7%] bg-muted text-right">
                  tokens
                </TableHead>
                <TableHead className="sticky top-0 z-20 w-[16%] bg-muted">request</TableHead>
                <TableHead className="sticky top-0 z-20 w-[16%] bg-muted">response</TableHead>
                <TableHead className="sticky top-0 z-20 w-[7%] bg-muted">client</TableHead>
                <TableHead className="sticky top-0 z-20 w-[8%] bg-muted">error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="[&_tr:last-child]:border-b">
              {items.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {formatDate(entry.created_at)}
                  </TableCell>
                  <TableCell
                    className="truncate"
                    title={entry.upstream ?? ""}
                  >
                    {entry.upstream ?? "-"}
                  </TableCell>
                  <TableCell
                    className="truncate font-mono text-xs"
                    title={entry.model ?? ""}
                  >
                    {entry.model ?? "-"}
                  </TableCell>
                  <TableCell>{statusBadge(entry.status)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {entry.latency_ms !== null ? `${entry.latency_ms}ms` : "-"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {(entry.input_tokens ?? 0)}→{(entry.output_tokens ?? 0)}
                  </TableCell>
                  <TableCell className="align-top">
                    <LogTextCell text={entry.request_text} />
                  </TableCell>
                  <TableCell className="align-top">
                    <LogTextCell text={entry.response_text} />
                  </TableCell>
                  <TableCell
                    className="truncate font-mono text-xs text-muted-foreground"
                    title={entry.client_addr ?? ""}
                  >
                    {entry.client_addr ?? "-"}
                  </TableCell>
                  <TableCell
                    className="truncate text-xs text-muted-foreground"
                    title={entry.error ?? ""}
                  >
                    {entry.error ?? "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </table>
        </div>
      )}

      <div className="mt-2 flex shrink-0 items-center justify-between text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>
            {total === 0
              ? "0 entries"
              : `Showing ${rangeStart}–${rangeEnd} of ${total} entries`}
          </span>
          <span className="text-xs">·</span>
          <Select value={String(pageSize)} onValueChange={onPageSizeChange}>
            <SelectTrigger className="h-8 w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {n} / page
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={!canPrev} onClick={gotoFirst}>
            « First
          </Button>
          <Button variant="outline" size="sm" disabled={!canPrev} onClick={gotoPrev}>
            ‹ Prev
          </Button>
          <span className="px-2 text-xs">
            Page {page} / {totalPages}
          </span>
          <Button variant="outline" size="sm" disabled={!canNext} onClick={gotoNext}>
            Next ›
          </Button>
          <Button variant="outline" size="sm" disabled={!canNext} onClick={gotoLast}>
            Last »
          </Button>
        </div>
      </div>

      {(info || loadErr) && (
        <div className="mt-4 space-y-3">
          {info && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/8 p-3 text-sm text-emerald-700">
              {info}
            </div>
          )}
          {loadErr && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {loadErr}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-border p-10 text-center">
      <p className="text-sm text-muted-foreground">
        暂无日志。发一条 chat 请求(含 mock)后点 Refresh 查看
      </p>
    </div>
  );
}

function statusBadge(s: string) {
  if (s === "ok") return <Badge>ok</Badge>;
  if (s === "error") return <Badge variant="destructive">error</Badge>;
  return <Badge variant="outline">{s}</Badge>;
}

function LogTextCell({ text }: { text: string | null }) {
  if (!text) {
    return <span className="text-xs text-muted-foreground">-</span>;
  }
  const compact = text.trim();
  const preview = compact.length > 88 ? `${compact.slice(0, 87).trimEnd()}…` : compact;
  return (
    <details className="group">
      <summary
        className="line-clamp-2 cursor-pointer list-none text-xs text-muted-foreground marker:hidden"
        title={compact}
      >
        {preview}
      </summary>
      <div className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-muted/25 p-2 font-mono text-xs text-foreground">
        {compact}
      </div>
    </details>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
