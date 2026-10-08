import { useEffect, useState } from "react";
import { api } from "../lib/api"; // <- change to your existing API helper

const SUBMITTED_FIELDS = [
  ["phone", "Phone"],
  ["personal_email", "Personal email"],
  ["date_of_birth", "Date of birth", "date"],
  ["address", "Address"],
  ["emergency_contact_name", "Emergency contact"],
  ["emergency_contact_relation", "Relation"],
  ["emergency_contact_phone", "Emergency phone"],
  ["college", "College"],
  ["degree", "Degree"],
  ["resume_url", "Resume link"],
  ["id_proof_url", "ID proof link"],
  ["bank_account_last4", "Bank account (last 4 digits)"],
];

const COMPANY_FIELDS = [
  ["employee_code", "Employee ID"],
  ["reporting_manager", "Reporting manager"],
  ["joining_date", "Joining date", "date"],
  ["employment_type", "Employment type"],
  ["stipend_or_salary", "Stipend / salary", "number"],
  ["offer_letter_url", "Offer letter link"],
  ["nda_signed", "NDA signed", "checkbox"],
  ["assigned_assets", "Assigned assets"],
];

function Section({ title, fields, values, editable, onSave }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(values);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setForm(values), [values]);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await onSave(form);
      setEditing(false);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Could not save");
    } finally {
      setSaving(false);
    }
  };

  const show = (v, type) => {
    if (type === "checkbox") return v ? "Yes" : "No";
    return v === null || v === undefined || v === "" ? "—" : String(v);
  };

  const isLink = (key) => key.endsWith("_url");

  return (
    <section className="mb-6 rounded-xl border border-white/10 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-white/70">{title}</h3>
        {editable && !editing && (
          <button onClick={() => setEditing(true)}
            className="rounded-lg border border-white/10 px-3 py-1 text-xs hover:bg-white/5">Edit</button>
        )}
      </div>

      <div className="space-y-3">
        {fields.map(([key, label, type]) => (
          <div key={key}>
            <div className="text-xs text-white/50">{label}</div>
            {editing ? (
              type === "checkbox" ? (
                <input type="checkbox" checked={!!form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.checked })} />
              ) : (
                <input
                  type={type || "text"}
                  value={form[key] ?? ""}
                  onChange={(e) => setForm({
                    ...form,
                    [key]: type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value,
                  })}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-transparent px-3 py-1.5 text-sm"
                />
              )
            ) : isLink(key) && values[key] ? (
              <a href={values[key]} target="_blank" rel="noreferrer" className="text-sm text-emerald-400 underline">Open</a>
            ) : (
              <div className="text-sm">{show(values[key], type)}</div>
            )}
          </div>
        ))}
      </div>

      {editing && (
        <div className="mt-4 flex items-center gap-2">
          <button onClick={save} disabled={saving}
            className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium disabled:opacity-50">
            {saving ? "Saving…" : "Save"}
          </button>
          <button onClick={() => { setEditing(false); setForm(values); }}
            className="rounded-lg border border-white/10 px-4 py-1.5 text-sm">Cancel</button>
          {error && <span className="text-xs text-red-400">{error}</span>}
        </div>
      )}
    </section>
  );
}

export default function EmployeeDetailsDrawer({ employee, onClose }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.get(`/employees/${employee.id}/profile`)
      .then((res) => alive && setProfile(res.data ?? res))
      .catch((e) => alive && setError(e?.response?.data?.detail || "Could not load details"))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [employee.id]);

  const saveSubmitted = async (form) => {
    const res = await api.put(`/employees/${employee.id}/profile/submitted`, form);
    setProfile(res.data ?? res);
  };

  const saveCompany = async (form) => {
    const res = await api.patch(`/employees/${employee.id}/profile/company`, form);
    setProfile(res.data ?? res);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside className="h-full w-full max-w-lg overflow-y-auto bg-neutral-900 p-6"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold">{employee.name}</h2>
            <p className="text-sm text-white/50">{employee.email}</p>
          </div>
          <button onClick={onClose} className="rounded-lg border border-white/10 px-3 py-1 text-sm">Close</button>
        </div>

        {loading && <p className="text-sm text-white/50">Loading…</p>}
        {error && <p className="text-sm text-red-400">{error}</p>}

        {profile && (
          <>
            <Section title="Submitted by employee" fields={SUBMITTED_FIELDS}
              values={profile.submitted} editable={profile.can_edit_submitted} onSave={saveSubmitted} />
            <Section title="Provided by company" fields={COMPANY_FIELDS}
              values={profile.company} editable={profile.can_edit_company} onSave={saveCompany} />
          </>
        )}
      </aside>
    </div>
  );
}