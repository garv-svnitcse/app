import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { KeyRound, Loader2, PanelLeft, SendHorizontal, ShieldCheck, Sparkles, Square } from "lucide-react";
import { toast } from "sonner";
import { PageHeader, EmptyState } from "@/components/module/ModulePrimitives";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ConversationList } from "@/components/ai/ConversationList";
import { AssistantMessage, UserBubble } from "@/components/ai/ChatMessage";
import { streamMessage } from "@/components/ai/streamChat";
import { MAX_MESSAGE_CHARS, SUGGESTIONS } from "@/components/ai/aiConfig";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { api, formatApiError } from "@/lib/api";

const PANE_HEIGHT = "h-[calc(100dvh-230px)] min-h-[460px]";

function dropTrailingAssistant(list) {
  const out = [...list];
  while (out.length && out[out.length - 1].role === "assistant") out.pop();
  return out;
}

export default function WavygoAI() {
  const { user } = useAuth();
  const { can, role } = usePermission();
  const allowed = can("ai.use");
  const [params, setParams] = useSearchParams();

  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [convs, setConvs] = useState([]);
  const [convsLoading, setConvsLoading] = useState(true);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [convLoading, setConvLoading] = useState(false);
  const [pending, setPending] = useState(null);
  const [input, setInput] = useState("");
  const [listOpen, setListOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const abortRef = useRef(null);
  const activeRef = useRef(null);
  const scrollRef = useRef(null);
  const stickRef = useRef(true);
  const inputRef = useRef(null);

  const busy = Boolean(pending);
  const configured = Boolean(status?.configured);
  const activeTitle = convs.find((c) => c.id === activeId)?.title;

  const loadStatus = useCallback(async () => {
    try {
      const { data } = await api.get("/ai/status");
      setStatus(data);
      setStatusError(null);
    } catch (e) {
      setStatusError(formatApiError(e));
    }
  }, []);

  const loadConvs = useCallback(async () => {
    try {
      const { data } = await api.get("/ai/conversations");
      setConvs(data);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setConvsLoading(false);
    }
  }, []);

  const setUrlConversation = useCallback((id) => {
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (id) next.set("c", id); else next.delete("c");
      return next;
    }, { replace: true });
  }, [setParams]);

  const openConversation = useCallback(async (id) => {
    abortRef.current?.abort();
    setListOpen(false);
    activeRef.current = id;
    setActiveId(id);
    setUrlConversation(id);
    if (!id) { setMessages([]); return; }
    setConvLoading(true);
    try {
      const { data } = await api.get(`/ai/conversations/${id}`);
      setMessages(data.messages || []);
      stickRef.current = true;
    } catch (e) {
      toast.error(formatApiError(e));
      setActiveId(null);
      setMessages([]);
      setUrlConversation(null);
    } finally {
      setConvLoading(false);
    }
  }, [setUrlConversation]);

  useEffect(() => {
    if (!allowed) return;
    loadStatus();
    loadConvs();
    const initial = params.get("c");
    if (initial) openConversation(initial);
    return () => abortRef.current?.abort();
    // Initial load only; later navigation goes through openConversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed]);

  // Follow the stream while the reader is at the bottom; leave them alone once they scroll up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, pending]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  /** Streams one reply into `pending`; appends the final (or stopped) reply to the transcript. */
  const runReply = async (convId, body) => {
    const controller = new AbortController();
    abortRef.current = controller;
    stickRef.current = true;
    let acc = { role: "assistant", content: "", tool_calls: [] };
    let final = null;
    let errorDetail = null;
    setPending(acc);
    try {
      await streamMessage(convId, body, {
        signal: controller.signal,
        onEvent: (event, data) => {
          if (event === "delta") acc = { ...acc, content: acc.content + (data.text || "") };
          else if (event === "reset") acc = { ...acc, content: data.text || "" };
          else if (event === "tool") {
            const entry = { ...data, ok: data.status !== "error" };
            const idx = acc.tool_calls.findIndex((t) => t.id === data.id);
            acc = {
              ...acc,
              tool_calls: idx >= 0 ? acc.tool_calls.map((t, i) => (i === idx ? { ...t, ...entry } : t)) : [...acc.tool_calls, entry],
            };
          } else if (event === "error") errorDetail = data.detail || "Something went wrong.";
          else if (event === "done") final = data.message;
          setPending(acc);
        },
      });
      const reply = final
        ? { ...final, error: errorDetail || final.error }
        : errorDetail ? { role: "assistant", content: "", tool_calls: acc.tool_calls, error: errorDetail } : null;
      if (reply && activeRef.current === convId) setMessages((m) => [...m, reply]);
    } catch (e) {
      if (e?.name !== "AbortError") throw e;
      if ((acc.content || acc.tool_calls.length) && activeRef.current === convId) {
        setMessages((m) => [...m, { ...acc, tool_calls: acc.tool_calls.filter((t) => t.status !== "running"), stopped: true }]);
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setPending(null);
    }
  };

  const send = async (raw) => {
    const text = (raw ?? input).trim();
    if (!text || busy || !configured) return;
    if (text.length > MAX_MESSAGE_CHARS) {
      toast.error(`Messages can be up to ${MAX_MESSAGE_CHARS} characters.`);
      return;
    }
    let convId = activeId;
    if (!convId) {
      try {
        const { data } = await api.post("/ai/conversations", {});
        convId = data.id;
        setConvs((c) => [data, ...c]);
        activeRef.current = convId;
        setActiveId(convId);
        setUrlConversation(convId);
        setMessages([]);
      } catch (e) {
        toast.error(formatApiError(e));
        return;
      }
    }
    const userMsg = { role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    try {
      await runReply(convId, { content: text });
    } catch (e) {
      setMessages((m) => m.filter((x) => x !== userMsg));
      setInput(text);
      toast.error(e.message || "Could not send the message");
      if (e.status === 503) loadStatus();
    }
    loadConvs();
    loadStatus();
  };

  const retry = async () => {
    if (busy || !activeId || !configured) return;
    setMessages((m) => dropTrailingAssistant(m));
    try {
      await runReply(activeId, { regenerate: true });
    } catch (e) {
      toast.error(e.message || "Could not retry");
      openConversation(activeId);
    }
    loadConvs();
    loadStatus();
  };

  const stop = () => abortRef.current?.abort();

  const newChat = () => {
    if (busy) stop();
    openConversation(null);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const rename = async (id, title) => {
    try {
      const { data } = await api.patch(`/ai/conversations/${id}`, { title });
      setConvs((c) => c.map((x) => (x.id === id ? { ...x, title: data.title } : x)));
    } catch (e) {
      toast.error(formatApiError(e));
    }
  };

  const confirmDelete = async () => {
    const target = deleteTarget;
    setDeleteTarget(null);
    if (!target) return;
    try {
      await api.delete(`/ai/conversations/${target.id}`);
      setConvs((c) => c.filter((x) => x.id !== target.id));
      if (target.id === activeId) openConversation(null);
      toast.success("Conversation deleted");
    } catch (e) {
      toast.error(formatApiError(e));
    }
  };

  if (!allowed) {
    return (
      <div>
        <PageHeader eyebrow="Workspace" title="WavyGo AI" />
        <EmptyState icon={ShieldCheck} title="Not available for your role" description="Ask your Founder or Admin for access to WavyGo AI." />
      </div>
    );
  }

  const list = (
    <ConversationList
      conversations={convs}
      loading={convsLoading}
      activeId={activeId}
      onSelect={openConversation}
      onNew={newChat}
      onRename={rename}
      onDelete={setDeleteTarget}
    />
  );

  const suggestions = SUGGESTIONS[role] || SUGGESTIONS.Employee;
  const lastAssistantIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return i;
    return -1;
  })();
  const lastIsUser = messages.length > 0 && messages[messages.length - 1].role === "user";
  const remaining = status?.limits?.remaining_this_hour;

  let body;
  if (!status && !statusError) {
    body = <div className="flex-1 flex items-center justify-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></div>;
  } else if (statusError) {
    body = (
      <div className="flex-1 flex items-center justify-center p-4">
        <EmptyState icon={Sparkles} title="Could not reach WavyGo AI" description={statusError}
                    action={<Button variant="outline" onClick={loadStatus}>Try again</Button>} />
      </div>
    );
  } else if (!configured) {
    body = (
      <div className="flex-1 overflow-y-auto p-4 sm:p-8 flex items-center justify-center" data-testid="ai-not-configured">
        <EmptyState
          icon={KeyRound}
          title="WavyGo AI isn't set up yet"
          description={
            <>
              An administrator needs to add an Anthropic API key to the backend: set the environment variable{" "}
              <code className="rounded bg-muted px-1 font-mono text-[12px]">ANTHROPIC_API_KEY</code> on the server (for example in{" "}
              <code className="rounded bg-muted px-1 font-mono text-[12px]">backend/.env</code>) and restart it. Optionally set{" "}
              <code className="rounded bg-muted px-1 font-mono text-[12px]">ANTHROPIC_MODEL</code> to choose a different Claude model.
              Your saved conversations stay available.
            </>
          }
        />
      </div>
    );
  } else {
    body = (
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto scrollbar-thin px-3 sm:px-5 py-4 space-y-5" data-testid="ai-messages">
        {convLoading ? (
          <div className="flex justify-center py-16 text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></div>
        ) : messages.length === 0 && !pending ? (
          <div className="max-w-xl mx-auto text-center pt-6 sm:pt-12">
            <div className="h-12 w-12 rounded-md bg-primary/10 text-primary flex items-center justify-center mx-auto">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="font-display text-[18px] font-semibold mt-3">Hi {user?.name?.split(" ")[0] || "there"}, how can I help?</div>
            <p className="text-[13px] text-muted-foreground mt-1">
              I can look up your tasks, calendar, team and more — only what your {role} role can see.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-6 text-left">
              {suggestions.map((s) => (
                <button key={s} onClick={() => send(s)}
                        className="rounded-lg border border-border bg-card hover:bg-muted px-3 py-2.5 text-[13px] text-foreground/90 transition-colors"
                        data-testid="ai-suggestion">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((m, i) => (m.role === "user"
              ? <UserBubble key={i} message={m} user={user} />
              : <AssistantMessage key={i} message={m} onRetry={!busy && i === lastAssistantIdx && i === messages.length - 1 ? retry : undefined} />
            ))}
            {pending && <AssistantMessage message={pending} pending />}
            {!pending && lastIsUser && (
              <div className="flex justify-center">
                <Button variant="outline" size="sm" onClick={retry} data-testid="ai-retry-unanswered">Get an answer</Button>
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="Workspace"
        title="WavyGo AI"
        description="Ask about your tasks, calendar, team and company data. Answers only use data your role can access."
        actions={(
          <Button variant="outline" className="lg:hidden gap-1.5" onClick={() => setListOpen(true)} data-testid="ai-open-chats">
            <PanelLeft className="h-4 w-4" /> Chats
          </Button>
        )}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
        <Card className={`hidden lg:flex flex-col border-border p-3 ${PANE_HEIGHT}`}>{list}</Card>

        <Card className={`flex flex-col overflow-hidden border-border ${PANE_HEIGHT}`}>
          <div className="px-4 sm:px-5 py-3 border-b border-border flex items-center gap-3">
            <div className="h-8 w-8 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0">
              <Sparkles className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-display text-[15px] font-semibold truncate">{activeTitle || "New chat"}</div>
              <div className="text-[11px] text-muted-foreground truncate">
                {status?.model ? `Claude · ${status.model}` : "WavyGo AI"}
                {configured && remaining != null && ` · ${remaining} messages left this hour`}
              </div>
            </div>
            {configured && <Badge className="bg-primary/10 text-primary hover:bg-primary/10 hidden sm:inline-flex">Read-only</Badge>}
          </div>

          {body}

          {configured && (
            <div className="border-t border-border px-3 sm:px-4 py-3">
              <div className="flex items-end gap-2">
                <Textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
                  }}
                  rows={1}
                  maxLength={MAX_MESSAGE_CHARS}
                  placeholder="Ask WavyGo AI…"
                  className="min-h-[42px] max-h-40 resize-none text-[13.5px]"
                  disabled={convLoading}
                  data-testid="ai-input"
                />
                {busy ? (
                  <Button variant="outline" onClick={stop} className="h-[42px] shrink-0 gap-1.5" data-testid="ai-stop">
                    <Square className="h-3.5 w-3.5 fill-current" /> <span className="hidden sm:inline">Stop</span>
                  </Button>
                ) : (
                  <Button onClick={() => send()} disabled={!input.trim() || convLoading} className="h-[42px] shrink-0" aria-label="Send" data-testid="ai-send">
                    <SendHorizontal className="h-4 w-4" />
                  </Button>
                )}
              </div>
              <div className="mt-1.5 flex justify-between gap-3 text-[11px] text-muted-foreground">
                <span>AI can make mistakes — check important figures in the module.</span>
                {input.length > MAX_MESSAGE_CHARS - 500 && <span className="shrink-0">{input.length}/{MAX_MESSAGE_CHARS}</span>}
              </div>
            </div>
          )}
        </Card>
      </div>

      <Sheet open={listOpen} onOpenChange={setListOpen}>
        <SheetContent side="left" className="w-[300px] sm:w-[320px] p-4 flex flex-col">
          <SheetHeader className="mb-3">
            <SheetTitle className="font-display">Chats</SheetTitle>
            <SheetDescription>Your WavyGo AI conversations are private to you.</SheetDescription>
          </SheetHeader>
          <div className="flex-1 min-h-0">{list}</div>
        </SheetContent>
      </Sheet>

      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              “{deleteTarget?.title}” and all its messages will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90" data-testid="ai-confirm-delete">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
