import { isTauri } from "@/lib/updater";
import {
  BugIcon,
  CopyIcon,
  Eye,
  EyeOff,
  PenBoxIcon,
  Trash2Icon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
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
  type ModelOut,
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

const UPSTREAM_TABLE_COLUMNS = [
  "name",
  "provider",
  "native_api",
  "model",
  "base_url",
  "api_key",
  "enabled",
  "created_at",
  "actions",
] as const;
type UpstreamTableColumn = (typeof UPSTREAM_TABLE_COLUMNS)[number];

type UpstreamColumnWidths = Record<UpstreamTableColumn, number>;

const TABLE_CELL = "p-1.5 text-xs text-muted-foreground";
const TABLE_NAME = `${TABLE_CELL} font-medium truncate`;
const TABLE_TEXT = `${TABLE_CELL} truncate`;
const TABLE_TECH = `${TABLE_TEXT} font-mono tabular-nums`;
const FORM_LABEL = "text-sm text-muted-foreground";
const FORM_LABEL_HINT = "text-xs text-muted-foreground";

const DEFAULT_UPSTREAM_COLUMN_WIDTHS: UpstreamColumnWidths = {
  name: 9,
  provider: 6,
  native_api: 11,
  model: 9,
  base_url: 11,
  api_key: 8,
  enabled: 6,
  created_at: 9,
  actions: 13,
};

const MIN_UPSTREAM_COLUMN_WIDTHS: UpstreamColumnWidths = {
  name: 6,
  provider: 4,
  native_api: 6,
  model: 8,
  base_url: 8,
  api_key: 8,
  enabled: 4,
  created_at: 6,
  actions: 13,
};

const MODEL_DEFAULT_COLUMNS = ["model", "alias", "status", "current_default", "upstream", "action"] as const;
type ModelDefaultColumn = (typeof MODEL_DEFAULT_COLUMNS)[number];
type ModelDefaultWidths = Record<ModelDefaultColumn, number>;

const DEFAULT_MODEL_DEFAULT_WIDTHS: ModelDefaultWidths = {
  model: 18,
  alias: 18,
  status: 10,
  current_default: 18,
  upstream: 28,
  action: 8,
};

const MIN_MODEL_DEFAULT_WIDTHS: ModelDefaultWidths = {
  model: 10,
  alias: 10,
  status: 8,
  current_default: 10,
  upstream: 15,
  action: 8,
};

export default function Upstreams() {
  const [items, setItems] = useState<UpstreamOut[] | null>(null);
  const [modelDefaults, setModelDefaults] = useState<ModelDefaultsOut | null>(null);
  const [models, setModels] = useState<ModelOut[] | null>(null);
  const [savingModel, setSavingModel] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [openAdd, setOpenAdd] = useState(false);
  const [toEdit, setToEdit] = useState<UpstreamOut | null>(null);
  const [toCopy, setToCopy] = useState<UpstreamOut | null>(null);
  const [toDelete, setToDelete] = useState<UpstreamOut | null>(null);
  const [modelToEdit, setModelToEdit] = useState<ModelUpstreamGroup | null>(null);
  const [restoringMock, setRestoringMock] = useState(false);
  const [testingUpstreamId, setTestingUpstreamId] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [upstreamColumnWidths, setUpstreamColumnWidths] = useState<UpstreamColumnWidths>(
    () => ({
      ...DEFAULT_UPSTREAM_COLUMN_WIDTHS,
      ...(isTauri() ? { actions: 12 } : { actions: 10 }),
    }),
  );
  const upstreamResizeRef = useRef<{
    startX: number;
    tableWidth: number;
    left: UpstreamTableColumn;
    right: UpstreamTableColumn;
    leftWidth: number;
    rightWidth: number;
  } | null>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const [list, bindings, modelList] = await Promise.all([
        api.listUpstreams(),
        api.listModelDefaults(),
        api.listModels(),
      ]);
      const ordered = [...list].reverse();
      setItems(ordered);
      setModelDefaults(bindings);
      setModels(modelList);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
      setItems([]);
      setModelDefaults(null);
      setModels(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function startUpstreamColumnResize(
    left: UpstreamTableColumn,
    right: UpstreamTableColumn,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) {
    event.preventDefault();
    const table = event.currentTarget.closest("table");
    const tableWidth = table?.getBoundingClientRect().width ?? 1;
    upstreamResizeRef.current = {
      startX: event.clientX,
      tableWidth,
      left,
      right,
      leftWidth: upstreamColumnWidths[left],
      rightWidth: upstreamColumnWidths[right],
    };

    const onPointerMove = (moveEvent: PointerEvent) => {
      const state = upstreamResizeRef.current;
      if (!state) return;
      const delta = ((moveEvent.clientX - state.startX) / state.tableWidth) * 100;
      const minLeft = MIN_UPSTREAM_COLUMN_WIDTHS[state.left];
      const minRight = MIN_UPSTREAM_COLUMN_WIDTHS[state.right];
      const pairTotal = state.leftWidth + state.rightWidth;
      const nextLeft = Math.min(
        // actions 列已到最小宽度时,改为单边拉伸,不压缩 actions
        state.right === "actions" && state.rightWidth <= minRight + 0.5
          ? 100
          : pairTotal - minRight,
        Math.max(minLeft, state.leftWidth + delta),
      );
      const nextRight = state.right === "actions" && state.rightWidth <= minRight + 0.5
        ? state.rightWidth // 不压缩 actions
        : pairTotal - nextLeft;
      setUpstreamColumnWidths((current) => ({
        ...current,
        [state.left]: nextLeft,
        [state.right]: nextRight,
      }));
    };

    const onPointerUp = () => {
      upstreamResizeRef.current = null;
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }
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

  async function handleSaveModelConfig(model: string, upstreamId: string | null, alias: string) {
    const current = models?.find((item) => item.name === model);
    const currentAlias = current?.alias ?? "";
    const nextAlias = alias.trim();
    const currentDefault = modelDefaults?.[model] ?? "";
    const nextDefault = upstreamId ?? "";

    setInfo(null);
    setLoadErr(null);
    setSavingModel(model);
    try {
      if (nextAlias !== currentAlias) {
        await api.setModelAlias(model, nextAlias || null);
      }
      if (nextDefault && nextDefault !== currentDefault) {
        await api.setModelDefaultUpstream(nextDefault, model);
      }
      setInfo(`model ${model} updated`);
      setModelToEdit(null);
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
      await load();
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
                  models={models ?? []}
                  savingModel={savingModel}
                  onEdit={setModelToEdit}
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
              <div className="relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden rounded-lg border border-border">
                <table className="w-full table-fixed caption-bottom text-sm">
                  <colgroup>
                    {UPSTREAM_TABLE_COLUMNS.map((column) => (
                      <col
                        key={column}
                        style={{
                          width: `${upstreamColumnWidths[column]}%`,
                          ...(column === "actions" && isTauri()
                            ? { minWidth: 110 }
                            : {}),
                        }}
                      />
                    ))}
                  </colgroup>
                  <TableHeader className="sticky top-0 z-20">
                    <TableRow className="hover:bg-muted/45">
                      <ResizableUpstreamHead
                        label="name"
                        left="name"
                        right="provider"
                        onResize={startUpstreamColumnResize}
                      />
                      <ResizableUpstreamHead
                        label="provider"
                        left="provider"
                        right="native_api"
                        onResize={startUpstreamColumnResize}
                      />
                      <ResizableUpstreamHead
                        label="native_api"
                        left="native_api"
                        right="model"
                        onResize={startUpstreamColumnResize}
                      />
                      <ResizableUpstreamHead
                        label="model"
                        left="model"
                        right="base_url"
                        onResize={startUpstreamColumnResize}
                      />
                      <ResizableUpstreamHead
                        label="base_url"
                        left="base_url"
                        right="api_key"
                        onResize={startUpstreamColumnResize}
                      />
                      <ResizableUpstreamHead
                        label="api_key"
                        left="api_key"
                        right="enabled"
                        onResize={startUpstreamColumnResize}
                      />
                      <ResizableUpstreamHead
                        label="enabled"
                        left="enabled"
                        right="created_at"
                        align="center"
                        onResize={startUpstreamColumnResize}
                      />
                      <ResizableUpstreamHead
                        label="created_at"
                        left="created_at"
                        right="actions"
                        onResize={startUpstreamColumnResize}
                      />
                      <TableHead className="bg-muted text-right select-none">
                        actions
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody className="[&_tr:last-child]:border-b [&_tr]:h-10">
                    {items.map((u) => (
                      <TableRow key={u.id}>
                        <TableCell className={TABLE_NAME} title={u.name}>
                          {u.name}
                        </TableCell>
                        <TableCell className={TABLE_CELL}>
                          <Badge variant="outline">{u.provider}</Badge>
                        </TableCell>
                        <TableCell className={TABLE_TEXT}
                          title={serverApiLabel(u.native_api)}
                        >
                          {serverApiLabel(u.native_api)}
                        </TableCell>
                        <TableCell className={TABLE_TECH}
                          title={u.model ?? ""}
                        >
                          {u.model ?? "-"}
                        </TableCell>
                        <TableCell className={TABLE_TEXT}
                          title={u.base_url}
                        >
                          {u.base_url}
                        </TableCell>
                        <TableCell className={TABLE_TECH}
                          title={maskApiKey(u.api_key)}
                        >
                          {maskApiKey(u.api_key)}
                        </TableCell>
                        <TableCell className={`${TABLE_CELL} text-center`}>
                          <span className="inline-flex items-center justify-center gap-1.5">
                            <span
                              className={`size-2 rounded-full ${
                                u.enabled ? "bg-emerald-500" : "bg-muted-foreground/40"
                              }`}
                              aria-hidden
                            />
                            <span className={u.enabled ? "font-medium" : ""}>
                              {u.enabled ? "on" : "off"}
                            </span>
                          </span>
                        </TableCell>
                        <TableCell className={TABLE_TECH}
                          title={formatDate(u.created_at)}
                        >
                          {formatDate(u.created_at)}
                        </TableCell>
                        <TableCell className={`${TABLE_CELL} overflow-hidden text-right`}>
                          <div className="flex justify-end gap-1 overflow-hidden">
                            {u.provider !== "mock" && (
                              <>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  className="hover:bg-muted-foreground/15"
                                  title="Edit"
                                  onClick={() => setToEdit(u)}
                                >
                                  <PenBoxIcon />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  className="hover:bg-muted-foreground/15"
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
                              className="hover:bg-muted-foreground/15"
                              title={u.test_result === "ok" ? "Test passed" : u.test_result === "fail" ? "Test failed" : "Test upstream"}
                              disabled={testingUpstreamId === u.id}
                              onClick={() => void handleTestUpstream(u)}
                            >
                              <BugIcon className={u.test_result === "ok" ? "text-emerald-500" : u.test_result === "fail" ? "text-destructive" : ""} />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              className="hover:bg-muted-foreground/15"
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
      <ModelConfigDialog
        group={modelToEdit}
        model={models?.find((item) => item.name === modelToEdit?.model) ?? null}
        open={modelToEdit !== null}
        saving={savingModel === modelToEdit?.model}
        onOpenChange={(open) => !open && setModelToEdit(null)}
        onSubmit={(model, upstreamId, alias) =>
          void handleSaveModelConfig(model, upstreamId, alias)
        }
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

function ResizableUpstreamHead({
  label,
  left,
  right,
  align = "left",
  onResize,
}: {
  label: string;
  left: UpstreamTableColumn;
  right: UpstreamTableColumn;
  align?: "left" | "center";
  onResize: (
    left: UpstreamTableColumn,
    right: UpstreamTableColumn,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) => void;
}) {
  return (
    <TableHead className="bg-muted relative select-none">
      <div className={`truncate pr-3 ${align === "center" ? "text-center" : ""}`}>
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

function ModelDefaultsPanel({
  groups,
  models,
  savingModel,
  onEdit,
}: {
  groups: ModelUpstreamGroup[];
  models: ModelOut[];
  savingModel: string | null;
  onEdit: (group: ModelUpstreamGroup) => void;
}) {
  const [mdColWidths, setMdColWidths] = useState<ModelDefaultWidths>(DEFAULT_MODEL_DEFAULT_WIDTHS);
  const mdResizeRef = useRef<{
    startX: number;
    tableWidth: number;
    left: ModelDefaultColumn;
    right: ModelDefaultColumn;
    leftWidth: number;
    rightWidth: number;
  } | null>(null);

  function startMdResize(
    left: ModelDefaultColumn,
    right: ModelDefaultColumn,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) {
    event.preventDefault();
    const table = event.currentTarget.closest("table");
    const tableWidth = table?.getBoundingClientRect().width ?? 1;
    mdResizeRef.current = {
      startX: event.clientX,
      tableWidth,
      left,
      right,
      leftWidth: mdColWidths[left],
      rightWidth: mdColWidths[right],
    };

    const onPointerMove = (moveEvent: PointerEvent) => {
      const state = mdResizeRef.current;
      if (!state) return;
      const delta = ((moveEvent.clientX - state.startX) / state.tableWidth) * 100;
      const minLeft = MIN_MODEL_DEFAULT_WIDTHS[state.left];
      const minRight = MIN_MODEL_DEFAULT_WIDTHS[state.right];
      const pairTotal = state.leftWidth + state.rightWidth;
      const nextLeft = Math.min(
        state.right === "action" && state.rightWidth <= minRight + 0.5
          ? 100
          : pairTotal - minRight,
        Math.max(minLeft, state.leftWidth + delta),
      );
      const nextRight = state.right === "action" && state.rightWidth <= minRight + 0.5
        ? state.rightWidth
        : pairTotal - nextLeft;
      setMdColWidths((current) => ({
        ...current,
        [state.left]: nextLeft,
        [state.right]: nextRight,
      }));
    };

    const onPointerUp = () => {
      mdResizeRef.current = null;
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  function MdResizableHead({ label, left, right, align = "left" }: {
    label: string;
    left: ModelDefaultColumn;
    right: ModelDefaultColumn;
    align?: "left" | "center";
  }) {
    return (
      <TableHead className="bg-muted relative select-none" style={{ width: `${mdColWidths[left]}%` }}>
        <div className={`truncate pr-3 ${align === "center" ? "text-center" : ""}`}>
          {label}
        </div>
        <button
          type="button"
          aria-label={`Resize ${label} column`}
          className="absolute right-0 top-0 z-30 h-full w-3 cursor-col-resize touch-none border-r border-transparent hover:border-ring focus:border-ring focus:outline-none"
          onPointerDown={(event) => startMdResize(left, right, event)}
        />
      </TableHead>
    );
  }

  const modelByName = new Map(models.map((model) => [model.name, model]));
  const duplicateGroups = groups.filter((group) => group.upstreams.length > 1);
  const singleGroups = groups.filter((group) => group.upstreams.length === 1);
  const orderedGroups = [...duplicateGroups, ...singleGroups];

  function renderRow(group: ModelUpstreamGroup) {
    const model = modelByName.get(group.model);
    const defaultUpstream = group.upstreams.find(
      (upstream) => upstream.id === group.defaultUpstreamId,
    );
    const uniqueUpstream = group.upstreams.length === 1 ? group.upstreams[0] : null;
    const currentUpstream = defaultUpstream ?? uniqueUpstream;
    const needsDefault = group.upstreams.length > 1 && !group.defaultUpstreamId;
    const saving = savingModel === group.model;

    return (
      <TableRow key={group.model}>
        <TableCell className={TABLE_TECH} title={group.model}>
          {group.model}
        </TableCell>
        <TableCell className={TABLE_TEXT} title={model?.alias ?? ""}>
          {model?.alias || "-"}
        </TableCell>
        <TableCell className={TABLE_CELL}>
          <Badge variant={needsDefault ? "destructive" : "outline"}>
            {needsDefault ? "required" : group.upstreams.length > 1 ? "configured" : "unique"}
          </Badge>
        </TableCell>
        <TableCell className={TABLE_TEXT} title={currentUpstream?.name ?? ""}>
          {currentUpstream?.name ?? "-"}
        </TableCell>
        <TableCell className={TABLE_TEXT} title={group.upstreams.map(formatUpstreamOptionLabel).join("\n")}>
          {group.upstreams.map((upstream) => upstream.name).join(", ")}
        </TableCell>
        <TableCell className={`${TABLE_CELL} text-right`}>
          <Button
            variant="ghost"
            size="icon-sm"
            className="hover:bg-muted-foreground/15"
            title={saving ? "Saving..." : `Edit ${group.model}`}
            disabled={saving}
            onClick={() => onEdit(group)}
          >
            <PenBoxIcon />
          </Button>
        </TableCell>
      </TableRow>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">
          Model defaults
        </h2>
        <p className={FORM_LABEL_HINT}>
          无 r-upstream 时按 body.model 匹配 upstream；同一个 model 对应多个 upstream 时，必须设置默认 upstream。
        </p>
      </div>
      <div className="relative min-h-0 flex-1 overflow-auto rounded-lg border border-border">
      {groups.length === 0 ? (
        <div className="px-4 py-4 text-sm text-muted-foreground">
          当前没有配置 model 的 upstream。客户端必须传 r-upstream，或先给 upstream 配置 model。
        </div>
      ) : (
        <table className="w-full table-fixed caption-bottom text-sm">
          <colgroup>
            {MODEL_DEFAULT_COLUMNS.map((column) => (
              <col key={column} style={{ width: `${mdColWidths[column]}%` }} />
            ))}
          </colgroup>
          <TableHeader className="sticky top-0 z-20">
            <TableRow className="bg-muted/45 hover:bg-muted/45">
              <MdResizableHead label="model" left="model" right="alias" />
              <MdResizableHead label="alias" left="alias" right="status" />
              <MdResizableHead label="status" left="status" right="current_default" />
              <MdResizableHead label="current default" left="current_default" right="upstream" />
              <MdResizableHead label="upstreams" left="upstream" right="action" />
              <TableHead className="bg-muted text-right select-none" style={{ width: `${mdColWidths["action"]}%` }}>
                action
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="[&_tr:last-child]:border-b [&_tr]:h-10">
            {orderedGroups.map(renderRow)}
          </TableBody>
        </table>
      )}
      </div>
    </div>
  );
}

function ModelConfigDialog({
  group,
  model,
  open,
  saving,
  onOpenChange,
  onSubmit,
}: {
  group: ModelUpstreamGroup | null;
  model: ModelOut | null;
  open: boolean;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (model: string, upstreamId: string | null, alias: string) => void;
}) {
  const [alias, setAlias] = useState("");
  const [defaultUpstreamId, setDefaultUpstreamId] = useState("");

  useEffect(() => {
    if (!open || !group) return;
    setAlias(model?.alias ?? "");
    setDefaultUpstreamId(group.defaultUpstreamId ?? (group.upstreams.length === 1 ? group.upstreams[0].id : ""));
  }, [open, group, model]);

  const canChooseDefault = (group?.upstreams.length ?? 0) > 1;
  const selectedUpstream = group?.upstreams.find((upstream) => upstream.id === defaultUpstreamId);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit model</DialogTitle>
          <DialogDescription>
            {group?.model ?? ""}
          </DialogDescription>
        </DialogHeader>
        {group && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="model-alias" className={FORM_LABEL}>
                alias <span className={FORM_LABEL_HINT}>(写入 Setup 生成的客户端 model)</span>
              </Label>
              <Input
                id="model-alias"
                value={alias}
                onChange={(event) => setAlias(event.target.value)}
                placeholder="same as model"
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="model-default-upstream" className={FORM_LABEL}>
                default upstream <span className={FORM_LABEL_HINT}>(多个 upstream 共享 model 时生效)</span>
              </Label>
              {canChooseDefault ? (
                <Select value={defaultUpstreamId || undefined} onValueChange={setDefaultUpstreamId}>
                  <SelectTrigger id="model-default-upstream" className="w-full">
                    <SelectValue placeholder="Select upstream" />
                  </SelectTrigger>
                  <SelectContent>
                    {group.upstreams.map((upstream) => (
                      <SelectItem key={`${group.model}-${upstream.id}`} value={upstream.id}>
                        {formatUpstreamOptionLabel(upstream)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id="model-default-upstream"
                  value={selectedUpstream ? formatUpstreamOptionLabel(selectedUpstream) : "-"}
                  readOnly
                />
              )}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={saving || !group || (canChooseDefault && !defaultUpstreamId)}
            onClick={() => group && onSubmit(group.model, defaultUpstreamId || null, alias)}
          >
            {saving ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
  const [showApiKey, setShowApiKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setErr(null);
    setShowApiKey(false);
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
          model: model.trim(),
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
          payload.model = trimmedModel;
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
      : "";

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
            <Label htmlFor="u-name" className={FORM_LABEL}>
              name{" "}
              <span className={FORM_LABEL_HINT}>
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
            <Label htmlFor="u-native-api" className={FORM_LABEL}>
              native_api{" "}
              <span className={FORM_LABEL_HINT}>
                (API 格式 · 决定 base_url 自动补全的 endpoint)
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
            <Label htmlFor="u-provider" className={FORM_LABEL}>
              provider{" "}
              <span className={FORM_LABEL_HINT}>
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
            <Label htmlFor="u-base" className={FORM_LABEL}>
              base_url{" "}
              <span className={FORM_LABEL_HINT}>
                (API 前缀 · 可含 /v1，勿填完整 endpoint)
              </span>
            </Label>
            <Input
              id="u-base"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com 或 https://api.example.com/v1"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="u-model" className={FORM_LABEL}>
              model{" "}
              <span className={FORM_LABEL_HINT}>
                (必填 · 客户端不传 r-upstream 时，按 body.model 自动匹配到此上游)
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
            <Label htmlFor="u-key" className={FORM_LABEL}>
              api_key{" "}
              <span className={FORM_LABEL_HINT}>
                {isEdit
                  ? "(已回显 · 清空保存 = 删除)"
                  : isCopy
                    ? "(从原 upstream 带过来 · 可修改)"
                    : "(可选 · 客户端不传时 server 用此 key 兜底)"}
              </span>
            </Label>
            <div className="relative">
              <Input
                id="u-key"
                type={showApiKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="pr-10"
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setShowApiKey((current) => !current)}
                aria-label={showApiKey ? "Hide API key" : "Show API key"}
              >
                {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
            {keyStatus && <p className={FORM_LABEL_HINT}>{keyStatus}</p>}
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
              <Label htmlFor="u-enabled" className={`${FORM_LABEL} cursor-pointer`}>
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

function maskApiKey(value: string | null | undefined): string {
  if (!value) return "-";
  const prefix = value.slice(0, 6);
  return `${prefix}${"*".repeat(Math.max(6, value.length - prefix.length))}`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
