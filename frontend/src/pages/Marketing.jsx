import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/module/ModulePrimitives";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePermission } from "@/hooks/usePermission";
import { useResource } from "@/components/crm/crmShared";
import MarketingOverview from "@/components/marketing/MarketingOverview";
import CampaignList from "@/components/marketing/CampaignList";
import CampaignDialog from "@/components/marketing/CampaignDialog";
import CampaignDetailSheet from "@/components/marketing/CampaignDetailSheet";

const TABS = ["overview", "campaigns"];

export default function Marketing() {
  const { can } = usePermission();
  const canManage = can("marketing.manage");
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = TABS.includes(searchParams.get("tab")) ? searchParams.get("tab") : "overview";
  const campaignId = searchParams.get("campaign");

  const [dialog, setDialog] = useState({ open: false, campaign: null });
  const [refreshKey, setRefreshKey] = useState(0);
  const meta = useResource("/marketing/meta", null, { paused: dialog.open });

  const setTab = useCallback((t) => setSearchParams((p) => {
    if (t === "overview") p.delete("tab"); else p.set("tab", t);
    return p;
  }), [setSearchParams]);
  const openCampaign = useCallback((id) => setSearchParams((p) => { p.set("campaign", id); return p; }), [setSearchParams]);
  const closeCampaign = useCallback(() => setSearchParams((p) => { p.delete("campaign"); return p; }), [setSearchParams]);

  const openCreate = useCallback(() => {
    meta.reload({ background: true });
    setDialog({ open: true, campaign: null });
  }, [meta]);

  // ?create=campaign (Quick Create) opens the new-campaign dialog once per request (re-armed once the param is gone).
  const handledCreate = useRef(false);
  useEffect(() => {
    if (searchParams.get("create") !== "campaign") { handledCreate.current = false; return; }
    if (handledCreate.current) return;
    handledCreate.current = true;
    setSearchParams((p) => { p.delete("create"); return p; }, { replace: true });
    if (canManage) setDialog({ open: true, campaign: null });
  }, [searchParams, setSearchParams, canManage]);

  const changed = () => setRefreshKey((k) => k + 1);
  const newButton = canManage && (
    <Button onClick={openCreate} className="gap-1.5 font-medium" data-testid="marketing-new-campaign">
      <Plus className="h-4 w-4" /> New campaign
    </Button>
  );

  return (
    <div data-testid="marketing-page">
      <PageHeader
        eyebrow="Growth"
        title="Marketing"
        description="Plan campaigns, track budget against spend, and see what the booking data can attribute."
        actions={newButton}
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-muted/60 p-1 mb-5">
          <TabsTrigger value="overview" data-testid="marketing-tab-overview">Overview</TabsTrigger>
          <TabsTrigger value="campaigns" data-testid="marketing-tab-campaigns">Campaigns</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="mt-0">
          <MarketingOverview onOpenCampaign={openCampaign} onCreate={newButton} refreshKey={refreshKey} />
        </TabsContent>
        <TabsContent value="campaigns" className="mt-0">
          <CampaignList onOpenCampaign={openCampaign} onCreate={newButton} refreshKey={refreshKey}
                        paused={dialog.open || Boolean(campaignId)} />
        </TabsContent>
      </Tabs>

      <CampaignDetailSheet campaignId={campaignId} open={Boolean(campaignId)} onOpenChange={(o) => !o && closeCampaign()}
                           canManage={canManage} onChanged={changed} refreshKey={refreshKey}
                           onEdit={(c) => { meta.reload({ background: true }); setDialog({ open: true, campaign: c }); }} />
      <CampaignDialog open={dialog.open} onOpenChange={(o) => setDialog((d) => ({ ...d, open: o }))} campaign={dialog.campaign}
                      meta={meta.data} onSaved={(c) => { changed(); if (!dialog.campaign) openCampaign(c.id); }} />
    </div>
  );
}
