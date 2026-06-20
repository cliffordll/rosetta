import assert from "node:assert/strict";
import test from "node:test";

import {
  formatParsedRawResponse,
  formatParsedRawRequest,
  formatRawRequest,
  formatRawResponse,
  formatRawTurn,
  previewLongText,
  previewRawResponseFrames,
} from "../src/lib/chat-raw.ts";

test("raw chat turn output includes sent request and received response frames", () => {
  const output = formatRawTurn({
    request: {
      url: "/v1/messages",
      headers: {
        "content-type": "application/json",
        "x-rosetta-upstream": "mock",
      },
      body: {
        stream: true,
        messages: [{ role: "user", content: "hello" }],
      },
    },
    responseFrames: [
      {
        event: "message_start",
        data: { type: "message_start", message: { usage: { input_tokens: 1 } } },
      },
      {
        event: "content_block_delta",
        data: { type: "content_block_delta", delta: { type: "text_delta", text: "hi" } },
      },
    ],
  });

  assert.match(output, /request/);
  assert.match(output, /response/);
  assert.match(output, /"x-rosetta-upstream": "mock"/);
  assert.match(output, /"event": "content_block_delta"/);
  assert.match(output, /"text": "hi"/);
});

test("raw chat turn output includes override api key header", () => {
  const output = formatRawTurn({
    request: {
      url: "/v1/messages",
      headers: {
        "content-type": "application/json",
        "x-api-key": "sk-secret",
      },
      body: {
        stream: true,
        messages: [{ role: "user", content: "hello" }],
      },
    },
    responseFrames: [],
    error: null,
  });

  assert.match(output, /"x-api-key": "sk-secret"/);
});

test("raw request and response can be formatted separately for chat bubbles", () => {
  const request = {
    url: "/v1/messages",
    headers: {
      "content-type": "application/json",
      "x-api-key": "sk-secret",
    },
    body: {
      stream: true,
      messages: [{ role: "user", content: "hello" }],
    },
  };
  const response = {
    responseFrames: [
      {
        event: "content_block_delta",
        data: { type: "content_block_delta", delta: { type: "text_delta", text: "hi" } },
      },
    ],
    error: null,
  };

  const requestOutput = formatRawRequest(request);
  const parsedRequestOutput = formatParsedRawRequest(request);
  const responseOutput = formatRawResponse(response);

  assert.match(requestOutput, /POST \/v1\/messages/);
  assert.match(requestOutput, /x-api-key: sk-secret/);
  assert.doesNotMatch(requestOutput, /"response"/);

  assert.match(parsedRequestOutput, /"request"/);
  assert.match(parsedRequestOutput, /"url": "\/v1\/messages"/);
  assert.match(parsedRequestOutput, /"x-api-key": "sk-secret"/);

  assert.match(responseOutput, /event: content_block_delta/);
  assert.match(responseOutput, /"text":"hi"/);
  assert.doesNotMatch(responseOutput, /"request"/);
});

test("raw response defaults to timestamped SSE text and can be parsed as JSON", () => {
  const response = {
    responseFrames: [
      {
        receivedAt: "2026-06-20T12:00:00.000Z",
        raw: 'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"text":"hi"}}',
        event: "content_block_delta",
        data: { type: "content_block_delta", delta: { text: "hi" } },
      },
    ],
    error: null,
  };

  const rawOutput = formatRawResponse(response);
  const parsedOutput = formatParsedRawResponse(response);

  assert.match(rawOutput, /\[2026-06-20T12:00:00.000Z\] event: content_block_delta/);
  assert.match(rawOutput, /data: \{"type":"content_block_delta"/);
  assert.doesNotMatch(rawOutput, /"response"/);

  assert.match(parsedOutput, /"response"/);
  assert.match(parsedOutput, /"receivedAt": "2026-06-20T12:00:00.000Z"/);
  assert.match(parsedOutput, /"event": "content_block_delta"/);
  assert.match(parsedOutput, /"text": "hi"/);
});

test("long raw text previews head and tail with hidden middle metadata", () => {
  const preview = previewLongText("abcdefghij", 4);

  assert.equal(preview.text, "ab\n\n... hidden 6 chars ...\n\nij");
  assert.equal(preview.isTruncated, true);
  assert.equal(preview.omittedChars, 6);
});

test("raw response preview keeps first and last frames and reveals middle frames in batches", () => {
  const response = {
    responseFrames: Array.from({ length: 25 }, (_, i) => ({
      receivedAt: `2026-06-20T12:00:${String(i).padStart(2, "0")}.000Z`,
      raw: `event: frame_${i}\ndata: {"index":${i}}`,
      event: `frame_${i}`,
      data: { index: i },
    })),
    error: null,
  };

  const collapsed = previewRawResponseFrames(response, { edgeFrames: 10, revealedMiddleFrames: 0 });
  assert.match(collapsed.text, /event: frame_0/);
  assert.match(collapsed.text, /event: frame_9/);
  assert.doesNotMatch(collapsed.text, /event: frame_10/);
  assert.match(collapsed.text, /hidden 5 frames/);
  assert.match(collapsed.text, /event: frame_15/);
  assert.match(collapsed.text, /event: frame_24/);
  assert.equal(collapsed.hiddenFrames, 5);

  const expanded = previewRawResponseFrames(response, { edgeFrames: 10, revealedMiddleFrames: 10 });
  assert.match(expanded.text, /event: frame_10/);
  assert.match(expanded.text, /event: frame_14/);
  assert.equal(expanded.hiddenFrames, 0);
});
