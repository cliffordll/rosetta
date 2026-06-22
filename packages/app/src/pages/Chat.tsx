import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, ServerApi, api, serverApiLabel, type UpstreamOut } from "@/lib/api";
import {
  loadChatPreferences,
  saveChatPreferences,
  type ChatViewMode,
} from "@/lib/chat-preferences";
import { changeServerApiSelection, ensureUpstreamChoice } from "@/lib/chat-selection";
import { ChatError, runTurn, type ChatTurnMsg } from "@/lib/chat";
import {
  emptyRawChatTurn,
  formatParsedRawRequest,
  formatParsedRawResponse,
  formatRawRequest,
  formatRawResponse,
  previewLongText,
  previewRawResponseFrames,
  type RawChatError,
  type RawChatRequest,
  type RawChatTurn,
} from "@/lib/chat-raw";
import type { SseFrame } from "@/lib/sse";

const NO_UPSTREAM_SELECTED = "__none__";
const DEFAULT_RAW_EDGE_FRAMES = 5;
const DEFAULT_RAW_EXPAND_STEP = 10;

interface MetaInfo {
  upstreamLabel: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  latencyMs: number;
  pathLabel: string;
  overrideKey: boolean;
}

type DisplayMsg =
  | { role: "user"; content: string; rawRequest: RawChatRequest | null }
  | {
      role: "assistant";
      content: string;
      raw: RawChatTurn;
      meta: MetaInfo | null;
      status: "streaming" | "done" | "aborted" | "error";
      errorMsg: string | null;
    };

