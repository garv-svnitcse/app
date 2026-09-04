import { useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Sparkles, Plus } from "lucide-react";
import { NAV_ITEMS } from "@/constants/nav";
import { toast } from "sonner";

export default function ModulePlaceholder() {
  const loc = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const item = NAV_ITEMS.find((n) => n.to === loc.pathname);
  const Icon = item?.icon || Sparkles;

  const moduleKey = loc.pathname.replace("/", "");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  // Form states
  const [campaignForm, setCampaignForm] = useState({
    name: "", channel: "Social Media", budget: 25000, audience: "General Audience", startDate: "", endDate: "", description: ""
  });
  const [eventForm, setEventForm] = useState({
    title: "", category: "Meeting", date: "", time: "10:00 AM", location: "Online Sync", description: ""
  });
  const [docForm, setDocForm] = useState({
    title: "", category: "Legal & Compliance", access: "All Teammates", url: "", description: ""
  });
  const [genericForm, setGenericForm] = useState({
    name: "", category: "General", notes: ""
  });

  useEffect(() => {
    const createParam = searchParams.get("create");
    if (createParam || searchParams.get("action")) {
      setOpen(true);
      setSearchParams(params => {
        params.delete("create");
        params.delete("action");
        return params;
      }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleCreate = () => {
    setSubmitting(true);
    setTimeout(() => {
      let newItem = null;
      if (moduleKey === "marketing") {
        newItem = { id: Date.now(), title: campaignForm.name || "Untitled Campaign", detail: `${campaignForm.channel} · ₹${campaignForm.budget}`, date: campaignForm.startDate || "Just now" };
        toast.success(`Campaign "${campaignForm.name || "New Campaign"}" created!`);
      } else if (moduleKey === "calendar") {
        newItem = { id: Date.now(), title: eventForm.title || "Untitled Event", detail: `${eventForm.category} · ${eventForm.time}`, date: eventForm.date || "Today" };
        toast.success(`Event "${eventForm.title || "New Event"}" scheduled!`);
      } else if (moduleKey === "company-vault") {
        newItem = { id: Date.now(), title: docForm.title || "Untitled Document", detail: `${docForm.category} · ${docForm.access}`, date: "Uploaded today" };
        toast.success(`Document "${docForm.title || "New Document"}" uploaded to Vault!`);
      } else {
        newItem = { id: Date.now(), title: genericForm.name || "New Item", detail: genericForm.category, date: "Created today" };
        toast.success(`${item?.label || "Item"} created successfully!`);
      }
      if (newItem) setItems(prev => [newItem, ...prev]);
      setSubmitting(false);
      setOpen(false);
    }, 400);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Module</div>
          <h1 className="font-display text-3xl font-semibold tracking-tight mt-1">{item?.label || "Coming soon"}</h1>
          <p className="text-sm text-muted-foreground mt-2 max-w-xl">
            The <span className="font-medium text-foreground">{item?.label}</span> module features and creation workflows.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge className="bg-primary/10 text-primary hover:bg-primary/10">Phase 2</Badge>
          <Button onClick={() => setOpen(true)} className="gap-1.5 font-medium">
            <Plus className="h-4 w-4" /> Create {item?.label ? item.label.split(" ")[0] : "New"}
          </Button>
        </div>
      </div>

      {items.length > 0 && (
        <Card className="border-border">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-display">Recent Items</CardTitle>
          </CardHeader>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Details</TableHead>
                <TableHead>Date</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map(it => (
                <TableRow key={it.id}>
                  <TableCell className="font-medium">{it.title}</TableCell>
                  <TableCell className="text-muted-foreground">{it.detail}</TableCell>
                  <TableCell>{it.date}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-600 border-emerald-200">Active</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <Card className="border-border border-dashed">
        <CardContent className="p-12 flex flex-col items-center text-center">
          <div className="h-14 w-14 rounded-xl bg-primary/10 text-primary flex items-center justify-center">
            <Icon className="h-6 w-6" strokeWidth={1.75} />
          </div>
          <h3 className="font-display text-lg font-semibold mt-4">{item?.label} Workspace</h3>
          <p className="text-sm text-muted-foreground mt-2 max-w-md">
            Click the button above or use Quick Create to add new items directly to this workspace.
          </p>
          <Button onClick={() => setOpen(true)} variant="outline" className="mt-4 gap-1.5">
            <Plus className="h-4 w-4" /> Open Creation Form
          </Button>
        </CardContent>
      </Card>

      {/* Creation Modal Dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-display">
              {moduleKey === "marketing" ? "New Marketing Campaign" :
               moduleKey === "calendar" ? "New Calendar Event" :
               moduleKey === "company-vault" ? "Upload Document to Vault" :
               `Create ${item?.label || "Item"}`}
            </DialogTitle>
            <DialogDescription>Fill out the form below to create a new entry.</DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-1">
            {moduleKey === "marketing" && (
              <>
                <div>
                  <Label className="text-[12px]">Campaign Name</Label>
                  <Input placeholder="e.g. Diwali Fleet Surge 2026" className="mt-1" value={campaignForm.name} onChange={e => setCampaignForm(s => ({ ...s, name: e.target.value }))} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-[12px]">Channel</Label>
                    <Select value={campaignForm.channel} onValueChange={v => setCampaignForm(s => ({ ...s, channel: v }))}>
                      <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Social Media">Social Media</SelectItem>
                        <SelectItem value="Performance Ads">Performance Ads</SelectItem>
                        <SelectItem value="Email Blast">Email Blast</SelectItem>
                        <SelectItem value="Billboard">Billboard</SelectItem>
                        <SelectItem value="Event">Event & Activation</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-[12px]">Budget (₹)</Label>
                    <Input type="number" className="mt-1" value={campaignForm.budget} onChange={e => setCampaignForm(s => ({ ...s, budget: parseFloat(e.target.value) || 0 }))} />
                  </div>
                </div>
                <div>
                  <Label className="text-[12px]">Target Audience</Label>
                  <Input placeholder="e.g. Daily commuters & College students" className="mt-1" value={campaignForm.audience} onChange={e => setCampaignForm(s => ({ ...s, audience: e.target.value }))} />
                </div>
                <div>
                  <Label className="text-[12px]">Objectives & Notes</Label>
                  <Textarea placeholder="Key goals and campaign details..." className="mt-1" rows={3} value={campaignForm.description} onChange={e => setCampaignForm(s => ({ ...s, description: e.target.value }))} />
                </div>
              </>
            )}

            {moduleKey === "calendar" && (
              <>
                <div>
                  <Label className="text-[12px]">Event Title</Label>
                  <Input placeholder="e.g. Q4 Fleet Expansion Strategy" className="mt-1" value={eventForm.title} onChange={e => setEventForm(s => ({ ...s, title: e.target.value }))} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-[12px]">Category</Label>
                    <Select value={eventForm.category} onValueChange={v => setEventForm(s => ({ ...s, category: v }))}>
                      <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Meeting">Meeting</SelectItem>
                        <SelectItem value="Product Launch">Product Launch</SelectItem>
                        <SelectItem value="Team Sync">Team Sync</SelectItem>
                        <SelectItem value="Workshop">Workshop</SelectItem>
                        <SelectItem value="Milestone">Milestone</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-[12px]">Time</Label>
                    <Input className="mt-1" value={eventForm.time} onChange={e => setEventForm(s => ({ ...s, time: e.target.value }))} />
                  </div>
                </div>
                <div>
                  <Label className="text-[12px]">Date</Label>
                  <Input type="date" className="mt-1" value={eventForm.date} onChange={e => setEventForm(s => ({ ...s, date: e.target.value }))} />
                </div>
                <div>
                  <Label className="text-[12px]">Location / Meeting Link</Label>
                  <Input placeholder="Google Meet link or Conference Room 3" className="mt-1" value={eventForm.location} onChange={e => setEventForm(s => ({ ...s, location: e.target.value }))} />
                </div>
              </>
            )}

            {moduleKey === "company-vault" && (
              <>
                <div>
                  <Label className="text-[12px]">Document Title</Label>
                  <Input placeholder="e.g. FY26 Fleet Operations Agreement.pdf" className="mt-1" value={docForm.title} onChange={e => setDocForm(s => ({ ...s, title: e.target.value }))} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-[12px]">Category</Label>
                    <Select value={docForm.category} onValueChange={v => setDocForm(s => ({ ...s, category: v }))}>
                      <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Legal & Compliance">Legal & Compliance</SelectItem>
                        <SelectItem value="Finance & Tax">Finance & Tax</SelectItem>
                        <SelectItem value="HR & Payroll">HR & Payroll</SelectItem>
                        <SelectItem value="Product & Tech">Product & Tech</SelectItem>
                        <SelectItem value="Operations">Operations</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-[12px]">Access Level</Label>
                    <Select value={docForm.access} onValueChange={v => setDocForm(s => ({ ...s, access: v }))}>
                      <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="All Teammates">All Teammates</SelectItem>
                        <SelectItem value="Management Only">Management Only</SelectItem>
                        <SelectItem value="Founders Only">Founders Only</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <Label className="text-[12px]">Document URL or Path</Label>
                  <Input placeholder="https://vault.wavygo.com/docs/..." className="mt-1" value={docForm.url} onChange={e => setDocForm(s => ({ ...s, url: e.target.value }))} />
                </div>
              </>
            )}

            {["marketing", "calendar", "company-vault"].includes(moduleKey) === false && (
              <>
                <div>
                  <Label className="text-[12px]">Name / Title</Label>
                  <Input placeholder={`Enter ${item?.label || "item"} name`} className="mt-1" value={genericForm.name} onChange={e => setGenericForm(s => ({ ...s, name: e.target.value }))} />
                </div>
                <div>
                  <Label className="text-[12px]">Category</Label>
                  <Input className="mt-1" value={genericForm.category} onChange={e => setGenericForm(s => ({ ...s, category: e.target.value }))} />
                </div>
                <div>
                  <Label className="text-[12px]">Notes</Label>
                  <Textarea className="mt-1" rows={3} value={genericForm.notes} onChange={e => setGenericForm(s => ({ ...s, notes: e.target.value }))} />
                </div>
              </>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={handleCreate} disabled={submitting}>
              {submitting ? "Saving..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
