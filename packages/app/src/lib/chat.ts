/**
 * Chat 页的核心:历史消息 → 请求体构造 + 一轮流式请求。
 *
 * 对齐 `rosetta/cli/commands/chat_core.py` 的 `_build_body` + `run_turn`:
 * - v0.1 历史只存纯文本 `{role, content}[]`,三格式的多轮表达都能直接消化
 * - 浏览器走 `fetch` + SSE;`override api-key` 按入口协议写 `x-api-key`(Claude) 或 `Authorization: Bearer`(OpenAI);指定 upstream → `r-upstream` 头
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
  /** 默认 true(流式);false 则等待完整响应后一次返回 */
  stream?: boolean;
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
  const doStream = opts.stream ?? true;
  const body = buildBody(opts.serverApi, messages, opts.model, opts.maxTokens, doStream);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (opts.upstreamName) headers["r-upstream"] = opts.upstreamName;
  if (opts.overrideApiKey) {
    if (opts.serverApi === ServerApi.MESSAGES) {
      headers["x-api-key"] = opts.overrideApiKey;
    } else {
      headers["authorization"] = `Bearer ${opts.overrideApiKey}`;
    }
  }

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

  if (!doStream) {
    const json: Record<string, unknown> = await resp.json();
    const fullText = extractText(json, opts.serverApi);
    opts.onToken(fullText);
    const inputTokens = extractInputTokens(json, opts.serverApi);
    const outputTokens = extractOutputTokens(json, opts.serverApi);
    opts.onRawFrame?.({
      event: "done",
      data: json,
      raw: JSON.stringify(json, null, 2),
      receivedAt: new Date().toISOString(),
    } satisfies SseFrame);
    return {
      text: fullText,
      inputTokens,
      outputTokens,
      latencyMs: Math.round(performance.now() - t0),
      aborted: false,
    };
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
  stream: boolean,
): Record<string, unknown> {
  const modelField: Record<string, unknown> = model ? { model } : {};
  if (serverApi === ServerApi.MESSAGES) {
    return { ...modelField, max_tokens: maxTokens, stream, messages };
  }
  if (serverApi === ServerApi.CHAT_COMPLETIONS) {
    return {
      ...modelField,
      stream,
      ...(stream ? { stream_options: { include_usage: true } } : {}),
      max_tokens: maxTokens,
      messages,
    };
  }
  return {
    ...modelField,
    stream,
    max_output_tokens: maxTokens,
    input: messages.map((m) => ({
      type: "message",
      role: m.role,
      content: m.content,
    })),
  };
}

function extractText(json: Record<string, unknown>, serverApi: ServerApi): string {
  if (serverApi === ServerApi.MESSAGES) {
    const content = json.content as Array<Record<string, unknown>> | undefined;
    if (!content) return "";
    return content
      .filter((b) => b.type === "text")
      .map((b) => String(b.text ?? ""))
      .join("");
  }
  if (serverApi === ServerApi.CHAT_COMPLETIONS) {
    const choices = json.choices as Array<Record<string, unknown>> | undefined;
    return (choices?.[0]?.message as Record<string, unknown>)?.content as string ?? "";
  }
  const output = json.output as Array<Record<string, unknown>> | undefined;
  if (!output) return "";
  return output
    .filter((b) => b.type === "message")
    .flatMap((m) => (m.content as Array<Record<string, unknown>>) ?? [])
    .filter((b) => b.type === "output_text")
    .map((b) => String(b.text ?? ""))
    .join("");
}

function extractInputTokens(json: Record<string, unknown>, serverApi: ServerApi): number {
  if (serverApi === ServerApi.MESSAGES) return (json.usage as Record<string, number>)?.input_tokens ?? 0;
  if (serverApi === ServerApi.CHAT_COMPLETIONS) return (json.usage as Record<string, number>)?.prompt_tokens ?? 0;
  return 0;
}

function extractOutputTokens(json: Record<string, unknown>, serverApi: ServerApi): number {
  if (serverApi === ServerApi.MESSAGES) return (json.usage as Record<string, number>)?.output_tokens ?? 0;
  if (serverApi === ServerApi.CHAT_COMPLETIONS) return (json.usage as Record<string, number>)?.completion_tokens ?? 0;
  return 0;
}
