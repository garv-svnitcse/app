import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api, tokens, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { CheckCircle2, ShieldCheck, KeyRound, ArrowRight, AlertCircle, Eye, EyeOff } from "lucide-react";

const MIN_PASSWORD = 8;

function readTokenFromUrl() {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("token") || "";
}

function passwordStrength(pw) {
  if (!pw) return { score: 0, label: "", color: "bg-slate-800" };
  let score = 0;
  if (pw.length >= MIN_PASSWORD) score += 1;
  if (pw.length >= 12) score += 1;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score += 1;
  if (/\d/.test(pw)) score += 1;
  if (/[^A-Za-z0-9]/.test(pw)) score += 1;
  if (pw.length < MIN_PASSWORD) return { score: 1, label: `Too short — at least ${MIN_PASSWORD} characters`, color: "bg-red-500" };
  if (score <= 2) return { score: 2, label: "Weak — add numbers, symbols or mixed case", color: "bg-amber-500" };
  if (score <= 3) return { score: 3, label: "Fair", color: "bg-yellow-400" };
  if (score <= 4) return { score: 4, label: "Good", color: "bg-emerald-500" };
  return { score: 5, label: "Strong", color: "bg-emerald-400" };
}

export default function ResetPassword() {
  // Read the token once, then strip it from the address bar so it doesn't linger in history
  const [token] = useState(readTokenFromUrl);
  const [status, setStatus] = useState(token ? "checking" : "invalid"); // checking | ready | invalid | done
  const [maskedEmail, setMaskedEmail] = useState("");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (window.location.search.includes("token=")) {
      window.history.replaceState(window.history.state, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    let active = true;
    api.get("/auth/reset-password/validate", { params: { token } })
      .then(({ data }) => {
        if (!active) return;
        setMaskedEmail(data.email || "");
        setStatus(data.valid ? "ready" : "invalid");
      })
      .catch(() => { if (active) setStatus("invalid"); });
    return () => { active = false; };
  }, [token]);

  const strength = passwordStrength(password);
  const mismatch = confirmPassword.length > 0 && password !== confirmPassword;

  async function handleSubmit(e) {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) {
      toast.error(`Password must be at least ${MIN_PASSWORD} characters`);
      return;
    }
    if (password !== confirmPassword) {
      toast.error("Passwords do not match");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/auth/reset-password", { token, password });
      tokens.clear();
      setStatus("done");
      toast.success("Password updated. Please sign in.");
    } catch (err) {
      if (err?.response?.status === 400 && /invalid or has expired/i.test(formatApiError(err))) {
        setStatus("invalid");
      }
      toast.error(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col justify-center items-center bg-slate-950 text-slate-100 p-4 relative overflow-hidden">
      {/* Background Decor */}
      <div className="absolute -top-40 -left-40 w-96 h-96 bg-blue-600/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-40 -right-40 w-96 h-96 bg-indigo-600/20 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-md space-y-6 relative z-10">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold uppercase tracking-wider">
            <ShieldCheck className="w-3.5 h-3.5" /> WavyGo OS Workspace
          </div>
          <h1 className="font-display text-3xl font-extrabold tracking-tight text-white">Reset Your Password</h1>
        </div>

        {status === "checking" ? (
          <Card className="border-slate-800 bg-slate-900/80 backdrop-blur-xl text-slate-100 p-8 text-center space-y-3">
            <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto" />
            <p className="text-sm text-slate-400">Verifying reset link…</p>
          </Card>
        ) : status === "invalid" ? (
          <Card className="border-red-500/30 bg-slate-900/90 backdrop-blur-xl text-slate-100 p-6 space-y-4">
            <div className="flex items-center gap-3 text-red-400">
              <AlertCircle className="w-6 h-6 shrink-0" />
              <h2 className="font-semibold text-base">Link invalid or expired</h2>
            </div>
            <p className="text-sm text-slate-400 leading-relaxed">
              This password reset link is invalid, has already been used, or has expired. Reset links work once and
              expire after 30 minutes. Request a new one from the sign-in page.
            </p>
            <Button asChild className="w-full bg-slate-800 hover:bg-slate-700 text-white">
              <Link to="/login">Back to Login</Link>
            </Button>
          </Card>
        ) : status === "done" ? (
          <Card className="border-emerald-500/30 bg-slate-900/90 backdrop-blur-xl text-slate-100 p-6 text-center space-y-5">
            <div className="w-14 h-14 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center mx-auto">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <div className="space-y-1">
              <h2 className="font-display text-2xl font-bold text-white">Password Updated!</h2>
              <p className="text-sm text-slate-400">
                For your security, you have been signed out of all devices. Sign in with your new password.
              </p>
            </div>
            <Button asChild className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium h-11">
              {/* Full navigation so any in-memory session from before the reset is dropped */}
              <a href="/login">
                Sign in <ArrowRight className="w-4 h-4 ml-2" />
              </a>
            </Button>
          </Card>
        ) : (
          <Card className="border-slate-800 bg-slate-900/90 backdrop-blur-xl text-slate-100 shadow-2xl">
            <CardHeader className="space-y-1">
              <CardTitle className="text-xl font-display font-bold">Choose a New Password</CardTitle>
              <CardDescription className="text-slate-400 text-xs">
                {maskedEmail ? <>For account <span className="text-slate-200 font-medium">{maskedEmail}</span></> : "Set a new password for your account"}
              </CardDescription>
            </CardHeader>

            <form onSubmit={handleSubmit}>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="new-password" className="text-xs text-slate-300">New Password</Label>
                  <div className="relative">
                    <Input
                      id="new-password"
                      type={showPassword ? "text" : "password"}
                      autoComplete="new-password"
                      autoFocus
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={`Minimum ${MIN_PASSWORD} characters`}
                      required
                      minLength={MIN_PASSWORD}
                      className="bg-slate-950 border-slate-800 text-slate-100 pr-10 focus:border-blue-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label="Toggle password visibility"
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  {password && (
                    <div className="space-y-1 pt-1" aria-live="polite">
                      <div className="flex gap-1">
                        {[1, 2, 3, 4, 5].map((i) => (
                          <div key={i} className={`h-1 flex-1 rounded-full ${i <= strength.score ? strength.color : "bg-slate-800"}`} />
                        ))}
                      </div>
                      <p className="text-[11px] text-slate-400">{strength.label}</p>
                    </div>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="confirm-password" className="text-xs text-slate-300">Confirm Password</Label>
                  <Input
                    id="confirm-password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-enter password"
                    required
                    minLength={MIN_PASSWORD}
                    className="bg-slate-950 border-slate-800 text-slate-100 focus:border-blue-500"
                  />
                  {mismatch && <p className="text-[11px] text-red-400">Passwords do not match</p>}
                </div>
              </CardContent>

              <CardFooter className="flex flex-col gap-3 pt-2">
                <Button
                  type="submit"
                  disabled={submitting}
                  className="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold h-10 transition-colors"
                >
                  {submitting ? (
                    <span className="flex items-center gap-2">
                      <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                      Updating Password…
                    </span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <KeyRound className="w-4 h-4" /> Update Password
                    </span>
                  )}
                </Button>
                <div className="text-center text-xs text-slate-500">
                  Remembered it?{" "}
                  <Link to="/login" className="text-blue-400 hover:underline">
                    Back to sign in
                  </Link>
                </div>
              </CardFooter>
            </form>
          </Card>
        )}
      </div>
    </div>
  );
}
