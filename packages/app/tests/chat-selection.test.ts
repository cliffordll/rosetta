import assert from "node:assert/strict";
import test from "node:test";

import {
  changeServerApiSelection,
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
      { id: "disabled", enabled: false },
      { id: "first-enabled", enabled: true },
      { id: "second-enabled", enabled: true },
    ],
    "__none__",
  );

  assert.equal(choice, "first-enabled");
});

test("initial upstream choice remains empty when none are enabled", () => {
  const choice = initialUpstreamChoice([{ id: "disabled", enabled: false }], "__none__");

  assert.equal(choice, "__none__");
});