export default function Chat() {
  const initialPreferences = useMemo(() => loadBrowserChatPreferences(), []);
  const [serverApi, setServerApi] = useState<ServerApi>(
    initialPreferences.serverApi ?? ServerApi.MESSAGES,
  );
  // model 留空(空字符串) → 不发 body.model,server 用 upstream.model 兜底;与
  // override api-key 的"留空 = 用 DB,填值 = 覆盖"语义对齐。
  // v0 不再硬编码 client 端"默认模型推荐";placeholder 显示 upstream.model 提示
  const [model, setModel] = useState<string>(initialPreferences.model ?? "");
  const [upstreamChoice, setUpstreamChoice] = useState<string>(
    initialPreferences.upstreamChoice ?? NO_UPSTREAM_SELECTED,
  );

  const [upstreams, setUpstreams] = useState<UpstreamOut[]>([]);
  const [upstreamsErr, setUpstreamsErr] = useState<string | null>(null);

  const [overrideKey, setOverrideKey] = useState<string | null>(null);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideDraft, setOverrideDraft] = useState("");

  const [messages, setMessages] = useState<DisplayMsg[]>([]);
  const [input, setInput] = useState("");
  const [viewMode, setViewMode] = useState<ChatViewMode>(
    initialPreferences.viewMode ?? "nice",
  );
  const [rawEdgeFrames, setRawEdgeFrames] = useState(
    initialPreferences.rawEdgeFrames ?? DEFAULT_RAW_EDGE_FRAMES,
  );
  const [rawExpandStep, setRawExpandStep] = useState(
    initialPreferences.rawExpandStep ?? DEFAULT_RAW_EXPAND_STEP,
  );
  const [inFlight, setInFlight] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);

  // mount-only 拉取 upstreams 列表,避免重新 fetch 覆盖用户已经手选的 upstreamChoice
  useEffect(() => {
    (async () => {
      try {
        const list = await api.listUpstreams();
        // 后端按 created_at 升序返回;UI 倒序让最新创建的排在最前
        const sorted = [...list].reverse();
        setUpstreams(sorted);
      } catch (e) {
        setUpstreamsErr(extractErr(e));
      }
    })();
  }, []);

  // 首次加载及 Fast Refresh 后校正空选择;已有明确选择时不覆盖。
  useEffect(() => {
    setUpstreamChoice((current) =>
      ensureUpstreamChoice(current, upstreams, NO_UPSTREAM_SELECTED),
    );
  }, [upstreams]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    saveChatPreferences(window.localStorage, {
      serverApi,
      upstreamChoice,
      model,
      viewMode,
      rawEdgeFrames,
      rawExpandStep,
    });
  }, [model, rawEdgeFrames, rawExpandStep, serverApi, upstreamChoice, viewMode]);

  // server_api 和 upstream 独立选择;切 API 时保留当前 upstream,只清空客户端 model override。
  const onServerApiChange = useCallback(
    (next: ServerApi) => {
      const selection = changeServerApiSelection(
        { serverApi, upstreamChoice, model },
        next,
      );
      setServerApi(selection.serverApi);
      setUpstreamChoice(selection.upstreamChoice);
      setModel(selection.model);
    },
    [model, serverApi, upstreamChoice],
  );

  // 默认跟随最新消息;用户手动上翻后暂停,回到底部或发送新消息后恢复。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, viewMode]);

  const upstreamById = useMemo(() => {
    const map = new Map<string, UpstreamOut>();
    for (const u of upstreams) map.set(u.id, u);
    return map;
  }, [upstreams]);

  const resolvedUpstream = useMemo<UpstreamOut | null>(() => {
    if (upstreamChoice === NO_UPSTREAM_SELECTED) return null;
    return upstreamById.get(upstreamChoice) ?? null;
  }, [upstreamChoice, upstreamById]);

  const hasModelRouting = model.trim().length > 0;
  // 显式选了一行 → 发送 OK;未选 upstream → 必须填写 model,server 按 model 匹配。
  // 只有选中 upstream 时,model 才允许留空并由 upstream.model 兜底。
  const canSend =
    !inFlight &&
    input.trim().length > 0 &&
    (resolvedUpstream !== null || hasModelRouting);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || inFlight) return;
    if (!resolvedUpstream && !hasModelRouting) return;
    setInput("");
    stickToBottomRef.current = true;

    const nextMsgs: DisplayMsg[] = [
      ...messages,
      { role: "user", content: text, rawRequest: null },
      {
        role: "assistant",
        content: "",
        raw: emptyRawChatTurn(),
        meta: null,
        status: "streaming",
        errorMsg: null,
      },
    ];
    setMessages(nextMsgs);
    setInFlight(true);

    const history: ChatTurnMsg[] = nextMsgs.flatMap<ChatTurnMsg>((m) => {
      if (m.role === "user") return [{ role: "user", content: m.content }];
      if (m.content) return [{ role: "assistant", content: m.content }];
      return [];
    });

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    // 没选 upstream → 不传 r-upstream,server 按 body.model 匹配 upstream。
    const upstreamName = resolvedUpstream ? resolvedUpstream.name : null;
    const upstreamLabel = resolvedUpstream ? formatUpstreamLabel(resolvedUpstream) : "model-route";
    const pathLabel = resolvedUpstream
      ? computePathLabel(serverApi, resolvedUpstream)
      : serverApi;
    // model 留空 → runTurn 不发 body.model;meta 行显示估算的 effective model
    // (client 输入 → upstream.model → "auto";server 实际 resolve 可能不同)
    const trimmedModel = model.trim();
    const effectiveModel = trimmedModel || resolvedUpstream?.model || "auto";

    try {
      const result = await runTurn(history, {
        serverApi: serverApi,
        model: trimmedModel || null,
        upstreamName,
        overrideApiKey: overrideKey,
        maxTokens: 1024,
        signal: ctrl.signal,
        onRawRequest: (request) => {
          setMessages((cur) => updateLatestUserRawRequest(cur, request));
        },
        onRawFrame: (frame) => {
          setMessages((cur) => appendLastAssistantRawFrame(cur, frame));
        },
        onToken: (tok) => {
          setMessages((cur) => {
            const copy = cur.slice();
            const last = copy[copy.length - 1];
            if (last && last.role === "assistant" && last.status === "streaming") {
              copy[copy.length - 1] = { ...last, content: last.content + tok };
            }
            return copy;
          });
        },
      });

      setMessages((cur) => {
        const copy = cur.slice();
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") {
          copy[copy.length - 1] = {
            ...last,
            status: result.aborted ? "aborted" : "done",
            meta: {
              upstreamLabel,
              model: effectiveModel,
              inputTokens: result.inputTokens,
              outputTokens: result.outputTokens,
              latencyMs: result.latencyMs,
              pathLabel,
              overrideKey: overrideKey !== null,
            },
          };
        }
        return copy;
      });
    } catch (e) {
      const msg =
        e instanceof ChatError ? `HTTP ${e.status}: ${e.body.slice(0, 300)}` : extractErr(e);
      setMessages((cur) => {
        const copy = cur.slice();
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") {
          const error: RawChatError | null =
            e instanceof ChatError ? { status: e.status, body: e.body } : null;
          copy[copy.length - 1] = {
            ...last,
            raw: error ? { ...last.raw, error } : last.raw,
            status: "error",
            errorMsg: msg,
          };
        }
        return copy;
      });
    } finally {
      setInFlight(false);
      abortRef.current = null;
    }
  }, [
    input,
    inFlight,
    messages,
    serverApi,
    model,
    resolvedUpstream,
    hasModelRouting,
    overrideKey,
  ]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    stickToBottomRef.current = true;
    setMessages([]);
  }, []);

  /**
   * error / aborted 后点 Retry:
   * 1. 从 messages 末尾剥掉最近一对 [user, failed assistant]
   * 2. 把 user.content 回填 input
   * 用户按 Send 完成重试;不强行自动发,避免"黑盒重试"对用户难追踪
   */
  const handleRetry = useCallback(() => {
    if (inFlight) return;
    const copy = messages.slice();
    let failedIdx = -1;
    for (let i = copy.length - 1; i >= 0; i--) {
      if (copy[i].role === "assistant") {
        failedIdx = i;
        break;
      }
    }
    if (failedIdx < 1) return; // 没找到 user/assistant 对,略过
    const userMsg = copy[failedIdx - 1];
    if (userMsg.role !== "user") return;
    setMessages(copy.slice(0, failedIdx - 1));
    setInput(userMsg.content);
  }, [messages, inFlight]);

  const openOverrideDialog = useCallback(() => {
    setOverrideDraft(overrideKey ?? "");
    setOverrideDialogOpen(true);
  }, [overrideKey]);

  const saveOverride = useCallback(() => {
    const v = overrideDraft.trim();
    setOverrideKey(v ? v : null);
    setOverrideDialogOpen(false);
  }, [overrideDraft]);

  const clearOverride = useCallback(() => {
    setOverrideKey(null);
    setOverrideDialogOpen(false);
  }, []);

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex shrink-0 items-center justify-between">
        <h1 className="text-2xl font-semibold">Chat</h1>
        <div className="flex items-center gap-2">
          {viewMode === "raw" && (
            <div className="flex items-center gap-1">
              <Label className="text-xs text-muted-foreground">Edge</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={rawEdgeFrames}
                onChange={(e) => setRawEdgeFrames(parsePositiveInt(e.target.value, 1))}
                className="h-8 w-16"
              />
              <Label className="text-xs text-muted-foreground">Step</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={rawExpandStep}
                onChange={(e) => setRawExpandStep(parsePositiveInt(e.target.value, 1))}
                className="h-8 w-16"
              />
            </div>
          )}
          <div className="flex rounded-md border border-border p-0.5">
            <Button
              type="button"
              variant={viewMode === "nice" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setViewMode("nice")}
            >
              Nice
            </Button>
            <Button
              type="button"
              variant={viewMode === "raw" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setViewMode("raw")}
            >
              Raw
            </Button>
          </div>
          <Button variant="outline" size="sm" onClick={openOverrideDialog}>
            {overrideKey ? "Override api-key · set" : "Override api-key"}
          </Button>
          <Button variant="outline" size="sm" onClick={handleNewChat}>
            New chat
          </Button>
        </div>
      </div>

      <div className="mb-4 grid shrink-0 grid-cols-3 gap-3">
        <div className="grid min-w-0 grid-cols-[68px_minmax(0,1fr)] items-start gap-2">
          <Label className="pt-2.5 text-xs uppercase text-muted-foreground">
            server_api
          </Label>
          <Select value={serverApi} onValueChange={(v) => onServerApiChange(v as ServerApi)}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ServerApi.MESSAGES}>
                {serverApiLabel(ServerApi.MESSAGES)}
              </SelectItem>
              <SelectItem value={ServerApi.CHAT_COMPLETIONS}>
                {serverApiLabel(ServerApi.CHAT_COMPLETIONS)}
              </SelectItem>
              <SelectItem value={ServerApi.RESPONSES}>
                {serverApiLabel(ServerApi.RESPONSES)}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="grid min-w-0 grid-cols-[68px_minmax(0,1fr)] items-start gap-2">
          <Label className="pt-2.5 text-xs uppercase text-muted-foreground">
            Upstream
          </Label>
          <div className="min-w-0">
            <Select value={upstreamChoice} onValueChange={setUpstreamChoice}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="请选择 upstream" />
              </SelectTrigger>
              <SelectContent
                position="popper"
                side="bottom"
                align="start"
                sideOffset={4}
                avoidCollisions={false}
              >
                {upstreams.map((u) => (
                  <SelectItem key={u.id} value={String(u.id)}>
                    {formatUpstreamLabel(u)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {upstreamsErr && (
              <p className="mt-1 text-xs text-destructive">加载 upstreams 失败:{upstreamsErr}</p>
            )}
            {!upstreamsErr && upstreams.length === 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                还没有 upstream,先去 Upstreams 页面添加。
              </p>
            )}
            {!upstreamsErr &&
              upstreams.length > 0 &&
              !resolvedUpstream &&
              model.trim().length > 0 && (
                <p className="mt-1 text-xs text-muted-foreground">
                  未选 upstream → 不发 r-upstream,server 将按 model 匹配 upstream。
                </p>
              )}
          </div>
        </div>

        <div className="grid min-w-0 grid-cols-[68px_minmax(0,1fr)] items-start gap-2">
          <Label className="pt-2.5 text-xs uppercase text-muted-foreground">
            Model
          </Label>
          <Input
            className="min-w-0"
            value={model}
            placeholder={
              resolvedUpstream?.model
                ? `留空 = 用 ${resolvedUpstream.model}(upstream 默认)`
                : "未选 upstream 时必须填写 model,用于自动匹配 upstream"
            }
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          const distance = el.scrollHeight - (el.scrollTop + el.clientHeight);
          stickToBottomRef.current = distance < 64;
        }}
        className="mb-3 min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-muted/20 p-4"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {resolvedUpstream || hasModelRouting
              ? "输入消息开始对话;流式逐 token 渲染。"
              : "先在上方选一个 upstream,或填写 model 让 server 自动匹配。"}
          </p>
        ) : (
          <ul className="space-y-4">
            {messages.map((m, i) => {
              const isLast = i === messages.length - 1;
              const canRetry =
                isLast &&
                m.role === "assistant" &&
                (m.status === "error" || m.status === "aborted");
              return (
                <li key={i}>
                  <MessageBubble
                    msg={m}
                    viewMode={viewMode}
                    rawEdgeFrames={rawEdgeFrames}
                    rawExpandStep={rawExpandStep}
                    onRetry={canRetry ? handleRetry : undefined}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="flex shrink-0 gap-2">
        <Textarea
          value={input}
          placeholder={
            resolvedUpstream || hasModelRouting
              ? "发消息…(Enter 发送,Shift+Enter 换行)"
              : "请选择 upstream,或填写 model"
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) void handleSend();
            }
          }}
          disabled={inFlight || (!resolvedUpstream && !hasModelRouting)}
          className="min-h-20 flex-1"
        />
        {inFlight ? (
          <Button variant="destructive" onClick={handleStop}>
            Stop
          </Button>
        ) : (
          <Button onClick={() => void handleSend()} disabled={!canSend}>
            Send
          </Button>
        )}
      </div>

      <Dialog open={overrideDialogOpen} onOpenChange={setOverrideDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Override api-key</DialogTitle>
            <DialogDescription>
              仅本次会话内生效(不落地)。留空等于清除;下一次请求将走 upstream 的 DB key。
            </DialogDescription>
          </DialogHeader>
          <div className="py-2">
            <Input
              value={overrideDraft}
              onChange={(e) => setOverrideDraft(e.target.value)}
              placeholder="sk-..."
              autoFocus
            />
          </div>
          <DialogFooter>
            {overrideKey && (
              <Button variant="outline" onClick={clearOverride}>
                清除
              </Button>
            )}
            <Button variant="outline" onClick={() => setOverrideDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={saveOverride}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function MessageBubble({
  msg,
  viewMode,
  rawEdgeFrames,
  rawExpandStep,
  onRetry,
}: {
  msg: DisplayMsg;
  viewMode: ChatViewMode;
  rawEdgeFrames: number;
  rawExpandStep: number;
  onRetry?: () => void;
}) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        {viewMode === "raw" ? (
          <RawUserRequest request={msg.rawRequest} />
        ) : (
          <div className="max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground whitespace-pre-wrap">
            {msg.content}
          </div>
        )}
      </div>
    );
  }

  const isStreaming = msg.status === "streaming";
  if (viewMode === "raw") {
    return (
      <div className="flex flex-col items-start gap-1">
        <RawAssistantResponse
          raw={msg.raw}
          edgeFrames={rawEdgeFrames}
          expandStep={rawExpandStep}
        />
        {msg.status === "error" && msg.errorMsg && (
          <div className="max-w-[85%] rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">
            {msg.errorMsg}
          </div>
        )}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            Retry(回填输入框,按 Send 重发)
          </button>
        )}
        {msg.meta && <MetaLine meta={msg.meta} />}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="max-w-[85%] rounded-lg border border-border bg-background px-3 py-2 text-sm whitespace-pre-wrap">
        {msg.content || (isStreaming ? <span className="text-muted-foreground">…</span> : null)}
        {msg.status === "aborted" && (
          <span className="ml-1 text-xs text-muted-foreground">[已中断]</span>
        )}
      </div>
      {msg.status === "error" && msg.errorMsg && (
        <div className="max-w-[85%] rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">
          {msg.errorMsg}
        </div>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="text-xs text-muted-foreground underline-offset-2 hover:underline"
        >
          Retry(回填输入框,按 Send 重发)
        </button>
      )}
      {msg.meta && <MetaLine meta={msg.meta} />}
    </div>
  );
}

