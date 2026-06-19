import { CopyIcon, FlaskConicalIcon, PencilIcon, Trash2Icon } from "lucide-react";
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
  type ServerApi,
  type UpstreamCreate,
  type UpstreamDefaultsOut,
  type UpstreamOut,
  type UpstreamNativeApi,
  type UpstreamProvider,
  type UpstreamUpdate,
} from "@/lib/api";
import {
  defaultBindingRows,
  formatUpstreamOptionLabel,
  type UpstreamDefaultScope,
} from "@/lib/upstream-defaults";

const NATIVE_APIS: UpstreamNativeApi[] = ["messages", "completions", "responses"];

export default function Upstreams() {
  const [items, setItems] = useState<UpstreamOut[] | null>(null);
  const [defaults, setDefaults] = useState<UpstreamDefaultsOut | null>(null);
  const [defaultDrafts, setDefaultDrafts] = useState<Record<UpstreamDefaultScope, string>>({
    global: "",
    messages: "",
    completions: "",
    responses: "",
  });
  const [savingScope, setSavingScope] = useState<UpstreamDefaultScope | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [openAdd, setOpenAdd] = useState(false);
  const [toEdit, setToEdit] = useState<UpstreamOut | null>(null);
  const [toCopy, setToCopy] = useState<UpstreamOut | null>(null);
  const [toDelete, setToDelete] = useState<UpstreamOut | null>(null);
  const [restoringMock, setRestoringMock] = useState(false);
  const [testingUpstreamId, setTestingUpstreamId] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const [list, bindings] = await Promise.all([
        api.listUpstreams(),
        api.listUpstreamDefaults(),
      ]);
      setItems([...list].reverse());
      setDefaults(bindings);
      setDefaultDrafts(defaultsToDrafts(bindings));
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
      setItems([]);
      setDefaults(null);
      setDefaultDrafts({
        global: "",
        messages: "",
        completions: "",
        responses: "",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const upstreamOptions = useMemo(
    () =>
      (items ?? []).map((upstream) => ({
        name: upstream.name,
        label: formatUpstreamOptionLabel(upstream),
      })),
    [items],
  );

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

  async function handleSaveDefault(scope: UpstreamDefaultScope) {
    const nextName = defaultDrafts[scope];
    if (!nextName) return;

    setInfo(null);
    setLoadErr(null);
    setSavingScope(scope);
    try {
      const updated = await api.setDefaultUpstream(
        nextName,
        scope === "global" ? undefined : (scope as ServerApi),
      );
      setInfo(`default ${scope} -> ${updated.name}`);
      await load();
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingScope(null);
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

  async function handleTestUpstream(upstream: UpstreamOut) {
    setInfo(null);
    setLoadErr(null);
    setTestingUpstreamId(upstream.id);
    try {
      const result = await api.testUpstream(upstream.id);
      if (result.ok) {
        setInfo(`Test OK · ${upstream.name} · ${result.summary}`);
      } else {
        setLoadErr(
          `Test FAIL · ${upstream.name} · ${result.summary}${
            result.detail ? ` · ${result.detail}` : ""
          }`,
        );
      }
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setTestingUpstreamId(null);
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

      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 && !loadErr ? (
        <EmptyState
          onAdd={() => setOpenAdd(true)}
          onRestoreMock={() => void handleRestoreMock()}
          restoringMock={restoringMock}
        />
      ) : (
        <>
          {defaults && (
            <DefaultsPanel
              defaults={defaults}
              drafts={defaultDrafts}
              options={upstreamOptions}
              savingScope={savingScope}
              onDraftChange={(scope, name) =>
                setDefaultDrafts((current) => ({ ...current, [scope]: name }))
              }
              onSave={(scope) => void handleSaveDefault(scope)}
            />
          )}

          <div className="rounded-lg border border-border">
            <Table className="w-full table-fixed">
            <TableHeader>
              <TableRow className="bg-muted/45 hover:bg-muted/45">
                <TableHead className="w-[10%]">name</TableHead>
                <TableHead className="w-[7%]">provider</TableHead>
                <TableHead className="w-[15%]">native_api</TableHead>
                <TableHead className="w-[10%]">model</TableHead>
                  <TableHead>base_url</TableHead>
                  <TableHead className="w-[9%]">api_key</TableHead>
                  <TableHead className="w-16">enabled</TableHead>
                  <TableHead className="w-48">created_at</TableHead>
                  <TableHead className="w-32 text-right">actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="truncate font-medium" title={u.name}>
                      {u.name}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{u.provider}</Badge>
                    </TableCell>
                    <TableCell
                      className="truncate text-xs text-muted-foreground"
                      title={serverApiLabel(u.native_api)}
                    >
                      {serverApiLabel(u.native_api)}
                    </TableCell>
                    <TableCell
                      className="truncate font-mono text-xs text-muted-foreground"
                      title={u.model ?? ""}
                    >
                      {u.model ?? "-"}
                    </TableCell>
                    <TableCell className="truncate text-xs text-muted-foreground" title={u.base_url}>
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
                              onClick={() => setToEdit(u)}
                            >
                              <PencilIcon />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              title="Copy as new"
                              onClick={() => setToCopy(u)}
                            >
                              <CopyIcon />
                            </Button>
                          </>
                        )}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Test"
                          disabled={testingUpstreamId === u.id}
                          onClick={() => void handleTestUpstream(u)}
                        >
                          <FlaskConicalIcon />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Delete"
                          onClick={() => setToDelete(u)}
                        >
                          <Trash2Icon />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}

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

function DefaultsPanel({
  defaults,
  drafts,
  options,
  savingScope,
  onDraftChange,
  onSave,
}: {
  defaults: UpstreamDefaultsOut;
  drafts: Record<UpstreamDefaultScope, string>;
  options: Array<{ name: string; label: string }>;
  savingScope: UpstreamDefaultScope | null;
  onDraftChange: (scope: UpstreamDefaultScope, name: string) => void;
  onSave: (scope: UpstreamDefaultScope) => void;
}) {
  return (
    <div className="mb-6 rounded-lg border border-border">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Defaults</h2>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/45 hover:bg-muted/45">
            <TableHead className="w-32">server_api</TableHead>
            <TableHead className="w-[22%]">current</TableHead>
            <TableHead>upstream</TableHead>
            <TableHead className="w-24 text-right">action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {defaultBindingRows(defaults).map((row) => {
            const draft = drafts[row.scope];
            const unchanged = draft === (row.upstreamName ?? "");
            const saving = savingScope === row.scope;
            return (
              <TableRow key={row.scope}>
                <TableCell className="font-medium">
                  {row.scope === "global" ? "global" : serverApiLabel(row.scope)}
                </TableCell>
                <TableCell className="truncate text-xs text-muted-foreground">
                  {row.upstreamName ?? "-"}
                </TableCell>
                <TableCell>
                  <Select
                    value={draft || undefined}
                    onValueChange={(value) => onDraftChange(row.scope, value)}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="Select upstream" />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((option) => (
                        <SelectItem key={`${row.scope}-${option.name}`} value={option.name}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8"
                    disabled={!draft || unchanged || saving}
                    onClick={() => onSave(row.scope)}
                  >
                    {saving ? "Saving…" : "Save"}
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
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

  useEffect(() => {
    if (!open) return;
    setErr(null);
    if ((mode === "edit" || mode === "copy") && initial) {
      setName(mode === "copy" ? `${initial.name}-copy` : initial.name);
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
    ? "修改字段后保存;api_key 会回显,留空保存会清空。"
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
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function defaultsToDrafts(defaults: UpstreamDefaultsOut): Record<UpstreamDefaultScope, string> {
  return {
    global: defaults.global ?? "",
    messages: defaults.messages ?? "",
    completions: defaults.completions ?? "",
    responses: defaults.responses ?? "",
  };
}
