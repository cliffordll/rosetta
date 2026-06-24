import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
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

const LOG_TABLE_COLUMNS = [
  "created_at",
  "upstream",
  "model",
  "result",
  "latency",
  "tokens",
  "request",
  "response",
  "client",
  "error",
] as const;
type LogTableColumn = (typeof LOG_TABLE_COLUMNS)[number];
type LogColumnWidths = Record<LogTableColumn, number>;

const TABLE_CELL = "p-1.5 text-xs text-muted-foreground";
const TABLE_TEXT = `${TABLE_CELL} truncate`;
const TABLE_TECH = `${TABLE_TEXT} font-mono tabular-nums`;
const LABEL_TEXT = "text-sm text-muted-foreground";

const DEFAULT_LOG_COLUMN_WIDTHS: LogColumnWidths = {
  created_at: 11,
  upstream: 9,
  model: 10,
  result: 6,
  latency: 7,
  tokens: 7,
  request: 15,
  response: 15,
  client: 7,
  error: 10,
};

const MIN_LOG_COLUMN_WIDTHS: LogColumnWidths = {
  created_at: 6,
  upstream: 6,
  model: 6,
  result: 5,
  latency: 5,
  tokens: 5,
  request: 8,
  response: 8,
  client: 5,
  error: 6,
};

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
  const [clearing, setClearing] = useState(false);
  const [logColumnWidths, setLogColumnWidths] = useState<LogColumnWidths>(
    DEFAULT_LOG_COLUMN_WIDTHS,
  );
  const logResizeRef = useRef<{
    startX: number;
    tableWidth: number;
    left: LogTableColumn;
    right: LogTableColumn;
    leftWidth: number;
    rightWidth: number;
  } | null>(null);

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

  function startLogColumnResize(
    left: LogTableColumn,
    right: LogTableColumn,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) {
    event.preventDefault();
    const table = event.currentTarget.closest("table");
    const tableWidth = table?.getBoundingClientRect().width ?? 1;
    logResizeRef.current = {
      startX: event.clientX,
      tableWidth,
      left,
      right,
      leftWidth: logColumnWidths[left],
      rightWidth: logColumnWidths[right],
    };

    const onPointerMove = (moveEvent: PointerEvent) => {
      const state = logResizeRef.current;
      if (!state) return;
      const delta = ((moveEvent.clientX - state.startX) / state.tableWidth) * 100;
      const minLeft = MIN_LOG_COLUMN_WIDTHS[state.left];
      const minRight = MIN_LOG_COLUMN_WIDTHS[state.right];
      const pairTotal = state.leftWidth + state.rightWidth;
      const nextLeft = Math.min(
        pairTotal - minRight,
        Math.max(minLeft, state.leftWidth + delta),
      );
      const nextRight = pairTotal - nextLeft;
      setLogColumnWidths((current) => ({
        ...current,
        [state.left]: nextLeft,
        [state.right]: nextRight,
      }));
    };

    const onPointerUp = () => {
      logResizeRef.current = null;
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }
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

  async function clearLogs() {
    setClearing(true);
    setInfo(null);
    setLoadErr(null);
    try {
      const result = await api.clearLogs();
      setOffset(0);
      setItems([]);
      setTotal(0);
      setInfo(`cleared ${result.deleted} log ${result.deleted === 1 ? "entry" : "entries"}`);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setClearing(false);
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
            <Label className={LABEL_TEXT}>log content</Label>
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
          <Button variant="outline" onClick={refresh} disabled={configSaving || clearing}>
            {configSaving ? "Saving…" : clearing ? "Clearing…" : "Refresh"}
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" disabled={clearing || total === 0}>
                Clear
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Clear all logs?</AlertDialogTitle>
                <AlertDialogDescription>
                  This removes every request log entry. Log settings are kept.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={clearing}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  disabled={clearing}
                  onClick={() => void clearLogs()}
                >
                  {clearing ? "Clearing…" : "Clear logs"}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 && !loadErr ? (
        <EmptyState />
      ) : (
                <div className="relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden rounded-lg border border-border">
          <table className="w-full table-fixed caption-bottom text-sm">
            <colgroup>
              {LOG_TABLE_COLUMNS.map((column) => (
                <col key={column} style={{ width: `${logColumnWidths[column]}%` }} />
              ))}
            </colgroup>
            <TableHeader className="sticky top-0 z-20">
              <TableRow className="hover:bg-muted/45">
                <ResizableLogHead
                  label="created_at"
                  left="created_at"
                  right="upstream"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="upstream"
                  left="upstream"
                  right="model"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="model"
                  left="model"
                  right="result"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="result"
                  left="result"
                  right="latency"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="latency"
                  left="latency"
                  right="tokens"
                  align="right"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="tokens"
                  left="tokens"
                  right="request"
                  align="right"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="request"
                  left="request"
                  right="response"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="response"
                  left="response"
                  right="client"
                  onResize={startLogColumnResize}
                />
                <ResizableLogHead
                  label="client"
                  left="client"
                  right="error"
                  onResize={startLogColumnResize}
                />
                <TableHead className="bg-muted">error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="[&_tr:last-child]:border-b [&_tr]:h-10">
              {items.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className={TABLE_TECH} title={formatDate(entry.created_at)}>
                    {formatDate(entry.created_at)}
                  </TableCell>
                  <TableCell
                    className={TABLE_TEXT}
                    title={entry.upstream ?? ""}
                  >
                    {entry.upstream ?? "-"}
                  </TableCell>
                  <TableCell
                    className={TABLE_TECH}
                    title={entry.model ?? ""}
                  >
                    {entry.model ?? "-"}
                  </TableCell>
                  <TableCell className={TABLE_CELL}>{statusBadge(entry.status)}</TableCell>
                  <TableCell className={`${TABLE_CELL} text-right font-mono tabular-nums`}>
                    {entry.latency_ms !== null ? `${entry.latency_ms}ms` : "-"}
                  </TableCell>
                  <TableCell className={`${TABLE_CELL} text-right font-mono tabular-nums`}>
                    {(entry.input_tokens ?? 0)}→{(entry.output_tokens ?? 0)}
                  </TableCell>
                  <TableCell className={`${TABLE_CELL} align-top`}>
                    <LogTextCell text={entry.request_text} />
                  </TableCell>
                  <TableCell className={`${TABLE_CELL} align-top`}>
                    <LogTextCell text={entry.response_text} />
                  </TableCell>
                  <TableCell
                    className={TABLE_TECH}
                    title={entry.client_addr ?? ""}
                  >
                    {entry.client_addr ?? "-"}
                  </TableCell>
                  <TableCell
                    className={TABLE_TEXT}
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

function ResizableLogHead({
  label,
  left,
  right,
  align = "left",
  onResize,
}: {
  label: string;
  left: LogTableColumn;
  right: LogTableColumn;
  align?: "left" | "right";
  onResize: (
    left: LogTableColumn,
    right: LogTableColumn,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) => void;
}) {
  return (
    <TableHead className="bg-muted relative select-none">
      <div className={`truncate pr-3 ${align === "right" ? "text-right" : ""}`}>
        {label}
      </div>
      <button
        type="button"
        aria-label={`Resize ${label} column`}
        className="absolute right-0 top-0 z-30 h-full w-3 cursor-col-resize touch-none border-r border-transparent hover:border-ring focus:border-ring focus:outline-none"
        onPointerDown={(event) => onResize(left, right, event)}
      />
    </TableHead>
  );
}
function EmptyState() {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-dashed border-border p-10 text-center">
      <p className="text-sm text-muted-foreground">
        暂无日志。发一条 chat 请求(含 mock)后点 Refresh 查看
      </p>
    </div>
  );
}

function statusBadge(s: string) {
  if (s === "ok") return <Badge className="bg-emerald-500 text-white">ok</Badge>;
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

