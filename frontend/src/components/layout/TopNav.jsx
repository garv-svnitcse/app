import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Plus, Bell, Sun, Moon, LogOut, Menu, User as UserIcon, Settings as SettingsIcon } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useLoggedTime } from "@/hooks/useLoggedTime";
import { useTheme } from "@/contexts/ThemeContext";
import { SHELL } from "@/constants/testIds";
import { api } from "@/lib/api";
import { visibleNavFor } from "@/constants/nav";
import { usePermission } from "@/hooks/usePermission";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from "@/components/ui/command";
import { DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { NotificationDrawer } from "@/components/layout/NotificationDrawer";
import { QuickCreateDialog, quickCreateOptionsFor } from "@/components/layout/QuickCreateDialog";

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  if (h < 21) return "Good evening";
  return "Working late";
}

function initials(name) {
  return (name || "").split(" ").map(s => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

export function TopNav({ onOpenMenu }) {
  const { user, logout } = useAuth();
  const { can, canViewModule } = usePermission();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const loggedTime = useLoggedTime();
  const [searchOpen, setSearchOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const { data } = await api.get("/notifications/unread-count");
        if (mounted) setUnread(data.count);
      } catch { /* noop */ }
    }
    load();
    const t = setInterval(load, 30000);
    // Pages that mark notifications read announce it, so the badge updates immediately.
    window.addEventListener("wavygo:notifications-changed", load);
    return () => {
      mounted = false;
      clearInterval(t);
      window.removeEventListener("wavygo:notifications-changed", load);
    };
  }, [notifOpen]);

  useEffect(() => {
    function onKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearchOpen(v => !v); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const first = (user?.name || "").split(" ")[0];

  return (
    <header
      data-testid={SHELL.topnav}
      className="sticky top-0 z-30 h-16 border-b border-border bg-background/85 backdrop-blur-xl"
    >
      <div className="h-full px-3 sm:px-6 flex items-center gap-2 sm:gap-4">
        <button
          onClick={onOpenMenu}
          className="md:hidden h-9 w-9 rounded-md border border-border bg-card flex items-center justify-center text-muted-foreground hover:text-foreground"
          aria-label="Open menu"
          data-testid="shell-mobile-menu"
        >
          <Menu className="h-4 w-4" />
        </button>

        {/* Greeting */}
        <div className="hidden md:flex flex-col leading-tight" data-testid={SHELL.greeting}>
          <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}</span>
          <span className="font-display text-[15px] font-semibold text-foreground">
            {greeting()}, {first} <span className="text-muted-foreground font-normal">·</span> <span className="text-primary">WavyGo OS</span>
          </span>
        </div>

        {loggedTime && (
          <div className="hidden sm:flex items-center gap-1.5 text-[12px] text-muted-foreground font-mono tabular-nums">
            <span>⏱</span>
            <span>{loggedTime.formatted}</span>
          </div>
        )}

        <div className="flex-1" />

        {/* Search */}
        <button
          data-testid={SHELL.globalSearchTrigger}
          onClick={() => setSearchOpen(true)}
          className={cn(
            "group inline-flex items-center gap-2 h-9 px-3 rounded-md border border-border bg-card",
            "text-sm text-muted-foreground hover:text-foreground hover:border-foreground/20 transition-colors",
            "sm:min-w-[220px]"
          )}
          aria-label="Jump to"
        >
          <Search className="h-4 w-4" />
          <span className="flex-1 text-left hidden sm:inline">Jump to…</span>
          <kbd className="hidden sm:inline text-[10px] tracking-widest text-muted-foreground/70 border border-border rounded px-1.5 py-0.5">⌘K</kbd>
        </button>

        {/* Quick create — only for roles that can create something */}
        {quickCreateOptionsFor(can, canViewModule).length > 0 && (
          <button
            data-testid={SHELL.quickCreate}
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-2 h-9 px-3 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-95 active:scale-[0.98] transition-transform"
          >
            <Plus className="h-4 w-4" />
            <span className="hidden sm:inline">Create</span>
          </button>
        )}

        {/* Theme */}
        <button
          data-testid={SHELL.themeToggle}
          onClick={toggle}
          className="h-9 w-9 rounded-md border border-border bg-card flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        {/* Notifications */}
        <button
          data-testid={SHELL.notificationBell}
          onClick={() => setNotifOpen(true)}
          className="relative h-9 w-9 rounded-md border border-border bg-card flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          {unread > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-destructive text-destructive-foreground text-[10px] font-semibold flex items-center justify-center">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>

        {/* User menu */}
        <DropdownMenu>
          <DropdownMenuTrigger data-testid={SHELL.userMenu} asChild>
            <button className="h-9 w-9 rounded-full ring-1 ring-border hover:ring-primary/40 transition-all">
              <Avatar className="h-9 w-9">
                <AvatarImage src={user?.photo || undefined} />
                <AvatarFallback className="bg-wavygo-100 text-wavygo-800 text-xs font-semibold">{initials(user?.name)}</AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="pb-2">
              <div className="text-[13px] font-semibold">{user?.name}</div>
              <div className="text-[11px] text-muted-foreground font-normal">{user?.email}</div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => navigate("/settings")}><UserIcon className="mr-2 h-4 w-4" />Profile</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => navigate("/settings")}><SettingsIcon className="mr-2 h-4 w-4" />Settings</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem data-testid="logout-button" onSelect={logout} className="text-destructive focus:text-destructive">
              <LogOut className="mr-2 h-4 w-4" />Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Global command palette */}
      <CommandDialog open={searchOpen} onOpenChange={setSearchOpen}>
        <DialogTitle className="sr-only">Jump to</DialogTitle>
        <DialogDescription className="sr-only">Search modules and create shortcuts</DialogDescription>
        <CommandInput data-testid={SHELL.globalSearch} placeholder="Jump to a module or create something…" />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          <CommandGroup heading="Modules">
            {visibleNavFor(user?.role).map(item => {
              const Icon = item.icon;
              return (
                <CommandItem key={item.key} onSelect={() => { setSearchOpen(false); navigate(item.to); }}>
                  <Icon className="mr-2 h-4 w-4" />
                  <span>{item.label}</span>
                </CommandItem>
              );
            })}
          </CommandGroup>
          <CommandGroup heading="Create">
            {quickCreateOptionsFor(can, canViewModule).map((o) => {
              const Icon = o.icon;
              return (
                <CommandItem key={o.label} onSelect={() => { setSearchOpen(false); navigate(o.to); }}>
                  <Icon className="mr-2 h-4 w-4" />
                  <span>{o.label}</span>
                </CommandItem>
              );
            })}
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      <NotificationDrawer open={notifOpen} onOpenChange={setNotifOpen} />
      <QuickCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </header>
  );
}
