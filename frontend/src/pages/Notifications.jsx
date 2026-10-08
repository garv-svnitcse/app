import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  CheckCheck,
  Info,
  AlertTriangle,
  XCircle,
  CheckCircle2,
  Bell,
} from "lucide-react";
import { useLiveRefresh } from "@/hooks/useLiveRefresh";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { useNavigate } from "react-router-dom";

const KIND_META = {
  info: {
    icon: Info,
    class: "text-info bg-info/10",
  },
  success: {
    icon: CheckCircle2,
    class: "text-success bg-success/10",
  },
  warning: {
    icon: AlertTriangle,
    class: "text-warning bg-warning/10",
  },
  error: {
    icon: XCircle,
    class: "text-destructive bg-destructive/10",
  },
};

// Lets the TopNav bell refresh its unread badge
function notifyChanged() {
  window.dispatchEvent(new Event("wavygo:notifications-changed"));
}

export default function NotificationsPage() {
  const [items, setItems] = useState([]);
  const navigate = useNavigate();

  async function load({ background = false } = {}) {
    try {
      const { data } = await api.get("/notifications");
      setItems(data);
    } catch (error) {
      if (!background) toast.error(`Could not load notifications: ${formatApiError(error)}`);
    }
  }

  useEffect(() => {
    load();
  }, []);
  useLiveRefresh(load, 30000);

  async function markAll() {
    try {
      await api.post("/notifications/read-all");
      notifyChanged();
      await load();
    } catch (error) {
      toast.error(`Could not mark notifications as read: ${formatApiError(error)}`);
    }
  }

  async function handleNotificationClick(notification) {
    try {
      // Mark notification as read
      if (!notification.read) {
        try {
          await api.post(`/notifications/${notification.id}/read`);
          notifyChanged();
        } catch (error) {
          // Don't stop navigation if the read endpoint is unavailable
          toast.error(`Could not mark notification as read: ${formatApiError(error)}`);
        }
      }

      // Navigate using the link stored in the notification.
      // For task notifications this will be:
      // /task-board?task_id=XXXXXXXX
      if (notification.link) {
        navigate(notification.link);
        return;
      }

      // Refresh the notification list if there is no link
      await load();
    } catch (error) {
      toast.error(`Could not open notification: ${formatApiError(error)}`);
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            Inbox
          </div>

          <h1 className="font-display text-3xl font-semibold tracking-tight mt-1">
            Notifications
          </h1>
        </div>

        <Button
          variant="outline"
          onClick={markAll}
          disabled={!items.some((n) => !n.read)}
          data-testid="mark-all-read-btn"
        >
          <CheckCheck className="h-4 w-4 mr-1.5" />
          Mark all as read
        </Button>
      </div>

      {/* Notifications */}
      <Card className="border-border">
        {items.length === 0 ? (
          <div className="p-16 text-center">
            <Bell className="h-8 w-8 mx-auto text-muted-foreground" />

            <div className="mt-3 text-sm text-muted-foreground">
              No notifications yet.
            </div>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((n) => {
              const meta = KIND_META[n.kind] || KIND_META.info;
              const Icon = meta.icon;

              return (
                <li
                  key={n.id}
                  onClick={() => handleNotificationClick(n)}
                  className={cn(
                    "px-6 py-4 flex gap-3 transition-colors",
                    !n.read && "bg-primary/[0.03]",
                    n.link && "cursor-pointer hover:bg-muted/50"
                  )}
                >
                  {/* Notification icon */}
                  <div
                    className={cn(
                      "h-10 w-10 rounded-md flex items-center justify-center shrink-0",
                      meta.class
                    )}
                  >
                    <Icon className="h-4.5 w-4.5" />
                  </div>

                  {/* Notification content */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2 justify-between">
                      <div className="text-[14px] font-medium text-foreground">
                        {n.title}
                      </div>

                      {!n.read && (
                        <Badge className="bg-primary text-primary-foreground text-[10px]">
                          NEW
                        </Badge>
                      )}
                    </div>

                    <p className="text-[13px] text-muted-foreground mt-1">
                      {n.body}
                    </p>

                    <div className="text-[11px] text-muted-foreground/70 mt-2">
                      {(() => {
                        try {
                          return formatDistanceToNow(
                            new Date(n.created_at),
                            {
                              addSuffix: true,
                            }
                          );
                        } catch {
                          return "";
                        }
                      })()}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}