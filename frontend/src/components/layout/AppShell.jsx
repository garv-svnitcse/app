import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopNav } from "@/components/layout/TopNav";
import { cn } from "@/lib/utils";

const DESKTOP_QUERY = "(min-width: 768px)";

function useIsDesktop() {
  const [matches, setMatches] = useState(() => typeof window === "undefined" || window.matchMedia(DESKTOP_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_QUERY);
    const onChange = (e) => setMatches(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return matches;
}

// Desktop: fixed sidebar that can collapse to icons. Below md: the same sidebar as an off-canvas drawer.
export function AppShell({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isDesktop = useIsDesktop();
  const { pathname } = useLocation();

  useEffect(() => { setMobileOpen(false); }, [pathname]);
  useEffect(() => { if (isDesktop) setMobileOpen(false); }, [isDesktop]);

  return (
    <div className="min-h-screen bg-background">
      <Sidebar
        collapsed={isDesktop && collapsed}
        onToggle={() => setCollapsed((v) => !v)}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
      />
      <div className={cn("transition-[padding] duration-300", collapsed ? "md:pl-[72px]" : "md:pl-[264px]")}>
        <TopNav onOpenMenu={() => setMobileOpen(true)} />
        <main className="px-4 sm:px-6 md:px-8 py-6 md:py-8 max-w-[1600px] mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}

export default AppShell;
