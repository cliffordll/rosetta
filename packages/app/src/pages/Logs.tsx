import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type LogOut, type UpstreamOut } from "@/lib/api";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 20;
const UPSTREAM_ALL = "__all__";

export default function Logs() {
  const [items, setItems] = useState<LogOut[] | null>(null);
  const [total, setTotal] = useState<number>(0);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [upstreams, setUpstreams] = useState<UpstreamOut[]>([]);
  const [upstreamFilter, setUpstreamFilter] = useState<string>(UPSTREAM_ALL);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [offset, setOffset] = useState(0);

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
    // upstream 下拉候选:只拉一次,之后用户 Restore mock / Add upstream 可点刷新
    (async () => {
      try {
        const list = await api.listUpstreams();
        setUpstreams([...list].reverse());
      } catch {
        // 拉不到不致命;过滤器保持 ALL
      }
    })();
  }, []);

  useEffect(() => {
    void load({ upstream: upstreamFilter, offset, limit: pageSize });
  }, [load, upstreamFilter, offset, pageSize]);

  function onUpstreamChange(value: string) {
    setOffset(0); // 换过滤重置分页
    setUpstreamFilter(value);
  }

  function onPageSizeChange(value: string) {
    const next = Number(value);
    setOffset(0); // 换页大小重置到第一页,避免 offset 落在新页面之外
    setPageSize(next);
  }

  function refresh() {
    void load({ upstream: upstreamFilter, offset, limit: pageSize });
  }

  // 用 total 算 page / totalPages,即使本页数据不足 pageSize 也能正确显示进度
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
    // 最后一页起始 offset = (totalPages - 1) * pageSize,确保不超 total
    setOffset(Math.max(0, (totalPages - 1) * pageSize));
  }

  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Logs</h1>
        <div className="flex items-center gap-2">
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
          <Button variant="outline" onClick={refresh}>
            Refresh
          </Button>
        </div>
      </div>

      {loadErr && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {loadErr}
        </div>
      )}

      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 && !loadErr ? (
        <EmptyState />
      ) : (
        <div className="rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-44">created_at</TableHead>
                <TableHead className="w-32">upstream</TableHead>
                <TableHead>model</TableHead>
                <TableHead className="w-24">status</TableHead>
                <TableHead className="w-20 text-right">latency</TableHead>
                <TableHead className="w-24 text-right">in→out</TableHead>
                <TableHead className="w-40">client_addr</TableHead>
                <TableHead className="w-48">upstream_url</TableHead>
                <TableHead>error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {formatDate(entry.created_at)}
                  </TableCell>
                  <TableCell>{entry.upstream ?? "-"}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {entry.model ?? "-"}
                  </TableCell>
                  <TableCell>{statusBadge(entry.status)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {entry.latency_ms !== null ? `${entry.latency_ms}ms` : "-"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {(entry.input_tokens ?? 0)}→{(entry.output_tokens ?? 0)}
                  </TableCell>
                  <TableCell
                    className="truncate font-mono text-xs text-muted-foreground"
                    title={entry.client_addr ?? ""}
                  >
                    {entry.client_addr ?? "-"}
                  </TableCell>
                  <TableCell
                    className="truncate font-mono text-xs text-muted-foreground"
                    title={entry.upstream_url ?? ""}
                  >
                    {entry.upstream_url ?? "-"}
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                    {entry.error ?? ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
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

function formatDate(iso: string): string {
  // server 存 UTC;UI 展示本地时间
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
