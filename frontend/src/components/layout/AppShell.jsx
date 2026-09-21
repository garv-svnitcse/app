import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopNav } from "@/components/layout/TopNav";
import { useSessionTimeout } from "@/hooks/useSessionTimeout";
import { cn } from "@/lib/utils";

export function AppShell({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  useSessionTimeout();
  return (
    <div className="min-h-screen bg-background">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
      <div className={cn("transition-[padding] duration-300", collapsed ? "pl-[72px]" : "pl-[264px]")}>
        <TopNav />
        <main className="px-6 md:px-8 py-6 md:py-8 max-w-[1600px] mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}

export default AppShell;
