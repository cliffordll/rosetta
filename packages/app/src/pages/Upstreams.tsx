import { BugIcon, CopyIcon, PencilIcon, SaveIcon, Trash2Icon } from "lucide-react";
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
  type ModelDefaultsOut,
  type UpstreamCreate,
  type UpstreamOut,
  type UpstreamNativeApi,
  type UpstreamProvider,
  type UpstreamUpdate,
} from "@/lib/api";
import {
  formatUpstreamOptionLabel,
  modelUpstreamGroups,
  type ModelUpstreamGroup,
} from "@/lib/upstream-defaults";

const NATIVE_APIS: UpstreamNativeApi[] = ["messages", "completions", "responses"];

export default function Upstreams() {
  const [items, setItems] = useState<UpstreamOut[] | null>(null);
  const [modelDefaults, setModelDefaults] = useState<ModelDefaultsOut | null>(null);
  const [modelDefaultDrafts, setModelDefaultDrafts] = useState<Record<string, string>>({});
  const [savingModel, setSavingModel] = useState<string | null>(null);
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
        api.listModelDefaults(),
      ]);
      const ordered = [...list].reverse();
      setItems(ordered);
      setModelDefaults(bindings);
      setModelDefaultDrafts(modelDefaultsToDrafts(ordered, bindings));
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
      setItems([]);
      setModelDefaults(null);
      setModelDefaultDrafts({});
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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

  const modelGroups = useMemo(
    () => modelUpstreamGroups(items ?? [], modelDefaults ?? {}),
    [items, modelDefaults],
  );

  async function handleSaveModelDefault(model: string) {
    const nextName = modelDefaultDrafts[model];
    if (!nextName) return;

    setInfo(null);
    setLoadErr(null);
    setSavingModel(model);
    try {
      const updated = await api.setModelDefaultUpstream(nextName, model);
      setInfo(`model default ${model} -> ${updated.name}`);
      await load();
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingModel(null);
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
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex shrink-0 items-center justify-between">
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
          <div className="flex min-h-0 flex-1 flex-col gap-4">
            {/* 上: Model defaults (4/10) */}
            <div className="flex min-h-0 flex-[4] flex-col">
              {modelDefaults && (
                <ModelDefaultsPanel
                  groups={modelGroups}
                  drafts={modelDefaultDrafts}
                  savingModel={savingModel}
                  onDraftChange={(model, name) =>
                    setModelDefaultDrafts((current) => ({ ...current, [model]: name }))
                  }
                  onSave={(model) => void handleSaveModelDefault(model)}
                />
              )}
            </div>

            {/* 下: Upstreams 表格 */}
            <div className="flex min-h-0 flex-[6] flex-col">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-muted-foreground">
                  Upstreams
                </h2>
              </div>
              <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
                <table className="w-full table-fixed caption-bottom text-sm">
                  <TableHeader>
                    <TableRow className="hover:bg-muted/45">
                      <TableHead className="sticky top-0 z-20 w-[9%] bg-muted">
                        name
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 w-[7%] bg-muted">
                        provider
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 w-[12%] bg-muted">
                        native_api
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 w-[8%] bg-muted">
                        model
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 bg-muted">
                        base_url
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 w-[11%] bg-muted">
                        api_key
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 w-[7%] bg-muted">
                        enabled
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 w-44 bg-muted">
                        created_at
                      </TableHead>
                      <TableHead className="sticky top-0 z-20 w-28 bg-muted text-right">
                        actions
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody className="[&_tr:last-child]:border-b">
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
                            <span
                              className={u.enabled ? "font-medium" : "text-muted-foreground"}
                            >
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
                              title="Test upstream"
                              disabled={testingUpstreamId === u.id}
                              onClick={() => void handleTestUpstream(u)}
                            >
                              <BugIcon />
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
                </table>
              </div>
            </div>
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

function ModelDefaultsPanel({
  groups,
  drafts,
  savingModel,
  onDraftChange,
  onSave,
}: {
  groups: ModelUpstreamGroup[];
  drafts: Record<string, string>;
  savingModel: string | null;
  onDraftChange: (model: string, name: string) => void;
  onSave: (model: string) => void;
}) {
  const duplicateGroups = groups.filter((group) => group.upstreams.length > 1);
  const singleGroups = groups.filter((group) => group.upstreams.length === 1);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">
          Model defaults
        </h2>
        <p className="text-xs text-muted-foreground">
          无 r-upstream 时按 body.model 匹配 upstream；同一个 model 对应多个 upstream 时，必须在这里指定默认 upstream。
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
      {groups.length === 0 ? (
        <div className="px-4 py-4 text-sm text-muted-foreground">
          当前没有配置 model 的 upstream。客户端必须传 r-upstream，或先给 upstream 配置 model。
        </div>
      ) : (
        <table className="w-full caption-bottom text-sm">
          <TableHeader>
            <TableRow className="bg-muted/45 hover:bg-muted/45">
              <TableHead className="sticky top-0 z-20 w-[22%] bg-muted">model</TableHead>
              <TableHead className="sticky top-0 z-20 w-[12%] bg-muted">status</TableHead>
              <TableHead className="sticky top-0 z-20 w-[22%] bg-muted">
                current default
              </TableHead>
              <TableHead className="sticky top-0 z-20 bg-muted">upstream</TableHead>
              <TableHead className="sticky top-0 z-20 w-24 bg-muted text-right">
                action
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="[&_tr:last-child]:border-b">
            {duplicateGroups.map((group) => {
              const draft = drafts[group.model] ?? "";
              const unchanged = draft === (group.defaultUpstreamName ?? "");
              const saving = savingModel === group.model;
              return (
                <TableRow key={group.model}>
                  <TableCell className="truncate font-mono text-xs" title={group.model}>
                    {group.model}
                  </TableCell>
                  <TableCell>
                    <Badge variant={group.defaultUpstreamName ? "outline" : "destructive"}>
                      {group.defaultUpstreamName ? "configured" : "required"}
                    </Badge>
                  </TableCell>
                  <TableCell className="truncate text-xs text-muted-foreground">
                    {group.defaultUpstreamName ?? "-"}
                  </TableCell>
                  <TableCell>
                    <Select
                      value={draft || undefined}
                      onValueChange={(value) => onDraftChange(group.model, value)}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Select upstream" />
                      </SelectTrigger>
                      <SelectContent>
                        {group.upstreams.map((upstream) => (
                          <SelectItem key={`${group.model}-${upstream.name}`} value={upstream.name}>
                            {formatUpstreamOptionLabel(upstream)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="icon-sm"
                      title={saving ? "Saving…" : `Save ${group.model} default`}
                      disabled={!draft || unchanged || saving}
                      onClick={() => onSave(group.model)}
                    >
                      <SaveIcon />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
            {singleGroups.map((group) => {
              const upstream = group.upstreams[0];
              return (
                <TableRow key={group.model}>
                  <TableCell className="truncate font-mono text-xs" title={group.model}>
                    {group.model}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">unique</Badge>
                  </TableCell>
                  <TableCell className="truncate text-xs text-muted-foreground">
                    {upstream.name}
                  </TableCell>
                  <TableCell className="truncate text-xs text-muted-foreground">
                    {formatUpstreamOptionLabel(upstream)}
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">auto</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </table>
      )}
      </div>
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
 * - `edit`:initial 预填 → PUT updateUpstream(只发改过的字段;api_key 留空 = 不动)
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
      : "新建上游 upstream。";

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
            <Label htmlFor="u-name">
              name{" "}
              <span className="text-xs text-muted-foreground">
                (唯一标识 · r-upstream header 的值)
              </span>
            </Label>
            <Input
              id="u-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. ant-main"
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-native-api">
              native_api{" "}
              <span className="text-xs text-muted-foreground">
                (API 格式 · 决定 base_url 追加的路径)
              </span>
            </Label>
            <Select value={nativeApi} onValueChange={(v) => setNativeApi(v as UpstreamNativeApi)}>
              <SelectTrigger id="u-native-api" className="w-full">
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
            <Label htmlFor="u-provider">
              provider{" "}
              <span className="text-xs text-muted-foreground">
                (暂时只用于区分 upstream 类别)
              </span>
            </Label>
            <Select value={provider} onValueChange={(v) => setProvider(v as UpstreamProvider)}>
              <SelectTrigger id="u-provider" className="w-full">
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
            <Label htmlFor="u-base">
              base_url{" "}
              <span className="text-xs text-muted-foreground">
                (填根地址 · rosetta 会按 native API 自动追加 /v1/…)
              </span>
            </Label>
            <Input
              id="u-base"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com (不要带 /v1)"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-model">
              model{" "}
              <span className="text-xs text-muted-foreground">
                (可选 · 客户端不传 r-upstream 时，按 body.model 自动匹配到此上游)
              </span>
            </Label>
            <Input
              id="u-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. claude-haiku-4-5"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-key">
              api_key{" "}
              <span className="text-xs text-muted-foreground">
                {isEdit
                  ? "(已回显 · 清空保存 = 删除)"
                  : isCopy
                    ? "(从原 upstream 带过来 · 可修改)"
                    : "(可选 · 客户端不传时 server 用此 key 兜底)"}
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

function modelDefaultsToDrafts(
  upstreams: UpstreamOut[],
  defaults: ModelDefaultsOut,
): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const group of modelUpstreamGroups(upstreams, defaults)) {
    if (group.upstreams.length <= 1) continue;
    drafts[group.model] = group.defaultUpstreamName ?? "";
  }
  return drafts;
}
