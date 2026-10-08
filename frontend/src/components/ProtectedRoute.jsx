import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { WavygoLogo } from "@/components/WavygoLogo";
import { canViewModule } from "@/constants/permissions";
import Forbidden from "@/pages/Forbidden";

export function ProtectedRoute({ children, allowedModule }) {
  const { user, loading } = useAuth();
  const loc = useLocation();

  if (loading || user === null) {
    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4" data-testid="app-loading">
          <WavygoLogo />
          <div className="text-sm text-muted-foreground">Loading WavyGo OS…</div>
        </div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname + loc.search }} replace />;
  if (allowedModule && !canViewModule(user.role, allowedModule)) return <Forbidden />;
  return children;
}

export default ProtectedRoute;
