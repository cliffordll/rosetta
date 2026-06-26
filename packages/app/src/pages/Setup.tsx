import { useCallback, useEffect, useMemo, useRef, useState, type Ref, type UIEvent } from "react";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CLIENT_CONFIG_TARGETS,
  clientConfigApiKeyEnv,
  clientConfigCliCommand,
  clientConfigTargetLabel,
  clientConfigTargetLanguage,
  type ClientConfigTarget,
} from "@/lib/client-config-snippets";
import { api, type SetupConfigOut, type UpstreamOut } from "@/lib/api";

function formatUpstreamLabel(u: UpstreamOut): string {
  return `${u.name}(${u.model ?? "auto"}+${u.native_api})`;
}

export default function Setup() {
  const [items, setItems] = useState<UpstreamOut[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [configTarget, setConfigTarget] = useState<ClientConfigTarget>("codex");
  const [localConfig, setLocalConfig] = useState<SetupConfigOut | null>(null);
  const [preview, setPreview] = useState<SetupConfigOut | null>(null);
  const [loadingLocal, setLoadingLocal] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [activeCommand, setActiveCommand] = useState<SetupCommandKind>("powershell");
  const [info, setInfo] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const currentPreRef = useRef<HTMLPreElement | null>(null);
  const generatedPreRef = useRef<HTMLPreElement | null>(null);
  const syncingScrollRef = useRef(false);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const list = await api.listUpstreams();
      const ordered = [...list].reverse();
      setItems(ordered);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
      setItems([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadLocalConfig = useCallback(
    async (target: ClientConfigTarget, options?: { quiet?: boolean }) => {
      if (!options?.quiet) setLoadingLocal(true);
      try {
        const result = await api.setupCurrent(target);
        setLocalConfig(result);
      } catch (e) {
        // 左侧面板只是辅助信息，读本地文件失败不阻断整个页面
        setLocalConfig(null);
      } finally {
        if (!options?.quiet) setLoadingLocal(false);
      }
    },
    [],
  );

  const loadPreviewConfig = useCallback(
    async (target: ClientConfigTarget, upstreamId: string | null) => {
      if (!upstreamId) {
        setPreview(null);
        return;
      }
      setInfo(null);
      setLoadErr(null);
      try {
        const result = await api.setupPreview(target, upstreamId);
        setPreview(result);
      } catch (e) {
        setPreview(null);
        setLoadErr(e instanceof Error ? e.message : String(e));
      }
    },
    [],
  );

  // 独立加载本地配置文件，不依赖 upstream
  useEffect(() => {
    void loadLocalConfig(configTarget);
  }, [configTarget, loadLocalConfig]);

  useEffect(() => {
    void loadPreviewConfig(configTarget, selectedId);
  }, [configTarget, loadPreviewConfig, selectedId]);

  function syncConfigScroll(
    source: HTMLPreElement,
    target: HTMLPreElement | null,
  ) {
    if (!target || syncingScrollRef.current) return;
    syncingScrollRef.current = true;
    const topRatio = source.scrollTop / Math.max(1, source.scrollHeight - source.clientHeight);
    const leftRatio = source.scrollLeft / Math.max(1, source.scrollWidth - source.clientWidth);
    target.scrollTop = topRatio * Math.max(0, target.scrollHeight - target.clientHeight);
    target.scrollLeft = leftRatio * Math.max(0, target.scrollWidth - target.clientWidth);
    window.requestAnimationFrame(() => {
      syncingScrollRef.current = false;
    });
  }

  async function handleRefreshCurrentTarget() {
    setRefreshing(true);
    setSelectedId(null);
    setPreview(null);
    try {
      await loadLocalConfig(configTarget, { quiet: true });
    } finally {
      setRefreshing(false);
    }
  }

  async function handleClear() {
    setInfo(null);
    setLoadErr(null);
    setClearing(true);
    try {
      const result = await api.setupClear(configTarget);
      setPreview(null);
      setLocalConfig({ ...result, original: result.generated });
      setInfo(result.backup_path ? `Cleared. Backup: ${result.backup_path}` : "Cleared");
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setClearing(false);
    }
  }

  async function handleCopyCommand(command: string) {
    setInfo(null);
    setLoadErr(null);
    try {
      await navigator.clipboard.writeText(command);
      setInfo("Copied command");
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    }
  }
  async function handleApply() {
    if (!selectedId) return;
    setInfo(null);
    setLoadErr(null);
    setApplying(true);
    try {
      const result = await api.setupApply(configTarget, selectedId);
      setPreview(result);
      setLocalConfig({ ...result, exists: true, original: result.generated });
      setInfo(result.backup_path ? `Applied. Backup: ${result.backup_path}` : "Applied");
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  }

  const alignedConfig = useMemo(
    () => (preview ? alignConfigLines(localConfig?.original ?? "", preview.generated) : null),
    [localConfig?.original, preview],
  );
  const selectedUpstream = useMemo(
    () => items?.find((item) => item.id === selectedId) ?? null,
    [items, selectedId],
  );
  const apiKeyEnv = clientConfigApiKeyEnv(configTarget);
  const cliCommand = clientConfigCliCommand(configTarget);
  const apiKeyValue = selectedUpstream?.api_key || "rosetta-local";
  const maskedApiKeyValue = maskApiKeyValue(apiKeyValue);
  const powershellApiKeyCommand = `$env:${apiKeyEnv}="${apiKeyValue}"`;
  const bashApiKeyCommand = `export ${apiKeyEnv}=${shellQuote(apiKeyValue)}`;
  const setupCommands: SetupCommandOption[] = [
    {
      kind: "powershell",
      label: "PowerShell",
      display: `$env:${apiKeyEnv}="${maskedApiKeyValue}"`,
      command: powershellApiKeyCommand,
    },
    {
      kind: "export",
      label: "export",
      display: `export ${apiKeyEnv}=${maskedApiKeyValue}`,
      command: bashApiKeyCommand,
    },
    { kind: "cli", label: "CLI", display: cliCommand, command: cliCommand },
  ];
  const selectedSetupCommand = setupCommands.find((item) => item.kind === activeCommand) ?? setupCommands[0];

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex shrink-0 items-center justify-between">
        <h1 className="text-2xl font-semibold">Setup</h1>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            {CLIENT_CONFIG_TARGETS.map((target) => (
              <Button
                key={target}
                variant="outline"
                size="sm"
                className={
                  configTarget === target
                    ? "border-border bg-muted/60 text-foreground hover:bg-muted/70 hover:text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }
                onClick={() => setConfigTarget(target)}
              >
                {clientConfigTargetLabel(target)}
              </Button>
            ))}
          </div>
          <Button
            variant="outline"
            disabled={refreshing || loadingLocal}
            onClick={() => void handleRefreshCurrentTarget()}
            title={`Refresh ${clientConfigTargetLabel(configTarget)} config`}
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </Button>
        </div>


        <div className="grid min-h-0 flex-1 gap-4 grid-cols-2">
          {/* 左侧：路径信息 + Current config（独立于 upstream） */}
          <div className="flex flex-col gap-3 min-h-0">
            <div className="rounded-md border bg-muted/30 flex items-center h-8 px-3 text-xs leading-relaxed text-muted-foreground whitespace-normal break-words">
              {localConfig
                ? `${localConfig.path} · ${localConfig.exists ? "existing file found" : "new file"}`
                : loadingLocal
                  ? "Loading..."
                  : "Config path will appear here"}
            </div>
            <div className="flex-1 flex flex-col min-h-0">
              <ConfigPanel
                title="Current config"
                language={localConfig?.language ?? clientConfigTargetLanguage(configTarget)}
                content={localConfig?.original || "(empty)"}
                lines={alignedConfig?.base}
                scrollRef={currentPreRef}
                onScroll={(event) => syncConfigScroll(event.currentTarget, generatedPreRef.current)}
              />
            </div>
          </div>

          {/* 右侧：upstream 选择器 + Generated config */}
          <div className="flex flex-col gap-3 min-h-0">
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground whitespace-nowrap shrink-0">upstream</span>
              <div className="flex-1">
                <Select
                  value={selectedId ?? ""}
                  onValueChange={(value) => setSelectedId(value || null)}
                >
                  <SelectTrigger size="sm" className="h-8 text-xs w-full">
                    <SelectValue placeholder="Select upstream" />
                  </SelectTrigger>
                  <SelectContent>
                    {items?.map((u) => (
                      <SelectItem key={u.id} value={u.id}>
                        {formatUpstreamLabel(u)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex-1 flex flex-col min-h-0">
              <ConfigPanel
                title="Generated config"
                language={preview?.language ?? clientConfigTargetLanguage(configTarget)}
                content={preview?.generated ?? "(select an upstream)"}
                lines={alignedConfig?.generated}
                scrollRef={generatedPreRef}
                onScroll={(event) => syncConfigScroll(event.currentTarget, currentPreRef.current)}
                highlightChanges={Boolean(preview)}
              />
            </div>
          </div>
        </div>

        <div className="flex min-w-0 shrink-0 items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-md border bg-muted/30 px-2 py-1 text-[11px] leading-tight text-muted-foreground whitespace-nowrap">
            <div className="flex shrink-0 items-center rounded-md border bg-background p-0.5">
              {setupCommands.map((item) => (
                <button
                  key={item.kind}
                  type="button"
                  className={`h-5 rounded px-1.5 text-[11px] ${activeCommand === item.kind ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/70 hover:text-foreground"}`}
                  onClick={() => setActiveCommand(item.kind)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-foreground">
              {selectedSetupCommand.display}
            </code>
            <Button
              type="button"
              variant="outline"
              size="xs"
              className="h-5 px-1.5 text-[11px]"
              onClick={() => void handleCopyCommand(selectedSetupCommand.command)}
            >
              Copy
            </Button>
          </div>
          <div className="flex shrink-0 justify-end gap-2">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="outline"
                disabled={!localConfig?.exists || clearing}
              >
                {clearing ? "Clearing..." : "Clear config"}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Clear Rosetta config?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will remove Rosetta entries from the local {clientConfigTargetLabel(configTarget)} config file.
                  A backup is created when the current file exists.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={clearing}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  disabled={clearing}
                  onClick={() => void handleClear()}
                >
                  Clear config
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button disabled={!preview || applying}>
                {applying ? "Applying..." : "Apply config"}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Apply config?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will write the generated Rosetta entries to the local {clientConfigTargetLabel(configTarget)}
                  config file. Existing config is backed up before writing.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={applying}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  disabled={!preview || applying}
                  onClick={() => void handleApply()}
                >
                  Apply config
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          </div>
        </div>

        {(info || loadErr) && (
          <div className="space-y-3">
            {info && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/8 p-3 text-sm text-emerald-700 whitespace-normal break-words">
                {info}
              </div>
            )}
            {loadErr && (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive whitespace-normal break-words">
                {loadErr}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function ConfigPanel({
  title,
  language,
  content,
  scrollRef,
  onScroll,
  lines,
  highlightChanges = false,
}: {
  title: string;
  language: string;
  content: string;
  lines?: DiffLine[];
  scrollRef?: Ref<HTMLPreElement>;
  onScroll?: (event: UIEvent<HTMLPreElement>) => void;
  highlightChanges?: boolean;
}) {

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground shrink-0">
        <span className="truncate font-medium">{title}</span>
        <div className="flex items-center gap-2">
          {highlightChanges && (
            <span className="flex items-center gap-2 text-[11px]">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm bg-emerald-500" /> added
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm bg-amber-500" /> changed
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm bg-destructive" /> removed
              </span>
            </span>
          )}
          <Badge variant="outline">{language}</Badge>
        </div>
      </div>
      <pre
        ref={scrollRef}
        onScroll={onScroll}
        className="max-w-full flex-1 overflow-auto rounded-md border bg-muted/40 text-xs leading-relaxed"
      >
        <code>
          {lines
            ? lines.map((line, index) => (
                <span
                  key={index}
                  className={`block min-h-[1.5em] border-l-2 px-3 ${diffLineClass(line.kind)}`}
                >
                  {line.text || "\u00a0"}
                </span>
              ))
            : content.split("\n").map((line, index) => (
                <span key={index} className="block min-h-[1.5em] px-3">
                  {line || "\u00a0"}
                </span>
              ))}
        </code>
      </pre>
    </div>
  );
}

type SetupCommandKind = "powershell" | "export" | "cli";

interface SetupCommandOption {
  kind: SetupCommandKind;
  label: string;
  display: string;
  command: string;
}
function maskApiKeyValue(value: string): string {
  if (!value || value === "rosetta-local") return value || "-";
  const prefix = value.slice(0, 6);
  return `${prefix}${"*".repeat(Math.max(6, value.length - prefix.length))}`;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}
type DiffLineKind = "same" | "added" | "changed" | "removed" | "empty";

interface DiffLine {
  text: string;
  kind: DiffLineKind;
}

interface AlignedConfigLines {
  base: DiffLine[];
  generated: DiffLine[];
}

function alignConfigLines(base: string, generated: string): AlignedConfigLines {
  const baseLines = splitDiffLines(base);
  const generatedLines = splitDiffLines(generated);
  const common = longestCommonLineSubsequence(baseLines, generatedLines);
  const aligned: AlignedConfigLines = { base: [], generated: [] };
  let baseIndex = 0;
  let generatedIndex = 0;

  for (const [nextBaseIndex, nextGeneratedIndex] of [...common, [baseLines.length, generatedLines.length] as [number, number]]) {
    while (baseIndex < nextBaseIndex || generatedIndex < nextGeneratedIndex) {
      if (baseIndex < nextBaseIndex && generatedIndex < nextGeneratedIndex) {
        aligned.base.push({ text: baseLines[baseIndex], kind: "changed" });
        aligned.generated.push({ text: generatedLines[generatedIndex], kind: "changed" });
        baseIndex += 1;
        generatedIndex += 1;
      } else if (baseIndex < nextBaseIndex) {
        aligned.base.push({ text: baseLines[baseIndex], kind: "removed" });
        aligned.generated.push({ text: "", kind: "empty" });
        baseIndex += 1;
      } else {
        aligned.base.push({ text: "", kind: "empty" });
        aligned.generated.push({ text: generatedLines[generatedIndex], kind: "added" });
        generatedIndex += 1;
      }
    }

    if (baseIndex < baseLines.length && generatedIndex < generatedLines.length) {
      aligned.base.push({ text: baseLines[baseIndex], kind: "same" });
      aligned.generated.push({ text: generatedLines[generatedIndex], kind: "same" });
      baseIndex += 1;
      generatedIndex += 1;
    }
  }

  if (!aligned.base.length && !aligned.generated.length) {
    aligned.base.push({ text: "", kind: "same" });
    aligned.generated.push({ text: "", kind: "same" });
  }
  return aligned;
}


function splitDiffLines(value: string): string[] {
  if (!value) return [];
  const normalized = value.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

function longestCommonLineSubsequence(a: string[], b: string[]): Array<[number, number]> {
  const dp: number[][] = Array.from({ length: a.length + 1 }, () =>
    Array.from({ length: b.length + 1 }, () => 0),
  );
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const pairs: Array<[number, number]> = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      pairs.push([i, j]);
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      i += 1;
    } else {
      j += 1;
    }
  }
  return pairs;
}

function diffLineClass(kind: DiffLineKind): string {
  switch (kind) {
    case "added":
      return "border-l-emerald-500 bg-emerald-500/15";
    case "changed":
      return "border-l-amber-500 bg-amber-500/25";
    case "removed":
      return "border-l-destructive bg-destructive/10 text-muted-foreground";
    case "empty":
      return "border-l-transparent bg-muted/20 text-transparent";
    case "same":
      return "border-l-transparent";
  }
}