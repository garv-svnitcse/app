import { useSearchParams } from "react-router-dom";
import { Lock } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/module/ModulePrimitives";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { usePermission } from "@/hooks/usePermission";
import FinanceOverview from "@/components/finance/FinanceOverview";
import InvoicesTab from "@/components/finance/InvoicesTab";
import PayoutsTab from "@/components/finance/PayoutsTab";
import StatementsTab from "@/components/finance/StatementsTab";
import VendorsTab from "@/components/finance/VendorsTab";
import BillsTab from "@/components/finance/BillsTab";
import FinanceSettingsTab from "@/components/finance/FinanceSettingsTab";

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "invoices", label: "Invoices" },
  { value: "payouts", label: "Payouts" },
  { value: "vendors", label: "Vendors" },
  { value: "bills", label: "Bills" },
  { value: "statements", label: "Statements" },
  { value: "settings", label: "Settings" },
];

export default function Finance() {
  const { can } = usePermission();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.value === params.get("tab")) ? params.get("tab") : "overview";
  // `vendor` is per-tab state (bills filter / open vendor panel), so switching tabs clears it.
  const setTab = (v) => setParams((p) => { p.set("tab", v); p.delete("vendor"); return p; }, { replace: true });
  const canManage = can("finance.manage");
  const viewVendorBills = (vendorId) => setParams((p) => { p.set("tab", "bills"); p.set("vendor", vendorId); return p; }, { replace: true });
  const openVendor = (vendorId) => setParams((p) => { p.set("tab", "vendors"); p.set("vendor", vendorId); return p; });

  if (!can("finance.view")) {
    return (
      <div data-testid="finance-page">
        <PageHeader eyebrow="Module" title="Finance" />
        <EmptyState icon={Lock} title="Finance is restricted" description="Only the Founder can view invoices, payouts, vendors and statements." />
      </div>
    );
  }

  return (
    <div data-testid="finance-page">
      <PageHeader
        eyebrow="Module"
        title="Finance"
        description="Customer invoices, vendor payouts, vendor bills and monthly statements — computed from live marketplace bookings."
        badge="Live"
      />
      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList className="flex flex-wrap h-auto gap-1 justify-start">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} data-testid={`finance-tab-${t.value}`}>{t.label}</TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="overview" className="mt-6"><FinanceOverview onNavigate={setTab} onOpenVendor={openVendor} /></TabsContent>
        <TabsContent value="invoices" className="mt-6"><InvoicesTab canManage={canManage} /></TabsContent>
        <TabsContent value="payouts" className="mt-6"><PayoutsTab canManage={canManage} /></TabsContent>
        <TabsContent value="vendors" className="mt-6"><VendorsTab canManage={canManage} onViewBills={viewVendorBills} /></TabsContent>
        <TabsContent value="bills" className="mt-6"><BillsTab canManage={canManage} /></TabsContent>
        <TabsContent value="statements" className="mt-6"><StatementsTab onOpenVendor={openVendor} /></TabsContent>
        <TabsContent value="settings" className="mt-6"><FinanceSettingsTab canManage={canManage} /></TabsContent>
      </Tabs>
    </div>
  );
}
