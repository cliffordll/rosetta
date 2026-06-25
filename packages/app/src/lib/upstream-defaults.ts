import type { ModelDefaultsOut, UpstreamOut } from "./api";

export type DefaultBindingScope = "global" | "messages" | "completions" | "responses";

export interface DefaultBindingRow {
  scope: DefaultBindingScope;
  upstreamName: string | null;
}

export function defaultBindingRows(
  defaults: Partial<Record<DefaultBindingScope, string | null>>,
): DefaultBindingRow[] {
  const scopes: DefaultBindingScope[] = ["global", "messages", "completions", "responses"];
  return scopes.map((scope) => ({
    scope,
    upstreamName: defaults[scope] ?? null,
  }));
}

export interface ModelUpstreamGroup {
  model: string;
  upstreams: UpstreamOut[];
  defaultUpstreamName: string | null;
}

export function modelUpstreamGroups(
  upstreams: UpstreamOut[],
  defaults: ModelDefaultsOut,
): ModelUpstreamGroup[] {
  const byModel = new Map<string, UpstreamOut[]>();
  for (const upstream of upstreams) {
    const model = upstream.model?.trim();
    if (!model) continue;
    byModel.set(model, [...(byModel.get(model) ?? []), upstream]);
  }

  return Array.from(byModel.entries())
    .map(([model, groupedUpstreams]) => ({
      model,
      upstreams: groupedUpstreams.sort((a, b) => a.name.localeCompare(b.name)),
      defaultUpstreamName: defaults[model] ?? null,
    }))
    .sort((a, b) => {
      const duplicateDelta = Number(b.upstreams.length > 1) - Number(a.upstreams.length > 1);
      return duplicateDelta || a.model.localeCompare(b.model);
    });
}

export function formatUpstreamOptionLabel(upstream: UpstreamOut): string {
  const model = upstream.model ?? "auto";
  const disabled = upstream.enabled ? "" : " · off";
  return `${upstream.name} (${model} · ${upstream.native_api}${disabled})`;
}
