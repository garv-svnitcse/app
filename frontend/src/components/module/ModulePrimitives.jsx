import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function PageHeader({ eyebrow, title, description, actions, badge }) {
  return (
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-6">
      <div className="min-w-0">
        {eyebrow && <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{eyebrow}</div>}
        <div className="flex items-center gap-2 mt-1">
          <h1 className="font-display text-3xl md:text-[32px] font-semibold tracking-tighter text-foreground truncate">{title}</h1>
          {badge && <Badge className="bg-primary/10 text-primary hover:bg-primary/10">{badge}</Badge>}
        </div>
        {description && <p className="text-sm text-muted-foreground mt-2 max-w-2xl">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, sub, icon: Icon, tone = "default" }) {
  const tones = {
    default: "text-primary bg-primary/10",
    success: "text-success bg-success/10",
    warning: "text-warning bg-warning/10",
    info: "text-info bg-info/10",
    danger: "text-destructive bg-destructive/10",
  };
  return (
    <div className="rounded-xl border border-border bg-card p-4 hover-lift">
      <div className="flex items-start justify-between">
        {Icon && (
          <div className={cn("h-9 w-9 rounded-md flex items-center justify-center", tones[tone])}>
            <Icon className="h-4.5 w-4.5" strokeWidth={2} />
          </div>
        )}
        {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
      </div>
      <div className="mt-3">
        <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
        <div className="font-display text-[22px] font-semibold text-foreground mt-1 tracking-tight">{value}</div>
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="p-16 text-center border border-dashed border-border rounded-xl bg-card/30">
      {Icon && (
        <div className="h-12 w-12 rounded-md bg-primary/10 text-primary flex items-center justify-center mx-auto">
          <Icon className="h-5 w-5" />
        </div>
      )}
      <div className="font-display text-[15px] font-semibold text-foreground mt-3">{title}</div>
      {description && <div className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">{description}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

const STATUS_CLASSES = {
  approved: "bg-success/10 text-success",
  active: "bg-success/10 text-success",
  available: "bg-success/10 text-success",
  completed: "bg-success/10 text-success",
  won: "bg-success/10 text-success",
  resolved: "bg-success/10 text-success",
  present: "bg-success/10 text-success",
  pending: "bg-warning/10 text-warning",
  in_progress: "bg-info/10 text-info",
  confirmed: "bg-info/10 text-info",
  review: "bg-info/10 text-info",
  open: "bg-info/10 text-info",
  assigned: "bg-info/10 text-info",
  todo: "bg-muted text-foreground/70",
  planned: "bg-muted text-foreground/70",
  maintenance: "bg-warning/10 text-warning",
  paused: "bg-warning/10 text-warning",
  rejected: "bg-destructive/10 text-destructive",
  cancelled: "bg-destructive/10 text-destructive",
  lost: "bg-destructive/10 text-destructive",
  closed: "bg-muted text-muted-foreground",
  urgent: "bg-destructive/10 text-destructive",
  high: "bg-destructive/10 text-destructive",
  medium: "bg-warning/10 text-warning",
  low: "bg-info/10 text-info",
  deactivated: "bg-destructive/10 text-destructive",
  inactive: "bg-destructive/10 text-destructive",
};

export function StatusPill({ status, className }) {
  const s = (status || "").toLowerCase();
  return (
    <span className={cn(
      "inline-flex items-center h-5 px-1.5 rounded text-[10.5px] font-semibold uppercase tracking-wide",
      STATUS_CLASSES[s] || "bg-muted text-foreground/70",
      className,
    )}>
      {(status || "").replace(/_/g, " ")}
    </span>
  );
}
