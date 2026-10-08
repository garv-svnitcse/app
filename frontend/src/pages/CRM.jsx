import { useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/module/ModulePrimitives";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePermission } from "@/hooks/usePermission";
import { useResource } from "@/components/crm/crmShared";
import CrmOverview from "@/components/crm/CrmOverview";
import CustomerList, { EMPTY_FILTERS } from "@/components/crm/CustomerList";
import Customer360Sheet from "@/components/crm/Customer360Sheet";
import SegmentsPanel from "@/components/crm/SegmentsPanel";
import SegmentDialog from "@/components/crm/SegmentDialog";
import FollowupsPanel from "@/components/crm/FollowupsPanel";
import CustomerDialog from "@/components/crm/CustomerDialog";

const TABS = ["overview", "customers", "segments", "followups"];

export default function CRM() {
  const { can } = usePermission();
  const canEdit = can("crm.edit");
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = TABS.includes(searchParams.get("tab")) ? searchParams.get("tab") : "overview";
  const customerId = searchParams.get("customer");

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [segDialog, setSegDialog] = useState({ open: false, segment: null, initial: null });
  const [followupsKey, setFollowupsKey] = useState(0);
  const [customersKey, setCustomersKey] = useState(0);
  const [overviewKey, setOverviewKey] = useState(0);
  const [addOpen, setAddOpen] = useState(false);

  const meta = useResource("/crm/meta");
  const segments = useResource("/crm/segments");

  const setTab = useCallback((t) => setSearchParams((p) => {
    if (t === "overview") p.delete("tab"); else p.set("tab", t);
    return p;
  }), [setSearchParams]);

  // ?customer=<id> (from notifications or links) opens the customer 360 sheet.
  const openCustomer = useCallback((id) => setSearchParams((p) => { p.set("customer", id); return p; }), [setSearchParams]);
  const closeCustomer = useCallback(() => setSearchParams((p) => { p.delete("customer"); return p; }), [setSearchParams]);

  const showCustomers = (patch) => {
    setFilters({ ...EMPTY_FILTERS, ...patch });
    setTab("customers");
  };

  // Tags and follow-ups edited in the sheet feed the filters and the follow-ups tab.
  const onCustomerChanged = () => {
    meta.reload({ background: true });
    segments.reload({ background: true });
    setFollowupsKey((k) => k + 1);
    setCustomersKey((k) => k + 1);
    setOverviewKey((k) => k + 1);
  };

  const onCustomerAdded = (c) => {
    onCustomerChanged();
    openCustomer(c.id);
  };

  const onCustomerDeleted = () => {
    closeCustomer();
    onCustomerChanged();
  };

  const headerAction = !canEdit ? null
    : tab === "segments" ? (segments.data?.length > 0 && (
      <Button onClick={() => setSegDialog({ open: true, segment: null, initial: null })} className="gap-1.5 font-medium">
        <Plus className="h-4 w-4" /> New segment
      </Button>
    ))
    : tab === "followups" ? null
    : (
      <Button onClick={() => setAddOpen(true)} className="gap-1.5 font-medium" data-testid="crm-add-customer">
        <Plus className="h-4 w-4" /> Add customer
      </Button>
    );

  return (
    <div data-testid="crm-page">
      <PageHeader
        eyebrow="Customers"
        title="CRM"
        description="Customer 360 built from live marketplace bookings, tickets, KYC and reviews — plus the team's notes and follow-ups."
        actions={headerAction}
      />

      <Tabs value={tab} onValueChange={setTab}>
        <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 mb-5">
          <TabsList className="bg-muted/60 p-1">
            <TabsTrigger value="overview" data-testid="crm-tab-overview">Overview</TabsTrigger>
            <TabsTrigger value="customers" data-testid="crm-tab-customers">Customers</TabsTrigger>
            <TabsTrigger value="segments" data-testid="crm-tab-segments">Segments</TabsTrigger>
            <TabsTrigger value="followups" data-testid="crm-tab-followups-list">Follow-ups</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="overview" className="mt-0">
          <CrmOverview refreshKey={overviewKey} onAddCustomer={canEdit ? () => setAddOpen(true) : undefined} onOpenCustomer={openCustomer} onPickStage={(stage) => showCustomers({ lifecycle: stage })} />
        </TabsContent>
        <TabsContent value="customers" className="mt-0">
          <CustomerList meta={meta.data} segments={segments.data} filters={filters} setFilters={setFilters}
                        onOpenCustomer={openCustomer} canEdit={canEdit} paused={Boolean(customerId) || segDialog.open || addOpen}
                        refreshKey={customersKey} onAddCustomer={() => setAddOpen(true)}
                        onSaveSegment={(f) => setSegDialog({ open: true, segment: null, initial: f })} />
        </TabsContent>
        <TabsContent value="segments" className="mt-0">
          <SegmentsPanel segments={segments.data} error={segments.error} reload={segments.reload} canEdit={canEdit}
                         onCreate={() => setSegDialog({ open: true, segment: null, initial: null })}
                         onEdit={(s) => setSegDialog({ open: true, segment: s, initial: null })}
                         onView={(s) => showCustomers({ segment_id: s.id })}
                         onDeleted={(s) => setFilters((f) => (f.segment_id === s.id ? { ...f, segment_id: "" } : f))} />
        </TabsContent>
        <TabsContent value="followups" className="mt-0">
          <FollowupsPanel canEdit={canEdit} onOpenCustomer={openCustomer} refreshKey={followupsKey}
                          onChanged={() => setOverviewKey((k) => k + 1)} />
        </TabsContent>
      </Tabs>

      <Customer360Sheet customerId={customerId} open={Boolean(customerId)} onOpenChange={(o) => !o && closeCustomer()}
                        canEdit={canEdit} tagSuggestions={meta.data?.tags} cities={meta.data?.cities}
                        onChanged={onCustomerChanged} onDeleted={onCustomerDeleted} />
      <CustomerDialog open={addOpen} onOpenChange={setAddOpen} cities={meta.data?.cities} onSaved={onCustomerAdded} />
      <SegmentDialog open={segDialog.open} onOpenChange={(o) => setSegDialog((s) => ({ ...s, open: o }))}
                     segment={segDialog.segment} initialFilters={segDialog.initial} meta={meta.data}
                     onSaved={() => { segments.reload({ background: true }); setCustomersKey((k) => k + 1); }} />
    </div>
  );
}
