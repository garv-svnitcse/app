import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { Eye, EyeOff, ArrowRight, ShieldCheck, Bike, Loader2 } from "lucide-react";
import { WavygoLogo } from "@/components/WavygoLogo";
import { useAuth } from "@/contexts/AuthContext";
import { AUTH } from "@/constants/testIds";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const HERO_IMG = "https://images.unsplash.com/photo-1620802051782-725fa33db067?auto=format&fit=crop&w=1600&q=80";

const FLOATING_CARDS = [
  { key: "bookings",  label: "Today's Bookings", pos: "top-[12%] left-[6%]",       delay: 0.1, motion: "animate-float"      },
  { key: "vendors",   label: "Active Vendors",   pos: "top-[8%] right-[8%]",       delay: 0.2, motion: "animate-float-slow" },
  { key: "vehicles",  label: "Vehicles Online",  pos: "top-[46%] left-[10%]",      delay: 0.3, motion: "animate-float-slow" },
  { key: "cities",    label: "Cities Served",    pos: "bottom-[24%] right-[10%]",  delay: 0.4, motion: "animate-float"      },
  { key: "revenue",   label: "Revenue (MTD)",    pos: "bottom-[10%] left-[8%]",    delay: 0.5, motion: "animate-float-slow" },
];

export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const queryParams = new URLSearchParams(loc.search);
  const prefilledEmail = queryParams.get("email") || loc.state?.email || "";
  const [email, setEmail] = useState(prefilledEmail);
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [kpis, setKpis] = useState([]);

  useEffect(() => {
    api.get("/dashboard/live-kpis").then(({ data }) => setKpis(data.kpis)).catch(() => {});
  }, []);

  useEffect(() => {
    if (user && user !== false) nav(loc.state?.from || "/dashboard", { replace: true });
  }, [user, nav, loc.state]);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const res = await login({ email: email.trim(), password, remember });
    setBusy(false);
    if (!res.ok) { setError(res.error); toast.error(res.error); return; }
    toast.success("Welcome back to WavyGo OS");
    nav(loc.state?.from || "/dashboard", { replace: true });
  }

  const kpiByKey = Object.fromEntries(kpis.map((k) => [k.label, k.value]));

  return (
    <div className="min-h-screen w-full grid lg:grid-cols-[1.05fr_1fr] bg-background">
      {/* LEFT — hero */}
      <div className="relative hidden lg:block overflow-hidden">
        <img src={HERO_IMG} alt="" className="absolute inset-0 h-full w-full object-cover" />
        <div className="absolute inset-0" style={{
          background: "linear-gradient(135deg, hsla(148,74%,12%,0.88) 0%, hsla(148,82%,20%,0.72) 45%, hsla(148,74%,12%,0.94) 100%)"
        }} />
        <div className="absolute inset-0 wavygo-grid-bg opacity-[0.08]" />

        <div className="relative z-10 h-full flex flex-col justify-between p-10 xl:p-14 text-white">
          <div className="flex items-center gap-3">
            <WavygoLogo forceVariant="white" className="h-9 w-auto" />
            <div>
              <div className="font-display text-[15px] font-semibold">WavyGo OS</div>
              <div className="text-[10px] uppercase tracking-[0.16em] text-white/60">Enterprise Operating System</div>
            </div>
          </div>

          <div className="max-w-lg">
            <h1 className="font-display text-4xl xl:text-5xl font-semibold tracking-tighter leading-[1.05]">
              The operating system for modern <span className="italic text-wavygo-100">mobility</span>.
            </h1>
            <p className="mt-5 text-[15px] leading-relaxed text-white/80 max-w-md">
              Run bookings, vehicles, vendors, finance and city operations across India from a single unified workspace.
            </p>
            <div className="mt-6 flex items-center gap-3 text-[12px] text-white/70">
              <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> SOC-ready</span>
              <span className="h-1 w-1 rounded-full bg-white/40" />
              <span className="inline-flex items-center gap-1.5"><Bike className="h-3.5 w-3.5" /> Built in Patna</span>
            </div>
          </div>

          <div className="text-[11px] text-white/60 tracking-[0.06em]">
            <div>WAVYGO MOBILITY SERVICES PRIVATE LIMITED</div>
            <div>CIN&nbsp;·&nbsp;U77100BR2025PTC077095</div>
          </div>
        </div>

        {/* Floating KPI cards */}
        <div className="absolute inset-0 pointer-events-none z-20">
          {FLOATING_CARDS.map((c, i) => (
            <motion.div
              key={c.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: c.delay, duration: 0.6, ease: [0.2, 0.7, 0.2, 1] }}
              className={cn("absolute", c.pos)}
            >
              <div className={cn(
                "rounded-xl bg-white/[0.09] backdrop-blur-xl border border-white/15 shadow-xl px-4 py-3 min-w-[172px]",
                c.motion
              )} style={{ animationDelay: `${i * 0.5}s` }}>
                <div className="text-[10px] uppercase tracking-[0.14em] text-white/60">{c.label}</div>
                <div className="font-display text-[22px] font-semibold text-white mt-0.5 leading-none">
                  {kpiByKey[c.label] || "—"}
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>

      {/* RIGHT — form */}
      <div className="flex flex-col justify-between p-6 sm:p-10">
        <div className="flex justify-between items-center">
          <WavygoLogo className="h-8" />
          <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Sign in</div>
        </div>

        <div className="mx-auto w-full max-w-sm py-10">
          <motion.div
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.2, 0.7, 0.2, 1] }}
          >
            <h2 className="font-display text-3xl font-semibold tracking-tight text-foreground">Welcome to WavyGo OS</h2>
            <p className="text-sm text-muted-foreground mt-2">Sign in with your work credentials to continue.</p>
          </motion.div>

          <form onSubmit={onSubmit} className="mt-8 space-y-4">
            <div>
              <Label htmlFor="email" className="text-[12px] font-medium text-foreground/80">Email</Label>
              <Input
                data-testid={AUTH.emailInput}
                id="email" type="email" autoComplete="email" required autoFocus
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="you@wavygo.in"
                className="mt-1.5 h-11"
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <Label htmlFor="password" className="text-[12px] font-medium text-foreground/80">Password</Label>
                <button type="button" data-testid={AUTH.forgotLink} onClick={() => toast.info("Password reset link will be emailed shortly.")} className="text-[12px] text-primary hover:underline">
                  Forgot password?
                </button>
              </div>
              <div className="relative mt-1.5">
                <Input
                  data-testid={AUTH.passwordInput}
                  id="password" type={showPw ? "text" : "password"} autoComplete="current-password" required
                  value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••"
                  className="h-11 pr-10"
                />
                <button type="button" onClick={() => setShowPw(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label="Toggle password visibility">
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <label className="flex items-center gap-2 text-[13px] text-muted-foreground select-none">
              <Checkbox data-testid={AUTH.rememberCheckbox} checked={remember} onCheckedChange={(v) => setRemember(!!v)} />
              Keep me signed in for 30 days
            </label>

            {error && (
              <div data-testid={AUTH.errorMessage} className="text-[12.5px] text-destructive bg-destructive/10 rounded-md px-3 py-2 border border-destructive/20">
                {error}
              </div>
            )}

            <Button data-testid={AUTH.submitButton} type="submit" disabled={busy}
                    className="w-full h-11 bg-primary hover:bg-wavygo-600 text-primary-foreground font-medium">
              {busy ? <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Signing in…</span> : (<span className="inline-flex items-center gap-1.5">Sign in <ArrowRight className="h-4 w-4" /></span>)}
            </Button>
          </form>

          <div className="mt-8 rounded-lg border border-border bg-muted/40 px-4 py-3">
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-1">Demo access</div>
            <div className="text-[12.5px] text-foreground/80 leading-relaxed">
              <div><span className="text-muted-foreground">Founder</span> · anilanand635@gmail.com / Wavygo@2026</div>
              <div><span className="text-muted-foreground">Admin</span> · admin@wavygo.in / Wavygo@2026</div>
              <div><span className="text-muted-foreground">Employee</span> · employee@wavygo.in / Wavygo@2026</div>
            </div>
          </div>
        </div>

        <footer className="text-[11px] text-muted-foreground tracking-[0.04em] pt-4 border-t border-border">
          <div className="font-medium text-foreground/80">WAVYGO MOBILITY SERVICES PRIVATE LIMITED</div>
          <div>CIN · U77100BR2025PTC077095</div>
        </footer>
      </div>
    </div>
  );
}
