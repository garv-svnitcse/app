import { useNavigate } from "react-router-dom";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Bike, Handshake, ClipboardList, Target, Users, Megaphone, CalendarDays, Archive } from "lucide-react";

const OPTIONS = [
  { label: "New Booking",     desc: "Reserve a vehicle for a customer.",  icon: Bike,          to: "/marketplace?tab=bookings&create=booking" },
  { label: "New Vendor",      desc: "Onboard a fleet partner.",           icon: Handshake,     to: "/marketplace?tab=vendors&create=vendor" },
  { label: "New Task",        desc: "Assign work to your team.",          icon: ClipboardList, to: "/task-board?create=task" },
  { label: "New Opportunity", desc: "Track a partnership or deal.",       icon: Target,        to: "/opportunity-hub?create=opportunity" },
  { label: "Invite Teammate", desc: "Add a user with a role.",            icon: Users,         to: "/employees?create=invite" },
  { label: "New Campaign",    desc: "Launch a marketing campaign.",       icon: Megaphone,     to: "/marketing?create=campaign" },
  { label: "New Event",       desc: "Schedule on the company calendar.",  icon: CalendarDays,  to: "/calendar?create=event" },
  { label: "Upload Document", desc: "Save to the Company Vault.",         icon: Archive,       to: "/company-vault?create=document" },
];

export function QuickCreateDialog({ open, onOpenChange }) {
  const navigate = useNavigate();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">Quick Create</DialogTitle>
          <DialogDescription>Jump straight into creating something new.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
          {OPTIONS.map((o) => {
            const Icon = o.icon;
            return (
              <button
                key={o.label}
                onClick={() => { onOpenChange(false); navigate(o.to); }}
                className="group text-left p-3 rounded-lg border border-border bg-card hover:border-primary/40 hover:bg-primary/[0.03] transition-colors"
              >
                <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center mb-2.5">
                  <Icon className="h-4.5 w-4.5" strokeWidth={2} />
                </div>
                <div className="text-[13px] font-semibold text-foreground">{o.label}</div>
                <div className="text-[11.5px] text-muted-foreground mt-0.5 leading-snug">{o.desc}</div>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