const RAW_PREVIEW_CHARS = 8000;

function RawUserRequest({ request }: { request: RawChatRequest | null }) {
  const [format, setFormat] = useState<"raw" | "json">("raw");
  const [expanded, setExpanded] = useState(false);
  const fullText =
    format === "raw" ? formatRawRequest(request) : formatParsedRawRequest(request);
  const preview = expanded ? { text: fullText, isTruncated: false, omittedChars: 0 } : previewLongText(fullText, RAW_PREVIEW_CHARS);
  return (
    <div className="flex max-w-full flex-col items-end gap-1">
      <div className="flex gap-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setFormat((current) => (current === "raw" ? "json" : "raw"))}
        >
          {format === "raw" ? "Parse JSON" : "Raw Request"}
        </Button>
        {(preview.isTruncated || expanded) && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? "Collapse" : `Show hidden (${preview.omittedChars})`}
          </Button>
        )}
      </div>
      <pre className="max-w-full overflow-x-auto rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs whitespace-pre">
        {preview.text}
      </pre>
    </div>
  );
}

function RawAssistantResponse({
  raw,
  edgeFrames,
  expandStep,
}: {
  raw: RawChatTurn;
  edgeFrames: number;
  expandStep: number;
}) {
  const [format, setFormat] = useState<"sse" | "json">("sse");
  const [expanded, setExpanded] = useState(false);
  const [revealedMiddleFrames, setRevealedMiddleFrames] = useState(0);
  const response = {
    responseFrames: raw.responseFrames,
    error: raw.error,
  };
  const fullText =
    format === "sse" ? formatRawResponse(response) : formatParsedRawResponse(response);
  const framePreview =
    expanded || format === "json"
      ? null
      : previewRawResponseFrames(response, {
          edgeFrames,
          revealedMiddleFrames,
        });
  const textPreview =
    framePreview ??
    (expanded
      ? { text: fullText, isTruncated: false, omittedChars: 0 }
      : previewLongText(fullText, RAW_PREVIEW_CHARS));
  const canRevealMore = framePreview !== null && framePreview.hiddenFrames > 0;

  return (
    <div className="flex max-w-full flex-col items-start gap-1">
      <div className="flex gap-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setFormat((current) => (current === "sse" ? "json" : "sse"))}
        >
          {format === "sse" ? "Parse JSON" : "Raw SSE"}
        </Button>
        {canRevealMore && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              setRevealedMiddleFrames((current) => current + expandStep)
            }
          >
            Show {expandStep} more ({framePreview.hiddenFrames})
          </Button>
        )}
        {(textPreview.isTruncated || expanded) && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setExpanded((current) => !current);
              setRevealedMiddleFrames(0);
            }}
          >
            {expanded ? "Collapse" : "Show all"}
          </Button>
        )}
      </div>
      <pre className="max-w-full overflow-x-auto rounded-lg border border-border bg-background px-3 py-2 text-xs whitespace-pre">
        {textPreview.text}
      </pre>
    </div>
  );
}

