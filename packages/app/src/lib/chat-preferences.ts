import { ServerApi, type ServerApi as ServerApiValue } from "./api.ts";

export type ChatViewMode = "nice" | "raw";

export interface ChatPreferences {
  serverApi?: ServerApiValue;
  upstreamChoice?: string;
  model?: string;
  viewMode?: ChatViewMode;
  rawEdgeFrames?: number;
  rawExpandStep?: number;
}

export const CHAT_PREFERENCES_KEY = "rosetta.chat.preferences.v1";

type ChatPreferencesStorage = Pick<Storage, "getItem" | "setItem">;

export function loadChatPreferences(storage: ChatPreferencesStorage): ChatPreferences {
  const raw = storage.getItem(CHAT_PREFERENCES_KEY);
  if (!raw) return {};

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!isObj(parsed)) return {};

  const preferences: ChatPreferences = {};
  const serverApi = parsed.serverApi;
  if (isServerApi(serverApi)) preferences.serverApi = serverApi;

  const upstreamChoice = parsed.upstreamChoice;
  if (typeof upstreamChoice === "string") preferences.upstreamChoice = upstreamChoice;

  const model = parsed.model;
  if (typeof model === "string") preferences.model = model;

  const viewMode = parsed.viewMode;
  if (viewMode === "nice" || viewMode === "raw") preferences.viewMode = viewMode;

  const rawEdgeFrames = parsed.rawEdgeFrames;
  if (isPositiveInteger(rawEdgeFrames)) preferences.rawEdgeFrames = rawEdgeFrames;

  const rawExpandStep = parsed.rawExpandStep;
  if (isPositiveInteger(rawExpandStep)) preferences.rawExpandStep = rawExpandStep;

  return preferences;
}

export function saveChatPreferences(
  storage: ChatPreferencesStorage,
  preferences: Required<ChatPreferences>,
): void {
  storage.setItem(
    CHAT_PREFERENCES_KEY,
    JSON.stringify({
      serverApi: preferences.serverApi,
      upstreamChoice: preferences.upstreamChoice,
      model: preferences.model,
      viewMode: preferences.viewMode,
      rawEdgeFrames: preferences.rawEdgeFrames,
      rawExpandStep: preferences.rawExpandStep,
    }),
  );
}

function isServerApi(value: unknown): value is ServerApiValue {
  return (
    value === ServerApi.MESSAGES ||
    value === ServerApi.CHAT_COMPLETIONS ||
    value === ServerApi.RESPONSES
  );
}

function isObj(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && typeof value === "number" && value > 0;
}
