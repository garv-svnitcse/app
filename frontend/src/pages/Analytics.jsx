import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Lock } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/module/ModulePrimitives";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePermission } from "@/hooks/usePermission";
import FilterBar, { DEFAULT_DAYS, parseDays, presetRange, todayIST } from "@/components/analytics/FilterBar";
import MarketplaceTab from "@/components/analytics/MarketplaceTab";
import OperationsTab from "@/components/analytics/OperationsTab";
import { ErrorPanel, useAnalyticsData } from "@/components/analytics/shared";

export default function Analytics() {
  const { can } = usePermission();
  const meta = useAnalyticsData("/analytics/meta", null, can("analytics.view"));
  const m = meta.data;

  const [searchParams, setSearchParams] = useSearchParams();
  const days = parseDays(searchParams.get("days"));
  const setDays = useCallback((d) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (d === DEFAULT_DAYS) next.delete("days"); else next.set("days", String(d));
      return next;
    }, { replace: true });
  }, [setSearchParams]);
  const [city, setCity] = useState("");
  const [department, setDepartment] = useState("");
  const [tab, setTab] = useState(null);
  const [nonce, setNonce] = useState(0);

  // IST "today" re-checked every minute, so the range (and its label) rolls over at midnight.
  const [today, setToday] = useState(todayIST);
  useEffect(() => {
    const t = setInterval(() => setToday(todayIST()), 60000);
    return () => clearInterval(t);
  }, []);
  const range = useMemo(() => presetRange(days, today), [days, today]);

  useEffect(() => {
    if (m && !tab) setTab(m.marketplace ? "marketplace" : "operations");
  }, [m, tab]);

  if (!can("analytics.view")) {
    return (
      <div>
        <PageHeader eyebrow="Module" title="Analytics" />
        <EmptyState icon={Lock} title="Analytics is not available for your role" description="Ask a Founder, Admin or Manager for the numbers you need." />
      </div>
    );
  }

  const canExport = !!m?.can_export;
  const active = tab || (m?.marketplace ? "marketplace" : "operations");

  return (
    <div data-testid="analytics-page">
      <PageHeader
        eyebrow="Insights"
        title="Analytics"
        description={m?.marketplace
          ? "Cohorts, retention, city drill-downs and team operations from live WavyGo data. All dates in IST."
          : "Task throughput, pipeline, attendance and calendar load from live WavyGo data. All dates in IST."}
      />

      {meta.loading && !m && (
        <div className="space-y-4">
          <Skeleton className="h-[52px] rounded-xl" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[112px] rounded-xl" />)}
          </div>
        </div>
      )}
      {meta.error && !m && <Card className="border-border"><ErrorPanel error={meta.error} onRetry={meta.reload} /></Card>}

      {m && (
        <Tabs value={active} onValueChange={setTab} className="space-y-4">
          <div className="flex flex-col gap-3">
            {m.marketplace && (
              <TabsList className="w-full sm:w-auto self-start">
                <TabsTrigger value="marketplace" className="flex-1 sm:flex-none" data-testid="analytics-tab-marketplace">Marketplace</TabsTrigger>
                <TabsTrigger value="operations" className="flex-1 sm:flex-none" data-testid="analytics-tab-operations">Operations</TabsTrigger>
              </TabsList>
            )}
            <FilterBar
              days={days} range={range} onDays={setDays}
              showCity={active === "marketplace"} cities={m.cities} city={city} onCity={setCity}
              showDepartment={active === "operations"} departments={m.departments}
              department={m.department_locked || department} onDepartment={setDepartment}
              departmentLocked={m.department_locked}
              onRefresh={() => setNonce((n) => n + 1)}
            />
          </div>

          {m.marketplace && (
            <TabsContent value="marketplace" className="mt-0">
              <MarketplaceTab key={`mk-${nonce}`} range={range} city={city} canExport={canExport} />
            </TabsContent>
          )}
          <TabsContent value="operations" className="mt-0">
            <OperationsTab key={`ops-${nonce}`} range={range} department={m.department_locked ? "" : department} canExport={canExport} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
