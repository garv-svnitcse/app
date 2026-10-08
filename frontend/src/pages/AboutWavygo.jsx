import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { WavygoLogo } from "@/components/WavygoLogo";

export default function AboutWavygo() {
  const [company, setCompany] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setError(null);
    api.get("/settings/company")
      .then(({ data }) => setCompany(data))
      .catch((e) => setError(e?.response?.data?.detail || "Could not load company details."));
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="rounded-2xl border border-border p-8 bg-gradient-to-br from-primary/[0.06] to-transparent">
        <div className="flex items-start gap-6">
          <div className="h-16 w-16 rounded-xl bg-white flex items-center justify-center shadow-sm border border-border">
            <WavygoLogo forceVariant="green" className="h-10" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">WavyGo Mobility Services</h1>
            <p className="text-sm text-muted-foreground mt-2 max-w-xl">
              A modern mobility company building the operating system, marketplace and fleet network for two-wheeler rentals across India.
            </p>
          </div>
        </div>
      </div>

      <Card className="border-border">
        <CardHeader><CardTitle className="font-display">Registered entity</CardTitle></CardHeader>
        <CardContent>
          {company ? (
            <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
              {Object.entries(company).map(([k, v]) => (
                <div key={k}>
                  <dt className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{k}</dt>
                  <dd className="text-[14px] font-medium text-foreground mt-0.5">{v}</dd>
                </div>
              ))}
            </dl>
          ) : error ? (
            <div className="text-sm text-muted-foreground" data-testid="about-error">
              {String(error)}
              <Button variant="outline" size="sm" onClick={load} className="ml-3 h-7 text-xs">Retry</Button>
            </div>
          ) : <div className="text-sm text-muted-foreground">Loading…</div>}
        </CardContent>
      </Card>
    </div>
  );
}
