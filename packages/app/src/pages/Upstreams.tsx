import { useCallback, useEffect, useMemo, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import {
  ApiError,
  UPSTREAM_PROVIDERS,
  api,
  type UpstreamCreate,
  type UpstreamOut,
  type UpstreamProtocol,
  type UpstreamProvider,
  type UpstreamUpdate,
} from "@/lib/api";

const PROTOCOLS: UpstreamProtocol[] = ["messages", "completions", "responses"];

// 分组渲染顺序;`any` 是 mock 占位,放最后
const GROUP_ORDER: string[] = ["messages", "completions", "responses", "any"];

const COLUMN_COUNT = 9;

export default function Upstreams() {
  const [items, setItems] = useState<UpstreamOut[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [openAdd, setOpenAdd] = useState(false);
  const [toEdit, setToEdit] = useState<UpstreamOut | null>(null);
  const [toDelete, setToDelete] = useState<UpstreamOut | null>(null);
  const [restoringMock, setRestoringMock] = useState(false);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const list = await api.listUpstreams();
      // 后端按 created_at 升序返回;UI 倒序让最新创建的排在最前
      setItems([...list].reverse());
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
      setItems([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 按 protocol 分组(messages → completions → responses → any),空组不渲染
  const grouped = useMemo(() => {
    if (!items) return [] as Array<{ protocol: string; rows: UpstreamOut[] }>;
    const buckets = new Map<string, UpstreamOut[]>();
    for (const u of items) {
      const arr = buckets.get(u.protocol) ?? [];
      arr.push(u);
      buckets.set(u.protocol, arr);
    }
    return GROUP_ORDER.filter((p) => buckets.has(p)).map((p) => ({
      protocol: p,
      rows: buckets.get(p) ?? [],
    }));
  }, [items]);

  async function handleDelete(id: string) {
    try {
      await api.deleteUpstream(id);
      setToDelete(null);
      await load();
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
      setToDelete(null);
    }
  }

  async function handleSetDefault(name: string) {
    setInfo(null);
    setLoadErr(null);
    try {
      const updated = await api.setDefaultUpstream(name);
      setInfo(`upstream '${updated.name}' is now default for protocol=${updated.protocol}`);
      await load();
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRestoreMock() {
    setInfo(null);
    setLoadErr(null);
    setRestoringMock(true);
    try {
      const result = await api.restoreMockUpstream();
      setInfo(
        result.created
          ? `mock upstream restored (id=${result.upstream.id})`
          : `mock upstream already exists (id=${result.upstream.id})`,
      );
      await load();
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRestoringMock(false);
    }
  }

  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Upstreams</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => void handleRestoreMock()}
            disabled={restoringMock}
          >
            {restoringMock ? "Restoring…" : "Restore mock"}
          </Button>
          <Button onClick={() => setOpenAdd(true)}>Add upstream</Button>
        </div>
      </div>

      {info && (
        <div className="mb-4 rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
          {info}
        </div>
      )}

      {loadErr && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {loadErr}
        </div>
      )}

      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 && !loadErr ? (
        <EmptyState
          onAdd={() => setOpenAdd(true)}
          onRestoreMock={() => void handleRestoreMock()}
          restoringMock={restoringMock}
        />
      ) : (
        <div className="rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-24">id</TableHead>
                <TableHead>name</TableHead>
                <TableHead>provider</TableHead>
                <TableHead>model</TableHead>
                <TableHead>base_url</TableHead>
                <TableHead className="w-24">enabled</TableHead>
                <TableHead className="w-24">default</TableHead>
                <TableHead className="w-40">created_at</TableHead>
                <TableHead className="w-48 text-right">actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {grouped.map((group) => (
                <GroupSection
                  key={group.protocol}
                  protocol={group.protocol}
                  rows={group.rows}
                  onSetDefault={(u) => void handleSetDefault(u.name)}
                  onEdit={(u) => setToEdit(u)}
                  onDelete={(u) => setToDelete(u)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <UpstreamFormDialog
        mode="add"
        open={openAdd}
        onOpenChange={setOpenAdd}
        onSubmitted={async () => {
          setOpenAdd(false);
          await load();
        }}
      />

      <UpstreamFormDialog
        mode="edit"
        initial={toEdit}
        open={toEdit !== null}
        onOpenChange={(o) => !o && setToEdit(null)}
        onSubmitted={async () => {
          setToEdit(null);
          await load();
        }}
      />

      <AlertDialog open={toDelete !== null} onOpenChange={(o) => !o && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete upstream?</AlertDialogTitle>
            <AlertDialogDescription>
              删除 <code className="rounded bg-muted px-1">{toDelete?.name}</code>;
              历史 logs 的 upstream_id 成死引用,UI 显示时会兜底。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) void handleDelete(toDelete.id);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function GroupSection({
  protocol,
  rows,
  onSetDefault,
  onEdit,
  onDelete,
}: {
  protocol: string;
  rows: UpstreamOut[];
  onSetDefault: (u: UpstreamOut) => void;
  onEdit: (u: UpstreamOut) => void;
  onDelete: (u: UpstreamOut) => void;
}) {
  return (
    <>
      <TableRow className="bg-muted/40 hover:bg-muted/40">
        <TableCell
          colSpan={COLUMN_COUNT}
          className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
        >
          {protocol} <span className="text-muted-foreground/70">· {rows.length}</span>
        </TableCell>
      </TableRow>
      {rows.map((u) => (
        <TableRow key={u.id}>
          <TableCell className="font-mono text-xs">{u.id.slice(0, 8)}…</TableCell>
          <TableCell className="font-medium">{u.name}</TableCell>
          <TableCell>
            <Badge variant="outline">{u.provider}</Badge>
          </TableCell>
          <TableCell className="font-mono text-xs text-muted-foreground">
            {u.model ?? "-"}
          </TableCell>
          <TableCell className="text-muted-foreground">{u.base_url}</TableCell>
          <TableCell>
            {u.enabled ? <Badge>enabled</Badge> : <Badge variant="outline">disabled</Badge>}
          </TableCell>
          <TableCell>{u.is_default ? <Badge>default</Badge> : null}</TableCell>
          <TableCell className="font-mono text-xs text-muted-foreground">
            {formatDate(u.created_at)}
          </TableCell>
          <TableCell className="text-right">
            {!u.is_default && u.protocol !== "any" && (
              <Button variant="ghost" size="sm" onClick={() => onSetDefault(u)}>
                Set default
              </Button>
            )}
            {u.provider !== "mock" && (
              <Button variant="ghost" size="sm" onClick={() => onEdit(u)}>
                Edit
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => onDelete(u)}>
              Delete
            </Button>
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

function EmptyState({
  onAdd,
  onRestoreMock,
  restoringMock,
}: {
  onAdd: () => void;
  onRestoreMock: () => void;
  restoringMock: boolean;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border p-10 text-center">
      <p className="mb-3 text-sm text-muted-foreground">暂无 upstream</p>
      <div className="flex items-center justify-center gap-2">
        <Button onClick={onAdd}>Add your first upstream</Button>
        <Button variant="outline" onClick={onRestoreMock} disabled={restoringMock}>
          {restoringMock ? "Restoring…" : "Restore built-in mock"}
        </Button>
      </div>
    </div>
  );
}

type FormMode = "add" | "edit";

/**
 * Add / Edit 共用对话框。`mode="add"` 提交 createUpstream;`mode="edit"` 提交
 * updateUpstream(只发改过的字段;protocol 变化时 server 自动清 is_default)。
 */
function UpstreamFormDialog({
  mode,
  initial,
  open,
  onOpenChange,
  onSubmitted,
}: {
  mode: FormMode;
  initial?: UpstreamOut | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmitted: () => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [protocol, setProtocol] = useState<UpstreamProtocol>("messages");
  const [provider, setProvider] = useState<UpstreamProvider>("custom");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // open 翻 true 时按 initial 填表;关闭时 reset
  useEffect(() => {
    if (!open) return;
    setErr(null);
    if (mode === "edit" && initial) {
      setName(initial.name);
      // initial.protocol 可能是 "any"(mock),但 mock 不让编辑,这里保险下
      setProtocol(
        (PROTOCOLS as readonly string[]).includes(initial.protocol)
          ? (initial.protocol as UpstreamProtocol)
          : "messages",
      );
      setProvider(initial.provider as UpstreamProvider);
      setApiKey(""); // api_key 不回填;留空 = 不动,填值 = 更新
      setModel(initial.model ?? "");
      setBaseUrl(initial.base_url);
      setEnabled(initial.enabled);
    } else {
      setName("");
      setProtocol("messages");
      setProvider("custom");
      setApiKey("");
      setModel("");
      setBaseUrl("");
      setEnabled(true);
    }
  }, [open, mode, initial]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!name.trim() || !baseUrl.trim()) {
      setErr("name 和 base_url 必填");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "add") {
        const payload: UpstreamCreate = {
          name: name.trim(),
          protocol,
          provider,
          api_key: apiKey.trim() || undefined,
          model: model.trim() || undefined,
          base_url: baseUrl.trim(),
        };
        await api.createUpstream(payload);
      } else if (initial) {
        // 只发与原值不同的字段;api_key 留空表示不动(不发字段)
        const payload: UpstreamUpdate = {};
        if (name.trim() !== initial.name) payload.name = name.trim();
        if (protocol !== initial.protocol) payload.protocol = protocol;
        if (provider !== initial.provider) payload.provider = provider;
        if (baseUrl.trim() !== initial.base_url) payload.base_url = baseUrl.trim();
        if (enabled !== initial.enabled) payload.enabled = enabled;
        if (apiKey.trim()) payload.api_key = apiKey.trim();
        const trimmedModel = model.trim();
        const initialModel = initial.model ?? "";
        if (trimmedModel !== initialModel) {
          payload.model = trimmedModel || null;
        }
        if (Object.keys(payload).length === 0) {
          // 没改动,直接关
          await onSubmitted();
          return;
        }
        await api.updateUpstream(initial.id, payload);
      }
      await onSubmitted();
    } catch (e) {
      if (e instanceof ApiError) {
        setErr(`HTTP ${e.status}: ${e.body.slice(0, 300)}`);
      } else {
        setErr(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const isEdit = mode === "edit";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit upstream" : "Add upstream"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "修改字段后保存;api_key 留空 = 不动,填值 = 更新。改 protocol 时如果该行是 default,会自动清掉。"
              : "新建上游 upstream;model 留空时,客户端必须自带 body.model。"}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="u-name">name</Label>
            <Input
              id="u-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. ant-main"
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-protocol">protocol</Label>
            <Select value={protocol} onValueChange={(v) => setProtocol(v as UpstreamProtocol)}>
              <SelectTrigger id="u-protocol">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROTOCOLS.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-provider">provider</Label>
            <Select value={provider} onValueChange={(v) => setProvider(v as UpstreamProvider)}>
              <SelectTrigger id="u-provider">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {UPSTREAM_PROVIDERS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-key">
              api_key{" "}
              <span className="text-xs text-muted-foreground">
                {isEdit ? "(留空 = 不动)" : "(可选)"}
              </span>
            </Label>
            <Input
              id="u-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-model">
              model <span className="text-xs text-muted-foreground">(可选 · 默认模型)</span>
            </Label>
            <Input
              id="u-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. claude-haiku-4-5"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-base">base_url</Label>
            <Input
              id="u-base"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com"
            />
          </div>
          {isEdit && (
            <div className="flex items-center gap-2">
              <input
                id="u-enabled"
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4"
              />
              <Label htmlFor="u-enabled" className="cursor-pointer">
                enabled
              </Label>
            </div>
          )}
          {err && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
              {err}
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? (isEdit ? "Saving…" : "Creating…") : isEdit ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function formatDate(iso: string): string {
  // server 存 UTC;UI 展示本地时间
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
