import { cn } from "@/lib/utils";

export const CHANNEL_LABELS = {
  social: "Social", search: "Search", email: "Email", sms: "SMS", whatsapp: "WhatsApp", push: "Push",
  referral: "Referral", influencer: "Influencer", partnership: "Partnership", offline: "Offline",
};
export const OBJECTIVE_LABELS = {
  awareness: "Awareness", acquisition: "Acquisition", activation: "Activation",
  retention: "Retention", reactivation: "Reactivation", referral: "Referral",
};
export const STATUS_META = {
  draft: { label: "Draft", cls: "bg-muted text-foreground/70" },
  scheduled: { label: "Scheduled", cls: "bg-info/10 text-info" },
  active: { label: "Active", cls: "bg-success/10 text-success" },
  paused: { label: "Paused", cls: "bg-warning/10 text-warning" },
  completed: { label: "Completed", cls: "bg-muted text-muted-foreground" },
};
export const STATUS_KEYS = Object.keys(STATUS_META);

export function CampaignStatus({ status, className }) {
  const m = STATUS_META[status] || STATUS_META.draft;
  return (
    <span className={cn("inline-flex items-center h-5 px-1.5 rounded text-[10.5px] font-semibold uppercase tracking-wide whitespace-nowrap", m.cls, className)}>
      {m.label}
    </span>
  );
}

export function roiText(roi) {
  if (roi === null || roi === undefined) return "—";
  return `${roi > 0 ? "+" : ""}${roi}%`;
}

export function channelList(channels) {
  return (channels || []).map((c) => CHANNEL_LABELS[c] || c).join(", ");
}
