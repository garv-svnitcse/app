import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { LIFECYCLE } from "./crmShared";

export function ErrorBlock({ title = "Couldn't load this", error, onRetry, testid }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-10 text-center" data-testid={testid}>
      <AlertTriangle className="h-6 w-6 text-destructive mx-auto" />
      <div className="font-display text-[15px] font-semibold mt-3">{title}</div>
      {error && <div className="text-[13px] text-muted-foreground mt-1">{error}</div>}
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4 gap-1.5" onClick={() => onRetry()}>
          <RefreshCw className="h-3.5 w-3.5" /> Try again
        </Button>
      )}
    </div>
  );
}

export function StatSkeletons({ count = 4 }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {Array.from({ length: count }, (_, i) => <Skeleton key={i} className="h-[108px] rounded-xl" />)}
    </div>
  );
}

export function RowSkeletons({ rows = 6, className }) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-4 space-y-3", className)}>
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)}
    </div>
  );
}

export function LifecyclePill({ stage, className }) {
  const meta = LIFECYCLE[stage] || LIFECYCLE.lead;
  return (
    <span className={cn("inline-flex items-center h-5 px-1.5 rounded text-[10.5px] font-semibold uppercase tracking-wide whitespace-nowrap", meta.cls, className)}>
      {meta.label}
    </span>
  );
}
