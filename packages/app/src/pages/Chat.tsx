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
import {
  ApiError,
  DEFAULT_MODELS,
  MODEL_CHOICES,
  Protocol,
  api,
  type UpstreamOut,
} from "@/lib/api";
import { ChatError, runTurn, type ChatTurnMsg } from "@/lib/chat";

const CUSTOM_MODEL_SENTINEL = "__custom__";
const NO_UPSTREAM_SELECTED = "__none__";

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
  | { role: "user"; content: string }
  | {
      role: "assistant";
      content: string;
      meta: MetaInfo | null;
      status: "streaming" | "done" | "aborted" | "error";
      errorMsg: string | null;
    };

export default function Chat() {
  const [protocol, setProtocol] = useState<Protocol>(Protocol.MESSAGES);
  const [model, setModel] = useState<string>(DEFAULT_MODELS[Protocol.MESSAGES]);
  const [useCustomModel, setUseCustomModel] = useState(false);
  const [upstreamChoice, setUpstreamChoice] = useState<string>(NO_UPSTREAM_SELECTED);

  const [upstreams, setUpstreams] = useState<UpstreamOut[]>([]);
  const [upstreamsErr, setUpstreamsErr] = useState<string | null>(null);

  const [overrideKey, setOverrideKey] = useState<string | null>(null);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideDraft, setOverrideDraft] = useState("");

  const [messages, setMessages] = useState<DisplayMsg[]>([]);
  const [input, setInput] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // mount-only 拉取 upstreams 列表;切 protocol 时的预选由 onProtocolChange 接手,
  // 避免重新 fetch 覆盖用户已经手选的 upstreamChoice
  useEffect(() => {
    (async () => {
      try {
        const list = await api.listUpstreams();
        // 后端按 created_at 升序返回;UI 倒序让最新创建的排在最前
        const sorted = [...list].reverse();
        setUpstreams(sorted);
        // 优先选当前 protocol(初始 MESSAGES)的 default(enabled);没有则
        // 保留 NO_UPSTREAM_SELECTED(用户可手选,或不选直接发让 server fallback)
        const dft = sorted.find(
          (u) => u.protocol === Protocol.MESSAGES && u.is_default && u.enabled,
        );
        if (dft) {
          setUpstreamChoice(String(dft.id));
        }
      } catch (e) {
        setUpstreamsErr(extractErr(e));
      }
    })();
  }, []);

  // 切 protocol:重置 model 默认 + 关自定义 + 重选当前 protocol 的 default upstream
  const onProtocolChange = useCallback(
    (next: Protocol) => {
      setProtocol(next);
      setModel(DEFAULT_MODELS[next]);
      setUseCustomModel(false);
      const dft = upstreams.find(
        (u) => u.protocol === next && u.is_default && u.enabled,
      );
      setUpstreamChoice(dft ? String(dft.id) : NO_UPSTREAM_SELECTED);
    },
    [upstreams],
  );

  // 当前 protocol 是否在 server 端配了 default(用于"未选 upstream 仍可发送"的判断)
  const hasDefaultForProtocol = useMemo(
    () => upstreams.some((u) => u.protocol === protocol && u.is_default && u.enabled),
    [upstreams, protocol],
  );

  // auto-scroll to bottom unless user is scrolled up
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - (el.scrollTop + el.clientHeight);
    if (distance < 64) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  const upstreamById = useMemo(() => {
    const map = new Map<string, UpstreamOut>();
    for (const u of upstreams) map.set(u.id, u);
    return map;
  }, [upstreams]);

  const resolvedUpstream = useMemo<UpstreamOut | null>(() => {
    if (upstreamChoice === NO_UPSTREAM_SELECTED) return null;
    return upstreamById.get(upstreamChoice) ?? null;
  }, [upstreamChoice, upstreamById]);

  // 显式选了一行 → 发送 OK
  // 没选(NO_UPSTREAM_SELECTED)→ 仅当当前 protocol 有 default 时允许,走 server fallback
  const canSend =
    !inFlight &&
    input.trim().length > 0 &&
    model.trim().length > 0 &&
    (resolvedUpstream !== null || hasDefaultForProtocol);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || inFlight) return;
    if (!resolvedUpstream && !hasDefaultForProtocol) return;
    setInput("");

    const nextMsgs: DisplayMsg[] = [
      ...messages,
      { role: "user", content: text },
      {
        role: "assistant",
        content: "",
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

    // 没选 upstream → 不传 header,server 按 protocol default fallback
    const upstreamName = resolvedUpstream ? resolvedUpstream.name : null;
    const upstreamLabel = resolvedUpstream ? resolvedUpstream.name : "default";
    const pathLabel = resolvedUpstream
      ? computePathLabel(protocol, resolvedUpstream)
      : protocol;

    try {
      const result = await runTurn(history, {
        fmt: protocol,
        model,
        upstreamName,
        overrideApiKey: overrideKey,
        maxTokens: 1024,
        signal: ctrl.signal,
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
              model,
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
          copy[copy.length - 1] = { ...last, status: "error", errorMsg: msg };
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
    protocol,
    model,
    resolvedUpstream,
    hasDefaultForProtocol,
    overrideKey,
  ]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
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
    <section className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Chat</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={openOverrideDialog}>
            {overrideKey ? "Override api-key · set" : "Override api-key"}
          </Button>
          <Button variant="outline" size="sm" onClick={handleNewChat}>
            New chat
          </Button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-3 gap-3">
        <div>
          <Label className="mb-1 block text-xs uppercase tracking-wide text-muted-foreground">
            Protocol
          </Label>
          <Select value={protocol} onValueChange={(v) => onProtocolChange(v as Protocol)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={Protocol.MESSAGES}>messages</SelectItem>
              <SelectItem value={Protocol.CHAT_COMPLETIONS}>completions</SelectItem>
              <SelectItem value={Protocol.RESPONSES}>responses</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className="mb-1 block text-xs uppercase tracking-wide text-muted-foreground">
            Upstream
          </Label>
          <Select value={upstreamChoice} onValueChange={setUpstreamChoice}>
            <SelectTrigger>
              <SelectValue placeholder="请选择 upstream" />
            </SelectTrigger>
            <SelectContent>
              {upstreams.map((u) => (
                <SelectItem key={u.id} value={String(u.id)}>
                  {u.name} · {u.protocol}
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
            hasDefaultForProtocol && (
              <p className="mt-1 text-xs text-muted-foreground">
                未选 upstream → 走 protocol={protocol} 的 default(server 端 fallback)。
              </p>
            )}
          {!upstreamsErr &&
            upstreams.length > 0 &&
            !resolvedUpstream &&
            !hasDefaultForProtocol && (
              <p className="mt-1 text-xs text-muted-foreground">
                protocol={protocol} 无 default upstream;选一行,或去 Upstreams 页"Set default"。
              </p>
            )}
        </div>

        <div>
          <Label className="mb-1 block text-xs uppercase tracking-wide text-muted-foreground">
            Model
          </Label>
          {useCustomModel ? (
            <div className="flex gap-1">
              <Input
                value={model}
                placeholder="模型 id"
                onChange={(e) => setModel(e.target.value)}
              />
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setUseCustomModel(false);
                  setModel(DEFAULT_MODELS[protocol]);
                }}
              >
                预设
              </Button>
            </div>
          ) : (
            <Select
              value={MODEL_CHOICES[protocol].includes(model) ? model : CUSTOM_MODEL_SENTINEL}
              onValueChange={(v) => {
                if (v === CUSTOM_MODEL_SENTINEL) {
                  setUseCustomModel(true);
                  return;
                }
                setModel(v);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODEL_CHOICES[protocol].map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
                <SelectItem value={CUSTOM_MODEL_SENTINEL}>自定义…</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      <div
        ref={scrollRef}
        className="mb-3 flex-1 overflow-y-auto rounded-lg border border-border bg-muted/20 p-4"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {resolvedUpstream || hasDefaultForProtocol
              ? "输入消息开始对话;流式逐 token 渲染。"
              : "先在上方选一个 upstream(或去 Upstreams 设 default),再开始对话。"}
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
                  <MessageBubble msg={m} onRetry={canRetry ? handleRetry : undefined} />
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="flex gap-2">
        <Textarea
          value={input}
          placeholder={
            resolvedUpstream || hasDefaultForProtocol
              ? "发消息…(Enter 发送,Shift+Enter 换行)"
              : "请先选择 upstream(或去 Upstreams 设 default)"
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) void handleSend();
            }
          }}
          disabled={inFlight || (!resolvedUpstream && !hasDefaultForProtocol)}
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

function MessageBubble({ msg, onRetry }: { msg: DisplayMsg; onRetry?: () => void }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground whitespace-pre-wrap">
          {msg.content}
        </div>
      </div>
    );
  }

  const isStreaming = msg.status === "streaming";
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

function computePathLabel(fmt: Protocol, upstream: UpstreamOut): string {
  const nativeProto = upstream.protocol as Protocol;
  if (fmt === nativeProto) return `${fmt}↔${nativeProto}`;
  return `${fmt}→IR→${nativeProto}`;
}

function extractErr(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
