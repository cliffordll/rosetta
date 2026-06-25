import { useCallback, useEffect, useMemo, useState } from "react";

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
  clientConfigTargetLabel,
  type ClientConfigTarget,
} from "@/lib/client-config-snippets";
import { api, type SetupConfigOut, type UpstreamOut } from "@/lib/api";
import { formatUpstreamOptionLabel } from "@/lib/upstream-defaults";

export default function Setup() {
  const [items, setItems] = useState<UpstreamOut[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [configTarget, setConfigTarget] = useState<ClientConfigTarget>("codex");
  const [preview, setPreview] = useState<SetupConfigOut | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [applying, setApplying] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

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

  const selectedUpstream = useMemo(
    () => items?.find((u) => u.id === selectedId) ?? null,
    [items, selectedId],
  );

  useEffect(() => {
    if (!selectedId) {
      setPreview(null);
      return;
    }

    let cancelled = false;
    async function loadPreview() {
      setInfo(null);
      setLoadErr(null);
      setLoadingPreview(true);
      try {
        const result = await api.setupPreview(configTarget, selectedId as string);
        if (!cancelled) setPreview(result);
      } catch (e) {
        if (!cancelled) {
          setPreview(null);
          setLoadErr(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setLoadingPreview(false);
      }
    }

    void loadPreview();
    return () => {
      cancelled = true;
    };
  }, [configTarget, selectedId]);

  async function handleCopy(content: string) {
    setInfo(null);
    setLoadErr(null);
    try {
      await navigator.clipboard.writeText(content);
      setInfo("Copied");
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
      setInfo(result.backup_path ? `Applied. Backup: ${result.backup_path}` : "Applied");
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex shrink-0 items-center justify-between">
        <h1 className="text-2xl font-semibold">Setup</h1>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-6">
        <div className="flex flex-wrap gap-2">
          {CLIENT_CONFIG_TARGETS.map((target) => (
            <Button
              key={target}
              variant={configTarget === target ? "default" : "outline"}
              size="sm"
              onClick={() => setConfigTarget(target)}
            >
              {clientConfigTargetLabel(target)}
            </Button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground whitespace-nowrap">upstream</span>
          <div className="max-w-xs flex-1">
            <Select
              value={selectedId ?? undefined}
              onValueChange={(value) => setSelectedId(value)}
            >
              <SelectTrigger size="sm" className="h-8 text-xs w-full">
                <SelectValue placeholder="Select upstream" />
              </SelectTrigger>
              <SelectContent>
                {items?.map((u) => (
                  <SelectItem key={u.id} value={u.id}>
                    {formatUpstreamOptionLabel(u)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {selectedUpstream && preview ? (
          <div className="flex min-h-0 flex-1 flex-col gap-4">
            <div className="rounded-md border bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground whitespace-normal break-words">
              {preview.path} · {preview.exists ? "existing file found" : "new file"} · {selectedUpstream.name}
            </div>

            <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-2">
              <ConfigPanel
                title="Current config"
                language={preview.language}
                content={preview.original || "(empty)"}
              />
              <ConfigPanel
                title="Generated config"
                language={preview.language}
                content={preview.generated}
              />
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => void handleCopy(preview.generated)}>
                Copy config
              </Button>
              <Button onClick={() => void handleApply()} disabled={applying}>
                {applying ? "Applying..." : "Apply config"}
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {items === null || loadingPreview ? "Loading..." : "请先选择一个 upstream"}
          </p>
        )}

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
}: {
  title: string;
  language: string;
  content: string;
}) {
  return (
    <div className="flex min-h-0 min-w-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span className="truncate font-medium">{title}</span>
        <Badge variant="outline">{language}</Badge>
      </div>
      <pre className="min-h-[280px] max-h-[55vh] max-w-full flex-1 overflow-auto rounded-md border bg-muted/40 p-3 text-xs leading-relaxed">
        <code>{content}</code>
      </pre>
    </div>
  );
}
