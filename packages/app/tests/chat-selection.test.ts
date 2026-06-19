import assert from "node:assert/strict";
import test from "node:test";

import {
  changeServerApiSelection,
  ensureUpstreamChoice,
  initialUpstreamChoice,
} from "../src/lib/chat-selection.ts";

test("changing server API preserves the selected upstream", () => {
  const next = changeServerApiSelection(
    {
      serverApi: "messages",
      upstreamChoice: "upstream-responses",
      model: "client-model-override",
    },
    "responses",
  );

  assert.deepEqual(next, {
    serverApi: "responses",
    upstreamChoice: "upstream-responses",
    model: "",
  });
});

test("initial upstream choice uses the first enabled upstream", () => {
  const choice = initialUpstreamChoice(
    [
      { id: "disabled", enabled: false, is_default: false },
      { id: "first-enabled", enabled: true, is_default: false },
      { id: "second-enabled", enabled: true, is_default: false },
    ],
    "__none__",
  );

  assert.equal(choice, "first-enabled");
});

test("initial upstream choice remains empty when none are enabled", () => {
  const choice = initialUpstreamChoice(
    [{ id: "disabled", enabled: false, is_default: false }],
    "__none__",
  );

  assert.equal(choice, "__none__");
});

test("initial upstream choice prefers the enabled global default", () => {
  const choice = initialUpstreamChoice(
    [
      { id: "first-enabled", enabled: true, is_default: false },
      { id: "global-default", enabled: true, is_default: true },
    ],
    "__none__",
  );

  assert.equal(choice, "global-default");
});

test("missing upstream choice is repaired when enabled upstreams arrive", () => {
  const choice = ensureUpstreamChoice(
    "__none__",
    [{ id: "first-enabled", enabled: true, is_default: false }],
    "__none__",
  );

  assert.equal(choice, "first-enabled");
});

test("an explicit upstream choice is preserved when upstreams refresh", () => {
  const choice = ensureUpstreamChoice(
    "selected-upstream",
    [{ id: "first-enabled", enabled: true, is_default: false }],
    "__none__",
  );

  assert.equal(choice, "selected-upstream");
});
