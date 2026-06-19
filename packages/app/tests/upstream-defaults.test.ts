import assert from "node:assert/strict";
import test from "node:test";

import {
  defaultBindingRows,
  formatUpstreamOptionLabel,
} from "../src/lib/upstream-defaults.ts";

test("defaultBindingRows returns the four scopes in fixed order", () => {
  const rows = defaultBindingRows({
    global: "shared",
    messages: null,
    completions: "openai-main",
    responses: "mock",
  });

  assert.deepEqual(rows, [
    { scope: "global", upstreamName: "shared" },
    { scope: "messages", upstreamName: null },
    { scope: "completions", upstreamName: "openai-main" },
    { scope: "responses", upstreamName: "mock" },
  ]);
});

test("formatUpstreamOptionLabel includes model, native API, and disabled state", () => {
  assert.equal(
    formatUpstreamOptionLabel({
      id: "u1",
      name: "anthropic-main",
      native_api: "messages",
      provider: "anthropic",
      base_url: "https://api.example.com",
      api_key: null,
      model: "claude-sonnet-4-5",
      enabled: false,
      is_default: false,
      created_at: "2026-06-19T00:00:00Z",
    }),
    "anthropic-main (claude-sonnet-4-5 · messages · off)",
  );
});

test("formatUpstreamOptionLabel uses auto when model is missing", () => {
  assert.equal(
    formatUpstreamOptionLabel({
      id: "u2",
      name: "openai-main",
      native_api: "responses",
      provider: "openai",
      base_url: "https://api.example.com",
      api_key: null,
      model: null,
      enabled: true,
      is_default: false,
      created_at: "2026-06-19T00:00:00Z",
    }),
    "openai-main (auto · responses)",
  );
});
