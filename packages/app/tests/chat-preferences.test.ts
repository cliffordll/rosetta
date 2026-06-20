import assert from "node:assert/strict";
import test from "node:test";

import {
  loadChatPreferences,
  saveChatPreferences,
  type ChatPreferences,
} from "../src/lib/chat-preferences.ts";

class MemoryStorage implements Pick<Storage, "getItem" | "setItem"> {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

test("chat preferences round-trip selected chat configuration", () => {
  const storage = new MemoryStorage();
  const preferences: ChatPreferences = {
    serverApi: "responses",
    upstreamChoice: "upstream-1",
    model: "client-model",
    viewMode: "raw",
    rawEdgeFrames: 12,
    rawExpandStep: 6,
  };

  saveChatPreferences(storage, preferences);

  assert.deepEqual(loadChatPreferences(storage), preferences);
  assert.doesNotMatch(storage.getItem("rosetta.chat.preferences.v1") ?? "", /overrideKey/);
  assert.doesNotMatch(storage.getItem("rosetta.chat.preferences.v1") ?? "", /sk-secret/);
});

test("chat preferences ignore malformed and invalid stored values", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    "rosetta.chat.preferences.v1",
    JSON.stringify({
      serverApi: "bogus",
      upstreamChoice: 123,
      model: null,
      viewMode: "table",
      rawEdgeFrames: -1,
      rawExpandStep: "10",
      overrideKey: "sk-secret",
    }),
  );

  assert.deepEqual(loadChatPreferences(storage), {});
});
