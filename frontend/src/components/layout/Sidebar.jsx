import { useEffect } from "react";
import { NavLink } from "react-router-dom";
import { ChevronsLeft, ChevronsRight, Circle, X } from "lucide-react";
import { visibleNavFor } from "@/constants/nav";
import { SHELL, SIDEBAR_NAV } from "@/constants/testIds";
import { WavygoLogo } from "@/components/WavygoLogo";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

function initials(name) {
  return (name || "").split(" ").map(s => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

export function Sidebar({ collapsed, onToggle, mobileOpen = false, onMobileClose }) {
  const { user } = useAuth();

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e) => { if (e.key === "Escape") onMobileClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen, onMobileClose]);

  return (
    <TooltipProvider delayDuration={150}>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 md:hidden" onClick={onMobileClose} aria-hidden="true" />
      )}
      <aside
        data-testid={SHELL.sidebar}
        className={cn(
          "fixed inset-y-0 left-0 z-50 md:z-40 flex flex-col text-sidebar-fg bg-sidebar",
          "transition-[width,transform] duration-300 md:translate-x-0",
          mobileOpen ? "translate-x-0 shadow-2xl" : "-translate-x-full",
          collapsed ? "w-[72px]" : "w-[264px]"
        )}
        style={{ backgroundColor: "hsl(var(--sidebar-bg))" }}
      >
        {/* Brand block */}
        <div className={cn("flex items-center gap-3 px-4 pt-5 pb-4 border-b border-white/5", collapsed && "justify-center px-2")}>
          {collapsed ? (
            <WavygoLogo forceVariant="white" className="h-7 w-auto" mark />
          ) : (
            <div className="flex items-center gap-3">
              <WavygoLogo forceVariant="white" className="h-8 w-auto max-w-[170px]" />
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto scrollbar-thin py-3 px-2">
          <ul className="space-y-0.5">
            {visibleNavFor(user?.role).map((item) => {
              const Icon = item.icon;
              const link = (
                <NavLink
                  to={item.to}
                  data-testid={SIDEBAR_NAV(item.key)}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-md px-3 py-2 text-[13.5px] font-medium relative",
                      "text-sidebar-fg/80 hover:text-white hover:bg-white/[0.06]",
                      "transition-colors duration-150",
                      isActive && "bg-white/10 text-white",
                      collapsed && "justify-center px-2"
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full" style={{ background: "hsl(var(--sidebar-active))" }} />
                      )}
                      <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </>
                  )}
                </NavLink>
              );
              return (
                <li key={item.key}>
                  {collapsed ? (
                    <Tooltip>
                      <TooltipTrigger asChild><div>{link}</div></TooltipTrigger>
                      <TooltipContent side="right" className="bg-slate-900 text-white border-slate-800">{item.label}</TooltipContent>
                    </Tooltip>
                  ) : link}
                </li>
              );
            })}
          </ul>
        </nav>

        {/* User block */}
        <div className={cn("border-t border-white/5 p-3", collapsed && "px-2")}>
          <div className={cn("flex items-center gap-3", collapsed && "justify-center")}>
            <div className="relative">
              <Avatar className="h-9 w-9 ring-2 ring-white/10">
                <AvatarImage src={user?.photo || undefined} alt={user?.name || "User"} />
                <AvatarFallback className="bg-wavygo-700 text-white text-xs font-semibold">{initials(user?.name)}</AvatarFallback>
              </Avatar>
              <span className={cn(
                "absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-[hsl(var(--sidebar-bg))]",
                user?.online ? "bg-emerald-400" : "bg-slate-500"
              )} />
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium leading-tight truncate text-white">{user?.name}</div>
                <div className="text-[11px] text-sidebar-muted flex items-center gap-1.5 mt-0.5">
                  <span className="inline-flex items-center gap-1">
                    <Circle className={cn("h-2 w-2", user?.online ? "fill-emerald-400 text-emerald-400" : "fill-slate-500 text-slate-500")} />
                    <span>{user?.role}</span>
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Mobile close */}
        <button
          onClick={onMobileClose}
          className="md:hidden absolute top-5 right-3 h-8 w-8 rounded-md text-sidebar-fg/80 hover:text-white hover:bg-white/10 flex items-center justify-center"
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
        </button>

        {/* Collapse toggle */}
        <button
          data-testid={SHELL.sidebarToggle}
          onClick={onToggle}
          className={cn(
            "hidden md:flex absolute top-6 -right-3 h-6 w-6 rounded-full bg-white text-slate-700 shadow-md",
            "items-center justify-center hover:bg-slate-50 transition-colors border border-slate-200"
          )}
          aria-label="Toggle sidebar"
        >
          {collapsed ? <ChevronsRight className="h-3.5 w-3.5" /> : <ChevronsLeft className="h-3.5 w-3.5" />}
        </button>
      </aside>
    </TooltipProvider>
  );
}
