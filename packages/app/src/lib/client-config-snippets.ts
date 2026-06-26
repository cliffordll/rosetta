export type ClientConfigTarget = "codex" | "claude" | "opencode";

export const CLIENT_CONFIG_TARGETS: ClientConfigTarget[] = ["codex", "claude", "opencode"];

export type ClientConfigLanguage = "toml" | "json";

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

export function clientConfigTargetLanguage(target: ClientConfigTarget): ClientConfigLanguage {
  switch (target) {
    case "codex":
      return "toml";
    case "claude":
    case "opencode":
      return "json";
  }
}
export function clientConfigApiKeyEnv(target: ClientConfigTarget): string {
  switch (target) {
    case "codex":
    case "opencode":
      return "OPENAI_API_KEY";
    case "claude":
      return "ANTHROPIC_API_KEY";
  }
}
export function clientConfigCliCommand(target: ClientConfigTarget): string {
  switch (target) {
    case "codex":
      return "codex --oss --local-provider rosetta";
    case "claude":
      return "claude";
    case "opencode":
      return "opencode";
  }
}
