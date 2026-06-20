/**
 * Chat 页的核心:历史消息 → 请求体构造 + 一轮流式请求。
 *
 * 对齐 `rosetta/cli/commands/chat_core.py` 的 `_build_body` + `run_turn`:
 * - v0.1 历史只存纯文本 `{role, content}[]`,三格式的多轮表达都能直接消化
 * - 浏览器走 `fetch` + SSE;`override api-key` → `x-api-key` 头;指定 upstream → `x-rosetta-upstream` 头
 * - 返回 `(assistantText, inputTokens, outputTokens, latencyMs)`;非 2xx 抛 `ChatError`
 */

import { apiBase, ServerApi } from "@/lib/api";
import type { RawChatRequest } from "@/lib/chat-raw";
import { ChatStream } from "@/lib/streams";
import type { SseFrame } from "@/lib/sse";

export interface ChatTurnMsg {
  role: "user" | "assistant";
  content: string;
}

export interface ChatTurnOpts {
  serverApi: ServerApi;
  /** 留空(null/"")则不发 body.model,server forwarder 用 upstream.model 兜底 */
  model: string | null;
  upstreamName: string | null;
  overrideApiKey: string | null;
  maxTokens: number;
  signal: AbortSignal;
  onToken: (t: string) => void;
  onRawRequest?: (request: RawChatRequest) => void;
  onRawFrame?: (frame: SseFrame) => void;
}

export interface ChatTurnResult {
  text: string;
  inputTokens: number;
  outputTokens: number;
  latencyMs: number;
  aborted: boolean;
}

export class ChatError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    const preview = body.slice(0, 200).replace(/\s+/g, " ");
    super(`HTTP ${status}: ${preview}`);
    this.name = "ChatError";
    this.status = status;
    this.body = body;
  }
}

/** server_api → 本地 server 数据面路径。 */
const URL_BY_SERVER_API: Record<ServerApi, string> = {
  [ServerApi.MESSAGES]: "/v1/messages",
  [ServerApi.CHAT_COMPLETIONS]: "/v1/chat/completions",
  [ServerApi.RESPONSES]: "/v1/responses",
};

export async function runTurn(
  messages: ChatTurnMsg[],
  opts: ChatTurnOpts,
): Promise<ChatTurnResult> {
  const body = buildBody(opts.serverApi, messages, opts.model, opts.maxTokens);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (opts.upstreamName) headers["x-rosetta-upstream"] = opts.upstreamName;
  if (opts.overrideApiKey) headers["x-api-key"] = opts.overrideApiKey;

  const base = await apiBase();
  const url = URL_BY_SERVER_API[opts.serverApi];
  opts.onRawRequest?.({ url, headers, body });
  const t0 = performance.now();
  let resp: Response;
  try {
    resp = await fetch(base + url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (e) {
    if (opts.signal.aborted) {
      return { text: "", inputTokens: 0, outputTokens: 0, latencyMs: 0, aborted: true };
    }
    throw e;
  }

  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ChatError(resp.status, text);
  }

  const stream = new ChatStream(opts.serverApi);
  const buf: string[] = [];
  let aborted = false;
  try {
    for await (const tok of stream.textDeltas(resp, opts.signal, opts.onRawFrame)) {
      buf.push(tok);
      opts.onToken(tok);
    }
  } catch (e) {
    if (opts.signal.aborted) {
      aborted = true;
    } else {
      throw e;
    }
  }

  return {
    text: buf.join(""),
    inputTokens: stream.inputTokens,
    outputTokens: stream.outputTokens,
    latencyMs: Math.round(performance.now() - t0),
    aborted,
  };
}

function buildBody(
  serverApi: ServerApi,
  messages: ChatTurnMsg[],
  model: string | null,
  maxTokens: number,
): Record<string, unknown> {
  // model 留空 → 不发字段,让 forwarder 兜底到 upstream.model
  const modelField: Record<string, unknown> = model ? { model } : {};
  if (serverApi === ServerApi.MESSAGES) {
    return { ...modelField, max_tokens: maxTokens, stream: true, messages };
  }
  if (serverApi === ServerApi.CHAT_COMPLETIONS) {
    // rosetta 翻译层 adapter 要求 max_tokens 必填;沿用 messages 的 maxTokens 一次给齐
    return {
      ...modelField,
      stream: true,
      stream_options: { include_usage: true },
      max_tokens: maxTokens,
      messages,
    };
  }
  // RESPONSES:字段名是 max_output_tokens,input item 需带 type="message"
  return {
    ...modelField,
    stream: true,
    max_output_tokens: maxTokens,
    input: messages.map((m) => ({
      type: "message",
      role: m.role,
      content: m.content,
    })),
  };
}
