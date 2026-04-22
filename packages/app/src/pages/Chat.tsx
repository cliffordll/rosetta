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
  Format,
  MODEL_CHOICES,
  PROVIDER_NATIVE_FORMAT,
  api,
  type ProviderOut,
} from "@/lib/api";
import { ChatError, runTurn, type ChatTurnMsg } from "@/lib/chat";

const CUSTOM_MODEL_SENTINEL = "__custom__";
const AUTO_PROVIDER = "__auto__";

interface MetaInfo {
  providerLabel: string;
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
  const [format, setFormat] = useState<Format>(Format.MESSAGES);
  const [model, setModel] = useState<string>(DEFAULT_MODELS[Format.MESSAGES]);
  const [useCustomModel, setUseCustomModel] = useState(false);
  const [providerChoice, setProviderChoice] = useState<string>(AUTO_PROVIDER);

  const [providers, setProviders] = useState<ProviderOut[]>([]);
  const [providersErr, setProvidersErr] = useState<string | null>(null);

  const [overrideKey, setOverrideKey] = useState<string | null>(null);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideDraft, setOverrideDraft] = useState("");

  const [messages, setMessages] = useState<DisplayMsg[]>([]);
  const [input, setInput] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const list = await api.listProviders();
        setProviders(list);
      } catch (e) {
        setProvidersErr(extractErr(e));
      }
    })();
  }, []);

  // 切 format:把 model 重置为该 format 的默认首选,并关掉自定义
  const onFormatChange = useCallback((next: Format) => {
    setFormat(next);
    setModel(DEFAULT_MODELS[next]);
    setUseCustomModel(false);
  }, []);

  // auto-scroll to bottom unless user is scrolled up
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - (el.scrollTop + el.clientHeight);
    if (distance < 64) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  const providerById = useMemo(() => {
    const map = new Map<number, ProviderOut>();
    for (const p of providers) map.set(p.id, p);
    return map;
  }, [providers]);

  const resolvedProvider = useMemo<ProviderOut | null>(() => {
    if (providerChoice === AUTO_PROVIDER) return null;
    const idNum = Number(providerChoice);
    return Number.isFinite(idNum) ? providerById.get(idNum) ?? null : null;
  }, [providerChoice, providerById]);

  const canSend = !inFlight && input.trim().length > 0 && model.trim().length > 0;

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || inFlight) return;
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

    const providerName = resolvedProvider?.name ?? null;
    const providerLabel = resolvedProvider?.name ?? "auto";
    const pathLabel = computePathLabel(format, resolvedProvider);

    try {
      const result = await runTurn(history, {
        fmt: format,
        model,
        providerName,
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
              providerLabel,
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
      const msg = e instanceof ChatError ? `HTTP ${e.status}: ${e.body.slice(0, 300)}` : extractErr(e);
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
  }, [input, inFlight, messages, format, model, resolvedProvider, overrideKey]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
  }, []);

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
            Format
          </Label>
          <Select value={format} onValueChange={(v) => onFormatChange(v as Format)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={Format.MESSAGES}>messages</SelectItem>
              <SelectItem value={Format.CHAT_COMPLETIONS}>completions</SelectItem>
              <SelectItem value={Format.RESPONSES}>responses</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className="mb-1 block text-xs uppercase tracking-wide text-muted-foreground">
            Provider
          </Label>
          <Select value={providerChoice} onValueChange={setProviderChoice}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTO_PROVIDER}>auto (路由表)</SelectItem>
              {providers.map((p) => (
                <SelectItem key={p.id} value={String(p.id)}>
                  {p.name} · {p.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {providersErr && (
            <p className="mt-1 text-xs text-destructive">加载 providers 失败:{providersErr}</p>
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
                  setModel(DEFAULT_MODELS[format]);
                }}
              >
                预设
              </Button>
            </div>
          ) : (
            <Select
              value={MODEL_CHOICES[format].includes(model) ? model : CUSTOM_MODEL_SENTINEL}
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
                {MODEL_CHOICES[format].map((m) => (
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
          <p className="text-sm text-muted-foreground">输入消息开始对话;流式逐 token 渲染。</p>
        ) : (
          <ul className="space-y-4">
            {messages.map((m, i) => (
              <li key={i}>
                <MessageBubble msg={m} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex gap-2">
        <Textarea
          value={input}
          placeholder="发消息…(Enter 发送,Shift+Enter 换行)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) void handleSend();
            }
          }}
          disabled={inFlight}
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
              仅本次会话内生效(不落地)。留空等于清除;下一次请求将走 provider 的 DB key。
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

function MessageBubble({ msg }: { msg: DisplayMsg }) {
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
      {msg.meta && <MetaLine meta={msg.meta} />}
    </div>
  );
}

function MetaLine({ meta }: { meta: MetaInfo }) {
  const parts = [
    meta.providerLabel,
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

function computePathLabel(fmt: Format, provider: ProviderOut | null): string {
  if (!provider) return "?";
  const nativeFmt = PROVIDER_NATIVE_FORMAT[provider.type];
  if (!nativeFmt) return "?";
  if (fmt === nativeFmt) return `${fmt}↔${nativeFmt}`;
  return `${fmt}→IR→${nativeFmt}`;
}

function extractErr(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
