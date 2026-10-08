import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { MessageSquare, MoreHorizontal, Pencil, Plus, Search, Trash2, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

function ago(iso) {
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }); } catch { return ""; }
}

/** Sidebar list of the user's own AI conversations with inline rename and delete. */
export function ConversationList({ conversations, loading, activeId, onSelect, onNew, onRename, onDelete, disabled }) {
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");

  const term = q.trim().toLowerCase();
  const list = term ? conversations.filter((c) => (c.title || "").toLowerCase().includes(term)) : conversations;

  const startEdit = (c) => { setEditing(c.id); setDraft(c.title || ""); };
  const commit = async () => {
    const title = draft.trim();
    const id = editing;
    setEditing(null);
    if (title && id) await onRename(id, title);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <Button onClick={onNew} disabled={disabled} className="w-full gap-1.5 font-medium" data-testid="ai-new-chat">
        <Plus className="h-4 w-4" /> New chat
      </Button>
      <div className="relative mt-3">
        <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="Search chats…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 pl-8 text-[13px]" data-testid="ai-search-chats" />
      </div>
      <div className="text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground px-2 mt-4 mb-1.5">Recent chats</div>
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin -mx-1 px-1">
        {loading ? (
          <div className="space-y-2 px-1">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : list.length === 0 ? (
          <div className="text-center text-[12.5px] text-muted-foreground py-8">{term ? "No chats match." : "No conversations yet."}</div>
        ) : (
          <ul className="space-y-0.5" data-testid="ai-conversation-list">
            {list.map((c) => {
              const active = c.id === activeId;
              if (editing === c.id) {
                return (
                  <li key={c.id} className="flex items-center gap-1 px-1 py-1">
                    <Input
                      autoFocus value={draft} maxLength={120} onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(null); }}
                      className="h-8 text-[13px]" aria-label="Conversation title" data-testid="ai-rename-input"
                    />
                    <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0" onClick={commit} aria-label="Save title"><Check className="h-4 w-4" /></Button>
                    <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0" onClick={() => setEditing(null)} aria-label="Cancel rename"><X className="h-4 w-4" /></Button>
                  </li>
                );
              }
              return (
                <li key={c.id} className={cn("group flex items-center rounded-md transition-colors", active ? "bg-primary/10" : "hover:bg-muted")}>
                  <button onClick={() => onSelect(c.id)} className="flex-1 min-w-0 flex items-center gap-2 px-2 py-1.5 text-left" data-testid="ai-conversation-item">
                    <MessageSquare className={cn("h-3.5 w-3.5 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
                    <span className="min-w-0">
                      <span className={cn("block truncate text-[13px]", active ? "font-medium text-foreground" : "text-foreground/85")}>{c.title}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">{ago(c.updated_at)}</span>
                    </span>
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="icon" variant="ghost" className="h-7 w-7 mr-1 shrink-0 opacity-70 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100" aria-label="Conversation actions">
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => startEdit(c)}><Pencil className="h-3.5 w-3.5 mr-2" /> Rename</DropdownMenuItem>
                      <DropdownMenuItem onClick={() => onDelete(c)} className="text-destructive focus:text-destructive"><Trash2 className="h-3.5 w-3.5 mr-2" /> Delete</DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

export default ConversationList;
