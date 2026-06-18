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
import { ChatError, runTurn, type ChatTurnMsg } from "@/lib/chat";

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
  const [serverApi, setServerApi] = useState<ServerApi>(ServerApi.MESSAGES);
  // model 留空(空字符串) → 不发 body.model,server 用 upstream.model 兜底;与
  // override api-key 的"留空 = 用 DB,填值 = 覆盖"语义对齐。
  // v0 不再硬编码 client 端"默认模型推荐";placeholder 显示 upstream.model 提示
  const [model, setModel] = useState<string>("");
  const [upstreamChoice, setUpstreamChoice] = useState<string>(NO_UPSTREAM_SELECTED);
  const [showAllUpstreams, setShowAllUpstreams] = useState(false);

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

  // mount-only 拉取 upstreams 列表;切 server_api 时的预选由 onServerApiChange 接手,
  // 避免重新 fetch 覆盖用户已经手选的 upstreamChoice
  useEffect(() => {
    (async () => {
      try {
        const list = await api.listUpstreams();
        // 后端按 created_at 升序返回;UI 倒序让最新创建的排在最前
        const sorted = [...list].reverse();
        setUpstreams(sorted);
        // 优先选当前 server_api(初始 MESSAGES)的 default(enabled);没有则
        // 保留 NO_UPSTREAM_SELECTED(用户可手选,或不选直接发让 server fallback)
        const dft = sorted.find(
          (u) => u.native_api === ServerApi.MESSAGES && u.is_default && u.enabled,
        );
        if (dft) {
          setUpstreamChoice(String(dft.id));
        }
      } catch (e) {
        setUpstreamsErr(extractErr(e));
      }
    })();
  }, []);

  // 切 server_api:回到 auto + 重选当前 server_api 的 upstream。优先级:
  //   default(若有) → 该 server_api 第一个 enabled → mock(any)→ NO_UPSTREAM_SELECTED
  // 真正发请求时若 model 留空不带 body.model,由 forwarder 走 upstream.model
  const onServerApiChange = useCallback(
    (next: ServerApi) => {
      setServerApi(next);
      setModel("");
      const matches = upstreams.filter(
        (u) => (u.native_api === next || u.native_api === "any") && u.enabled,
      );
      const dft = matches.find((u) => u.native_api === next && u.is_default);
      const first =
        matches.find((u) => u.native_api === next) ?? matches.find((u) => u.native_api === "any");
      const picked = dft ?? first ?? null;
      setUpstreamChoice(picked ? String(picked.id) : NO_UPSTREAM_SELECTED);
    },
    [upstreams],
  );

  // 当前 server_api 是否在 server 端配了 default(用于"未选 upstream 仍可发送"的判断)
  const hasDefaultForServerApi = useMemo(
    () => upstreams.some((u) => u.native_api === serverApi && u.is_default && u.enabled),
    [upstreams, serverApi],
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

  // 默认只显示当前 server_api 匹配 + any 的 upstream(mock 跨格式接受)。
  // showAllUpstreams 打开后显示全部,用于显式验证跨 API 类型 IR 翻译路径。
  const filteredUpstreams = useMemo(
    () =>
      showAllUpstreams
        ? upstreams
        : upstreams.filter((u) => u.native_api === serverApi || u.native_api === "any"),
    [upstreams, serverApi, showAllUpstreams],
  );

  const resolvedUpstream = useMemo<UpstreamOut | null>(() => {
    if (upstreamChoice === NO_UPSTREAM_SELECTED) return null;
    return upstreamById.get(upstreamChoice) ?? null;
  }, [upstreamChoice, upstreamById]);

  // 显式选了一行 → 发送 OK
  // 没选(NO_UPSTREAM_SELECTED)→ 仅当当前 server_api 有 default 时允许,走 server fallback
  // model 不再要求非空:留空时 server 用 upstream.model 兜底
  const canSend =
    !inFlight &&
    input.trim().length > 0 &&
    (resolvedUpstream !== null || hasDefaultForServerApi);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || inFlight) return;
    if (!resolvedUpstream && !hasDefaultForServerApi) return;
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

    // 没选 upstream → 不传 header,server 按 server_api default fallback
    const upstreamName = resolvedUpstream ? resolvedUpstream.name : null;
    const upstreamLabel = resolvedUpstream ? formatUpstreamLabel(resolvedUpstream) : "default";
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
    serverApi,
    model,
    resolvedUpstream,
    hasDefaultForServerApi,
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
            server_api
          </Label>
          <Select value={serverApi} onValueChange={(v) => onServerApiChange(v as ServerApi)}>
            <SelectTrigger>
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

        <div>
          <div className="mb-1 flex items-center justify-between gap-3">
            <Label className="block text-xs uppercase tracking-wide text-muted-foreground">
              Upstream
            </Label>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={showAllUpstreams}
                onChange={(e) => setShowAllUpstreams(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              show all
            </label>
          </div>
          <Select value={upstreamChoice} onValueChange={setUpstreamChoice}>
            <SelectTrigger>
              <SelectValue placeholder="请选择 upstream" />
            </SelectTrigger>
            <SelectContent
              position="popper"
              side="bottom"
              align="start"
              sideOffset={4}
              avoidCollisions={false}
            >
              {filteredUpstreams.map((u) => (
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
            hasDefaultForServerApi && (
              <p className="mt-1 text-xs text-muted-foreground">
                未选 upstream → 走 server_api={serverApi} 的 default(server 端 fallback)。
              </p>
            )}
          {!upstreamsErr &&
            upstreams.length > 0 &&
            !resolvedUpstream &&
            !hasDefaultForServerApi && (
              <p className="mt-1 text-xs text-muted-foreground">
                server_api={serverApi} 无 default upstream;选一行,或去 Upstreams 页"Set default"。
              </p>
            )}
        </div>

        <div>
          <Label className="mb-1 block text-xs uppercase tracking-wide text-muted-foreground">
            Model
          </Label>
          <Input
            value={model}
            placeholder={
              resolvedUpstream?.model
                ? `留空 = 用 ${resolvedUpstream.model}(upstream 默认)`
                : "留空 = 走 upstream.model;请在 Upstreams 设默认或填具体 model"
            }
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
      </div>

      <div
        ref={scrollRef}
        className="mb-3 flex-1 overflow-y-auto rounded-lg border border-border bg-muted/20 p-4"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {resolvedUpstream || hasDefaultForServerApi
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
            resolvedUpstream || hasDefaultForServerApi
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
          disabled={inFlight || (!resolvedUpstream && !hasDefaultForServerApi)}
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

function computePathLabel(serverApi: ServerApi, upstream: UpstreamOut): string {
  const nativeApi = upstream.native_api as ServerApi;
  if (serverApi === nativeApi) return `${serverApi}↔${nativeApi}`;
  return `${serverApi}→IR→${nativeApi}`;
}

function formatUpstreamLabel(upstream: UpstreamOut): string {
  return `${upstream.name}(${upstream.model ?? "auto"}+${upstream.native_api})`;
}

function extractErr(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