function MetaLine({ meta }: { meta: MetaInfo }) {
  const parts = [
    meta.upstreamLabel,
    meta.model,
    `${meta.inputTokens}→${meta.outputTokens} tok`,
    `${meta.latencyMs} ms`,
    meta.pathLabel,
  ];
  if (meta.overrideKey) parts.push("override");
  return (
    <div className="text-xs text-muted-foreground font-mono">[{parts.join(" · ")}]</div>
  );
}

function computePathLabel(serverApi: ServerApi, upstream: UpstreamOut): string {
  const nativeApi = upstream.native_api as ServerApi;
  if (serverApi === nativeApi) return `${serverApi}↔${nativeApi}`;
  return `${serverApi}→IR→${nativeApi}`;
}

function formatUpstreamLabel(upstream: UpstreamOut): string {
  return `${upstream.name}(${upstream.model ?? "auto"}+${upstream.native_api})`;
}

function loadBrowserChatPreferences() {
  if (typeof window === "undefined") return {};
  return loadChatPreferences(window.localStorage);
}

function parsePositiveInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function updateLatestUserRawRequest(
  messages: DisplayMsg[],
  request: RawChatRequest,
): DisplayMsg[] {
  const copy = messages.slice();
  for (let i = copy.length - 1; i >= 0; i--) {
    const msg = copy[i];
    if (msg.role === "user") {
      copy[i] = { ...msg, rawRequest: request };
      return copy;
    }
  }
  return messages;
}

function appendLastAssistantRawFrame(messages: DisplayMsg[], frame: SseFrame): DisplayMsg[] {
  const copy = messages.slice();
  const last = copy[copy.length - 1];
  if (!last || last.role !== "assistant") return messages;
  copy[copy.length - 1] = {
    ...last,
    raw: {
      ...last.raw,
      responseFrames: [...last.raw.responseFrames, frame],
    },
  };
  return copy;
}

function extractErr(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
