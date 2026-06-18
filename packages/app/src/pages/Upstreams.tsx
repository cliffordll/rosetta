import { CopyIcon, PencilIcon, StarIcon, Trash2Icon } from "lucide-react";
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
  serverApiLabel,
  type UpstreamCreate,
  type UpstreamOut,
  type UpstreamNativeApi,
  type UpstreamProvider,
  type UpstreamUpdate,
} from "@/lib/api";

const NATIVE_APIS: UpstreamNativeApi[] = ["messages", "completions", "responses"];

// native API 分组渲染顺序;`any` 是 mock 占位,放最后
const GROUP_ORDER: string[] = ["messages", "completions", "responses", "any"];

const COLUMN_COUNT = 9;

export default function Upstreams() {
  const [items, setItems] = useState<UpstreamOut[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [openAdd, setOpenAdd] = useState(false);
  const [toEdit, setToEdit] = useState<UpstreamOut | null>(null);
  const [toCopy, setToCopy] = useState<UpstreamOut | null>(null);
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

  // 按 upstream native API 分组(messages → completions → responses → any),空组不渲染
  const grouped = useMemo(() => {
    if (!items) return [] as Array<{ nativeApi: string; rows: UpstreamOut[] }>;
    const buckets = new Map<string, UpstreamOut[]>();
    for (const u of items) {
      const arr = buckets.get(u.native_api) ?? [];
      arr.push(u);
      buckets.set(u.native_api, arr);
    }
    return GROUP_ORDER.filter((p) => buckets.has(p)).map((p) => ({
      nativeApi: p,
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
      setInfo(`upstream '${updated.name}' is now default for native_api=${updated.native_api}`);
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
        <div className="rounded-lg border border-border overflow-x-auto">
          <Table className="w-full table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[14%]">name</TableHead>
                <TableHead className="w-[10%]">provider</TableHead>
                <TableHead className="w-[18%]">model</TableHead>
                <TableHead>base_url</TableHead>
                <TableHead className="w-[18%]">api_key</TableHead>
                <TableHead className="w-16">enabled</TableHead>
                <TableHead className="w-16">default</TableHead>
                <TableHead className="w-32">created_at</TableHead>
                <TableHead className="w-28 text-right">actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {grouped.map((group) => (
                <GroupSection
                  key={group.nativeApi}
                  nativeApi={group.nativeApi}
                  rows={group.rows}
                  onSetDefault={(u) => void handleSetDefault(u.name)}
                  onEdit={(u) => setToEdit(u)}
                  onCopy={(u) => setToCopy(u)}
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

      <UpstreamFormDialog
        mode="copy"
        initial={toCopy}
        open={toCopy !== null}
        onOpenChange={(o) => !o && setToCopy(null)}
        onSubmitted={async () => {
          setToCopy(null);
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
  nativeApi,
  rows,
  onSetDefault,
  onEdit,
  onCopy,
  onDelete,
}: {
  nativeApi: string;
  rows: UpstreamOut[];
  onSetDefault: (u: UpstreamOut) => void;
  onEdit: (u: UpstreamOut) => void;
  onCopy: (u: UpstreamOut) => void;
  onDelete: (u: UpstreamOut) => void;
}) {
  return (
    <>
      <TableRow className="bg-muted/40 hover:bg-muted/40">
        <TableCell
          colSpan={COLUMN_COUNT}
          className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
        >
          native_api={serverApiLabel(nativeApi)}{" "}
          <span className="text-muted-foreground/70">· {rows.length}</span>
        </TableCell>
      </TableRow>
      {rows.map((u) => (
        <TableRow key={u.id}>
          <TableCell className="truncate font-medium" title={u.name}>
            {u.name}
          </TableCell>
          <TableCell>
            <Badge variant="outline">{u.provider}</Badge>
          </TableCell>
          <TableCell
            className="truncate font-mono text-xs text-muted-foreground"
            title={u.model ?? ""}
          >
            {u.model ?? "-"}
          </TableCell>
          <TableCell
            className="truncate text-xs text-muted-foreground"
            title={u.base_url}
          >
            {u.base_url}
          </TableCell>
          <TableCell
            className="truncate font-mono text-xs text-muted-foreground"
            title={u.api_key ?? ""}
          >
            {u.api_key ?? "-"}
          </TableCell>
          <TableCell className="text-xs">
            <span className="inline-flex items-center gap-1.5">
              <span
                className={`size-2 rounded-full ${
                  u.enabled ? "bg-emerald-500" : "bg-muted-foreground/40"
                }`}
                aria-hidden
              />
              <span className={u.enabled ? "font-medium" : "text-muted-foreground"}>
                {u.enabled ? "on" : "off"}
              </span>
            </span>
          </TableCell>
          <TableCell>
            {u.native_api !== "any" && (
              <Button
                variant="ghost"
                size="icon-sm"
                title={
                  u.is_default
                    ? "Default for this native API"
                    : "Set as default for this native API"
                }
                disabled={u.is_default}
                onClick={() => onSetDefault(u)}
              >
                <StarIcon
                  className={
                    u.is_default
                      ? "fill-amber-400 text-amber-500"
                      : "text-muted-foreground"
                  }
                />
              </Button>
            )}
          </TableCell>
          <TableCell
            className="truncate font-mono text-xs text-muted-foreground"
            title={u.created_at}
          >
            {formatDate(u.created_at)}
          </TableCell>
          <TableCell className="text-right">
            <div className="flex justify-end gap-1">
              {u.provider !== "mock" && (
                <>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="Edit"
                    onClick={() => onEdit(u)}
                  >
                    <PencilIcon />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="Copy as new"
                    onClick={() => onCopy(u)}
                  >
                    <CopyIcon />
                  </Button>
                </>
              )}
              <Button
                variant="ghost"
                size="icon-sm"
                title="Delete"
                onClick={() => onDelete(u)}
              >
                <Trash2Icon />
              </Button>
            </div>
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

type FormMode = "add" | "edit" | "copy";

/**
 * Add / Edit / Copy 共用对话框。
 *
 * - `add`:空白表单 → POST createUpstream
 * - `edit`:initial 预填 → PUT updateUpstream(只发改过的字段;native API 变化时
 *   server 自动清 is_default;api_key 留空 = 不动)
 * - `copy`:initial 预填(name 加 `-copy` 后缀,api_key 不带) → POST createUpstream;
 *   等价于"以选中行为模板新建一个"
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
  const [nativeApi, setNativeApi] = useState<UpstreamNativeApi>("messages");
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
    if ((mode === "edit" || mode === "copy") && initial) {
      // copy 时 name 加后缀避免 UNIQUE 冲突;edit 时保留原 name
      setName(mode === "copy" ? `${initial.name}-copy` : initial.name);
      // initial.native_api 可能是 "any"(mock),但 mock 不让编辑/复制,这里保险下
      setNativeApi(
        (NATIVE_APIS as readonly string[]).includes(initial.native_api)
          ? (initial.native_api as UpstreamNativeApi)
          : "messages",
      );
      setProvider(initial.provider as UpstreamProvider);
      setApiKey(initial.api_key ?? "");
      setModel(initial.model ?? "");
      setBaseUrl(initial.base_url);
      setEnabled(initial.enabled);
    } else {
      setName("");
      setNativeApi("messages");
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
      // add 和 copy 都走 createUpstream,语义都是"新建一行";copy 仅在预填上不同
      if (mode === "add" || mode === "copy") {
        const payload: UpstreamCreate = {
          name: name.trim(),
          native_api: nativeApi,
          provider,
          api_key: apiKey.trim() || undefined,
          model: model.trim() || undefined,
          base_url: baseUrl.trim(),
        };
        await api.createUpstream(payload);
      } else if (initial) {
        // 只发与原值不同的字段;api_key 为空表示清空该字段
        const payload: UpstreamUpdate = {};
        if (name.trim() !== initial.name) payload.name = name.trim();
        if (nativeApi !== initial.native_api) payload.native_api = nativeApi;
        if (provider !== initial.provider) payload.provider = provider;
        if (baseUrl.trim() !== initial.base_url) payload.base_url = baseUrl.trim();
        if (enabled !== initial.enabled) payload.enabled = enabled;
        const trimmedApiKey = apiKey.trim();
        const initialApiKey = initial.api_key ?? "";
        if (trimmedApiKey !== initialApiKey) {
          payload.api_key = trimmedApiKey || null;
        }
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
  const isCopy = mode === "copy";

  const title = isEdit ? "Edit upstream" : isCopy ? "Copy upstream" : "Add upstream";
  const description = isEdit
    ? "修改字段后保存;api_key 会回显,留空保存会清空。改 upstream native API 时如果该行是 default,会自动清掉。"
    : isCopy
      ? `以 '${initial?.name}' 为模板新建一行;name 已加 -copy 后缀避免冲突,api_key 会带过来,可按需修改。`
      : "新建上游 upstream;model 留空时,客户端必须自带 body.model。base_url 填根地址,不要带 /v1 或具体 API 路径。";

  const keyStatus =
    isEdit && initial
      ? initial.api_key
        ? "当前已保存 api_key;此处已回显。清空后保存会删除该 key。"
        : "当前未保存 api_key;填值后保存。"
      : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
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
            <Label htmlFor="u-native-api">upstream native API</Label>
            <Select value={nativeApi} onValueChange={(v) => setNativeApi(v as UpstreamNativeApi)}>
              <SelectTrigger id="u-native-api">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {NATIVE_APIS.map((t) => (
                  <SelectItem key={t} value={t}>
                    {serverApiLabel(t)}
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
                {isEdit
                  ? "(已回显 · 清空保存 = 删除)"
                  : isCopy
                    ? "(从原 upstream 带过来 · 可修改)"
                    : "(可选)"}
              </span>
            </Label>
            <Input
              id="u-key"
              type="text"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
            {keyStatus && <p className="text-xs text-muted-foreground">{keyStatus}</p>}
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
              placeholder="https://api.example.com (不要带 /v1)"
            />
            <p className="text-xs text-muted-foreground">
              rosetta 会按 upstream native API 自动追加 /v1/messages、/v1/chat/completions 或
              /v1/responses。
            </p>
          </div>
          {(isEdit || isCopy) && (
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
