import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, formatApiError } from "@/lib/api";

const EMPTY = { name: "", email: "", phone: "", city: "", tags: "" };
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Add a customer, or edit one (`customer` given) — name, email, phone and city. */
export default function CustomerDialog({ open, onOpenChange, customer, cities, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const editing = Boolean(customer);
  // The 360 sheet refetches its customer in the background (every minute, on tab focus); keying the reset
  // on the id keeps those refreshes from wiping what the user is typing.
  const customerRef = useRef(customer);
  customerRef.current = customer;
  const customerId = customer?.id;

  useEffect(() => {
    if (!open) return;
    const c = customerRef.current;
    setErrors({});
    setForm(c
      ? { name: c.name || "", email: c.email || "", phone: c.phone || "", city: c.city || "", tags: "" }
      : EMPTY);
  }, [open, customerId]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function validate() {
    const next = {};
    if (!form.name.trim()) next.name = "Name is required";
    if (!form.email.trim()) next.email = "Email is required";
    else if (!EMAIL_RE.test(form.email.trim())) next.email = "Enter a valid email";
    if (!form.city.trim()) next.city = "City is required";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(e) {
    e.preventDefault();
    if (!validate()) return toast.error("Fill in the required fields");
    setSaving(true);
    try {
      const body = { name: form.name.trim(), email: form.email.trim(), phone: form.phone.trim() || null, city: form.city.trim() };
      if (!editing) body.tags = form.tags.split(",").map((t) => t.trim()).filter(Boolean);
      const { data } = editing
        ? await api.patch(`/crm/customers/${customer.id}`, body)
        : await api.post("/crm/customers", body);
      toast.success(editing ? "Customer updated" : `${data.name} added`);
      onSaved?.(data);
      onOpenChange(false);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const field = (key, label, props = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`cu-${key}`}>{label}</Label>
      <Input id={`cu-${key}`} value={form[key]} onChange={set(key)} aria-invalid={Boolean(errors[key])}
             data-testid={`crm-customer-${key}`} {...props} />
      {errors[key] && <p className="text-[12px] text-destructive">{errors[key]}</p>}
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? "Edit customer" : "Add customer"}</DialogTitle>
            <DialogDescription>
              {editing ? "Update the customer's contact details." : "New customers start as leads until their first booking."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            {field("name", "Name", { maxLength: 200, placeholder: "e.g. Asha Kumari", autoFocus: true })}
            {field("email", "Email", { type: "email", maxLength: 200, placeholder: "name@example.com" })}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {field("phone", "Phone (optional)", { type: "tel", maxLength: 40, placeholder: "+91 …" })}
              {field("city", "City", { maxLength: 100, list: "crm-city-options", placeholder: "e.g. Patna" })}
            </div>
            <datalist id="crm-city-options">
              {(cities || []).map((c) => <option key={c} value={c} />)}
            </datalist>
            {!editing && field("tags", "Tags (optional, comma separated)", { placeholder: "e.g. VIP, corporate" })}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="crm-customer-save">
              {saving && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}{editing ? "Save" : "Add customer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
