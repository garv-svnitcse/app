import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { usePermission } from "@/hooks/usePermission";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

export default function Settings() {
  const { user, refreshMe } = useAuth();
  const { theme, setTheme } = useTheme();
  const { can, role } = usePermission();
  const canChangePassword = can("auth.change_own_password");
  const isPersonal = role === "Employee" || role === "Intern";
  const [profile, setProfile] = useState({ name: "", phone: "", designation: "", department: "" });
  const [pwForm, setPwForm] = useState({ current_password: "", new_password: "" });
  const [company, setCompany] = useState(null);
  const [roles, setRoles] = useState([]);

  const [savingProfile, setSavingProfile] = useState(false);
  const [changingPw, setChangingPw] = useState(false);

  useEffect(() => {
    if (user) setProfile({
      name: user.name || "", phone: user.phone || "",
      designation: user.designation || "", department: user.department || "",
    });
  }, [user]);

  useEffect(() => {
    api.get("/settings/company").then(({ data }) => setCompany(data)).catch(() => {});
    api.get("/settings/roles").then(({ data }) => setRoles(data.roles)).catch(() => {});
  }, []);

  async function saveProfile() {
    setSavingProfile(true);
    try {
      await api.patch("/users/me", { phone: profile.phone });
      await refreshMe();
      toast.success("Profile updated");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setSavingProfile(false);
    }
  }

  async function changePassword() {
    setChangingPw(true);
    try {
      await api.post("/users/me/password", pwForm);
      setPwForm({ current_password: "", new_password: "" });
      toast.success("Password updated");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setChangingPw(false);
    }
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Settings</div>
        <h1 className="font-display text-3xl font-semibold tracking-tight mt-1">{isPersonal ? "My Profile" : "Workspace preferences"}</h1>
      </div>

      <Tabs defaultValue="profile" className="w-full">
        <TabsList>
          <TabsTrigger value="profile" data-testid="tab-profile">Profile</TabsTrigger>
          <TabsTrigger value="company" data-testid="tab-company">Company</TabsTrigger>
          <TabsTrigger value="theme" data-testid="tab-theme">Theme</TabsTrigger>
          <TabsTrigger value="security" data-testid="tab-security">Security</TabsTrigger>
          <TabsTrigger value="roles" data-testid="tab-roles">Roles</TabsTrigger>
        </TabsList>

        <TabsContent value="profile" className="mt-4">
          <Card className="border-border">
            <CardHeader><CardTitle className="font-display">Your profile</CardTitle><CardDescription>Update your personal details</CardDescription></CardHeader>
            <CardContent className="space-y-4 max-w-lg">
              <div><Label>Name</Label><Input className="mt-1.5" value={profile.name} disabled data-testid="profile-name" /></div>
              <div><Label>Phone</Label><Input className="mt-1.5" value={profile.phone} onChange={(e) => setProfile(s => ({ ...s, phone: e.target.value }))} placeholder="+91" disabled={savingProfile} data-testid="profile-phone" /></div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Designation</Label><Input className="mt-1.5" value={profile.designation} disabled data-testid="profile-designation" /></div>
                <div><Label>Department</Label><Input className="mt-1.5" value={profile.department} disabled data-testid="profile-department" /></div>
              </div>
              <Button onClick={saveProfile} disabled={savingProfile} data-testid="save-profile-btn">
                {savingProfile ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                {savingProfile ? "Saving..." : "Save changes"}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="company" className="mt-4">
          <Card className="border-border">
            <CardHeader><CardTitle className="font-display">Company</CardTitle><CardDescription>Registered entity details</CardDescription></CardHeader>
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
              ) : <div className="text-sm text-muted-foreground">Loading…</div>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="theme" className="mt-4">
          <Card className="border-border">
            <CardHeader><CardTitle className="font-display">Appearance</CardTitle><CardDescription>Personalise WavyGo OS</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between max-w-md">
                <div>
                  <div className="text-[14px] font-medium">Dark mode</div>
                  <div className="text-[12px] text-muted-foreground">Reduces eye strain in low-light environments.</div>
                </div>
                <Switch checked={theme === "dark"} onCheckedChange={(v) => setTheme(v ? "dark" : "light")} data-testid="dark-mode-switch" />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="security" className="mt-4">
          <Card className="border-border">
            <CardHeader><CardTitle className="font-display">Security</CardTitle><CardDescription>{canChangePassword ? "Change your password" : "Password management"}</CardDescription></CardHeader>
            <CardContent className="space-y-4 max-w-md">
              {canChangePassword ? (
                <>
                  <div><Label>Current password</Label><Input type="password" className="mt-1.5" value={pwForm.current_password} onChange={(e) => setPwForm(s => ({ ...s, current_password: e.target.value }))} disabled={changingPw} data-testid="current-password-input" /></div>
                  <div><Label>New password</Label><Input type="password" className="mt-1.5" value={pwForm.new_password} onChange={(e) => setPwForm(s => ({ ...s, new_password: e.target.value }))} disabled={changingPw} data-testid="new-password-input" /></div>
                  <Button onClick={changePassword} disabled={changingPw} data-testid="change-password-btn">
                    {changingPw ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                    {changingPw ? "Updating..." : "Update password"}
                  </Button>
                </>
              ) : (
                <div className="text-[13.5px] text-muted-foreground leading-relaxed" data-testid="password-managed-note">
                  Password changes are managed by your Founder/Admin. Please contact them if you need a reset.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="roles" className="mt-4">
          <Card className="border-border">
            <CardHeader><CardTitle className="font-display">Roles & permissions</CardTitle><CardDescription>How access is structured across WavyGo OS</CardDescription></CardHeader>
            <CardContent>
              <div className="space-y-3">
                {roles.map((r) => (
                  <div key={r.name} className="flex items-start justify-between gap-4 p-4 rounded-lg border border-border">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-display font-semibold text-foreground">{r.name}</span>
                        <Badge variant="secondary" className="text-[10px]">Level {r.level}</Badge>
                      </div>
                      <div className="text-[13px] text-muted-foreground mt-1">{r.description}</div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
