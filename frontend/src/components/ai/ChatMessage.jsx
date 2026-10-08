import { useState } from "react";
import { AlertTriangle, Check, CircleSlash, Copy, Loader2, RotateCcw, Sparkles, Wrench } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Markdown } from "@/components/ai/Markdown";
import { TOOL_LABELS } from "@/components/ai/aiConfig";
import { cn } from "@/lib/utils";

function initials(name) {
  return (name || "?").split(" ").map((s) => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

/** Chips for the data sources the assistant read, deduplicated by tool name. */
export function ToolChips({ calls }) {
  if (!calls?.length) return null;
  const seen = new Map();
  for (const c of calls) {
    const prev = seen.get(c.name);
    // Keep the latest call per tool, but a still-running one stays visible as running.
    if (!prev || prev.status !== "running" || c.status === "running") seen.set(c.name, c);
  }
  return (
    <div className="flex flex-wrap gap-1.5 mb-2" data-testid="ai-tool-chips">
      {[...seen.values()].map((c) => {
        const running = c.status === "running";
        const failed = c.status === "error" || c.ok === false;
        return (
          <span
            key={c.name}
            title={c.summary || undefined}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
              failed ? "border-warning/40 bg-warning/10 text-warning" : "border-border bg-muted/60 text-muted-foreground"
            )}
          >
            {running ? <Loader2 className="h-3 w-3 animate-spin" /> : failed ? <CircleSlash className="h-3 w-3" /> : <Wrench className="h-3 w-3" />}
            {TOOL_LABELS[c.name] || c.name}
            {c.summary && !running && <span className="opacity-70">· {c.summary}</span>}
          </span>
        );
      })}
    </div>
  );
}

function AssistantAvatar() {
  return (
    <div className="h-7 w-7 shrink-0 rounded-md bg-primary/10 text-primary flex items-center justify-center">
      <Sparkles className="h-3.5 w-3.5" />
    </div>
  );
}

export function UserBubble({ message, user }) {
  return (
    <div className="flex gap-2.5 flex-row-reverse" data-testid="ai-user-message">
      <Avatar className="h-7 w-7 shrink-0">
        <AvatarImage src={user?.photo || undefined} />
        <AvatarFallback className="text-[9px] bg-wavygo-100 text-wavygo-800">{initials(user?.name)}</AvatarFallback>
      </Avatar>
      <div className="max-w-[85%] sm:max-w-[75%] rounded-lg bg-primary text-primary-foreground px-3 py-2 text-[13.5px] leading-relaxed whitespace-pre-wrap break-words">
        {message.content}
      </div>
    </div>
  );
}

/**
 * One assistant reply. `pending` is true while it streams (text may be empty while tools run).
 * `onRetry` is only passed for the latest reply.
 */
export function AssistantMessage({ message, pending = false, onRetry }) {
  const [copied, setCopied] = useState(false);
  const text = message.content || "";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy to clipboard");
    }
  };
  const waiting = pending && !text;
  return (
    <div className="flex gap-2.5" data-testid="ai-assistant-message">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 max-w-[92%] sm:max-w-[85%]">
        <ToolChips calls={message.tool_calls} />
        {waiting ? (
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground py-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {message.tool_calls?.some((c) => c.status === "running") ? "Looking up company data…" : "Thinking…"}
          </div>
        ) : text ? (
          <div className="rounded-lg bg-muted/50 border border-border px-3.5 py-2.5">
            <Markdown text={text} />
            {pending && <span className="inline-block w-1.5 h-4 align-middle bg-primary/70 animate-pulse ml-0.5" aria-hidden />}
          </div>
        ) : null}
        {message.stopped && !pending && (
          <div className="mt-1.5 text-[11.5px] text-muted-foreground flex items-center gap-1"><CircleSlash className="h-3 w-3" /> Stopped</div>
        )}
        {message.error && !pending && (
          <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[12.5px] text-destructive flex items-start gap-2" data-testid="ai-error">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>{message.error}</span>
          </div>
        )}
        {!pending && (text || onRetry) && (
          <div className="mt-1 flex items-center gap-0.5">
            {text && (
              <Button variant="ghost" size="sm" className="h-7 px-2 text-[11.5px] text-muted-foreground" onClick={copy} data-testid="ai-copy">
                {copied ? <Check className="h-3.5 w-3.5 mr-1" /> : <Copy className="h-3.5 w-3.5 mr-1" />} {copied ? "Copied" : "Copy"}
              </Button>
            )}
            {onRetry && (
              <Button variant="ghost" size="sm" className="h-7 px-2 text-[11.5px] text-muted-foreground" onClick={onRetry} data-testid="ai-retry">
                <RotateCcw className="h-3.5 w-3.5 mr-1" /> Retry
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
