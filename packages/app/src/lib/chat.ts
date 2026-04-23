/**
 * Chat 页的核心:历史消息 → 请求体构造 + 一轮流式请求。
 *
 * 对齐 `rosetta/cli/commands/chat_core.py` 的 `_build_body` + `run_turn`:
 * - v0.1 历史只存纯文本 `{role, content}[]`,三格式的多轮表达都能直接消化
 * - 浏览器走 `fetch` + SSE;`override api-key` → `x-api-key` 头;指定 upstream → `x-rosetta-upstream` 头
 * - 返回 `(assistantText, inputTokens, outputTokens, latencyMs)`;非 2xx 抛 `ChatError`
 */

import { Protocol } from "@/lib/api";
import { ChatStream } from "@/lib/streams";

export interface ChatTurnMsg {
  role: "user" | "assistant";
  content: string;
}

export interface ChatTurnOpts {
  fmt: Protocol;
  model: string;
  upstreamName: string | null;
  overrideApiKey: string | null;
  maxTokens: number;
  signal: AbortSignal;
  onToken: (t: string) => void;
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

/** protocol → 数据面路径(对齐 `rosetta.shared.protocols.UPSTREAM_PATH`,但这里是本地 server 路由)。 */
const URL_BY_PROTOCOL: Record<Protocol, string> = {
  [Protocol.MESSAGES]: "/v1/messages",
  [Protocol.CHAT_COMPLETIONS]: "/v1/chat/completions",
  [Protocol.RESPONSES]: "/v1/responses",
};

export async function runTurn(
  messages: ChatTurnMsg[],
  opts: ChatTurnOpts,
): Promise<ChatTurnResult> {
  const body = buildBody(opts.fmt, messages, opts.model, opts.maxTokens);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (opts.upstreamName) headers["x-rosetta-upstream"] = opts.upstreamName;
  if (opts.overrideApiKey) headers["x-api-key"] = opts.overrideApiKey;

  const t0 = performance.now();
  let resp: Response;
  try {
    resp = await fetch(URL_BY_PROTOCOL[opts.fmt], {
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

  const stream = new ChatStream(opts.fmt);
  const buf: string[] = [];
  let aborted = false;
  try {
    for await (const tok of stream.textDeltas(resp, opts.signal)) {
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
  fmt: Protocol,
  messages: ChatTurnMsg[],
  model: string,
  maxTokens: number,
): Record<string, unknown> {
  if (fmt === Protocol.MESSAGES) {
    return { model, max_tokens: maxTokens, stream: true, messages };
  }
  if (fmt === Protocol.CHAT_COMPLETIONS) {
    // rosetta 翻译层 adapter 要求 max_tokens 必填;沿用 messages 的 maxTokens 一次给齐
    return {
      model,
      stream: true,
      stream_options: { include_usage: true },
      max_tokens: maxTokens,
      messages,
    };
  }
  // RESPONSES:字段名是 max_output_tokens,input item 需带 type="message"
  return {
    model,
    stream: true,
    max_output_tokens: maxTokens,
    input: messages.map((m) => ({
      type: "message",
      role: m.role,
      content: m.content,
    })),
  };
}
