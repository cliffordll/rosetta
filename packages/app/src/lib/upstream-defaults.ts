import type { UpstreamDefaultsOut, UpstreamOut } from "./api";

export const DEFAULT_SCOPE_ORDER = [
  "global",
  "messages",
  "completions",
  "responses",
] as const;

export type UpstreamDefaultScope = (typeof DEFAULT_SCOPE_ORDER)[number];

export function defaultBindingRows(
  defaults: UpstreamDefaultsOut,
): Array<{ scope: UpstreamDefaultScope; upstreamName: string | null }> {
  return DEFAULT_SCOPE_ORDER.map((scope) => ({
    scope,
    upstreamName: defaults[scope],
  }));
}

export function formatUpstreamOptionLabel(upstream: UpstreamOut): string {
  const model = upstream.model ?? "auto";
  const disabled = upstream.enabled ? "" : " · off";
  return `${upstream.name} (${model} · ${upstream.native_api}${disabled})`;
}
