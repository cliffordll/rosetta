export type ClientConfigTarget = "codex" | "claude" | "opencode";

export const CLIENT_CONFIG_TARGETS: ClientConfigTarget[] = ["codex", "claude", "opencode"];

export function clientConfigTargetLabel(target: ClientConfigTarget): string {
  switch (target) {
    case "codex":
      return "Codex";
    case "claude":
      return "Claude";
    case "opencode":
      return "OpenCode";
  }
}
