import type { SseFrame } from "@/lib/sse";

export interface RawChatRequest {
  url: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
}

export interface RawChatError {
  status: number;
  body: string;
}

export interface RawChatTurn {
  request: RawChatRequest | null;
  responseFrames: SseFrame[];
  error: RawChatError | null;
}

export interface RawChatResponse {
  responseFrames: SseFrame[];
  error: RawChatError | null;
}

export interface RawTextPreview {
  text: string;
  isTruncated: boolean;
  omittedChars: number;
}

export interface RawResponseFramePreview {
  text: string;
  isTruncated: boolean;
  hiddenFrames: number;
}

export function emptyRawChatTurn(): RawChatTurn {
  return {
    request: null,
    responseFrames: [],
    error: null,
  };
}

export function formatRawTurn(turn: RawChatTurn): string {
  return JSON.stringify(
    {
      request: turn.request,
      response: {
        frames: turn.responseFrames,
        error: turn.error,
      },
    },
    null,
    2,
  );
}

export function previewLongText(text: string, maxChars: number): RawTextPreview {
  if (text.length <= maxChars) {
    return { text, isTruncated: false, omittedChars: 0 };
  }
  const headChars = Math.ceil(maxChars / 2);
  const tailChars = Math.floor(maxChars / 2);
  const omittedChars = text.length - headChars - tailChars;
  return {
    text: [
      text.slice(0, headChars),
      `... hidden ${omittedChars} chars ...`,
      text.slice(text.length - tailChars),
    ].join("\n\n"),
    isTruncated: true,
    omittedChars,
  };
}

export function previewRawResponseFrames(
  response: RawChatResponse,
  opts: { edgeFrames: number; revealedMiddleFrames: number },
): RawResponseFramePreview {
  const total = response.responseFrames.length;
  const edgeFrames = Math.max(0, opts.edgeFrames);
  const revealedMiddleFrames = Math.max(0, opts.revealedMiddleFrames);
  const middleStart = edgeFrames;
  const middleEnd = Math.max(middleStart, total - edgeFrames);
  const middleTotal = Math.max(0, middleEnd - middleStart);
  const revealed = Math.min(revealedMiddleFrames, middleTotal);
  const hiddenFrames = Math.max(0, middleTotal - revealed);

  if (hiddenFrames === 0) {
    return {
      text: formatRawResponse(response),
      isTruncated: false,
      hiddenFrames: 0,
    };
  }

  const frames = [
    ...response.responseFrames.slice(0, edgeFrames),
    ...response.responseFrames.slice(middleStart, middleStart + revealed),
  ];
  const tail = response.responseFrames.slice(total - edgeFrames);
  const parts = [
    formatRawResponse({ responseFrames: frames, error: null }),
    `... hidden ${hiddenFrames} frames ...`,
    formatRawResponse({ responseFrames: tail, error: response.error }),
  ].filter(Boolean);

  return {
    text: parts.join("\n\n"),
    isTruncated: true,
    hiddenFrames,
  };
}

export function formatRawRequest(request: RawChatRequest | null): string {
  if (!request) return "request pending";
  const lines = [`POST ${request.url}`];
  for (const [key, value] of Object.entries(request.headers)) {
    lines.push(`${key}: ${value}`);
  }
  lines.push("");
  lines.push(JSON.stringify(request.body, null, 2));
  return lines.join("\n");
}

export function formatParsedRawRequest(request: RawChatRequest | null): string {
  return JSON.stringify(
    {
      request,
    },
    null,
    2,
  );
}

export function formatRawResponse(response: RawChatResponse): string {
  const lines: string[] = [];
  for (const frame of response.responseFrames) {
    lines.push(formatRawSseFrame(frame));
    lines.push("");
  }
  if (response.error) {
    lines.push("[error]");
    lines.push(`HTTP ${response.error.status}`);
    lines.push(response.error.body);
  }
  return lines.join("\n").trimEnd();
}

export function formatParsedRawResponse(response: RawChatResponse): string {
  return JSON.stringify(
    {
      response: {
        frames: response.responseFrames,
        error: response.error,
      },
    },
    null,
    2,
  );
}

function formatRawSseFrame(frame: SseFrame): string {
  const timestamp = frame.receivedAt ?? "unknown";
  const eventLabel = frame.event ? ` event: ${frame.event}` : "";
  const raw = frame.raw ?? formatParsedFrameFallback(frame);
  const rawLines = raw.split(/\r?\n/);
  const bodyLines = rawLines.filter((line) => !line.startsWith("event:"));
  return [`[${timestamp}]${eventLabel}`, ...bodyLines].join("\n");
}

function formatParsedFrameFallback(frame: SseFrame): string {
  const lines: string[] = [];
  if (frame.event) lines.push(`event: ${frame.event}`);
  lines.push(`data: ${JSON.stringify(frame.data)}`);
  return lines.join("\n");
}
