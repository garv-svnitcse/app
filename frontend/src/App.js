import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import Login from "@/pages/Login";
import AcceptInvite from "@/pages/AcceptInvite";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import Settings from "@/pages/Settings";
import NotificationsPage from "@/pages/Notifications";
import ActivityLogs from "@/pages/ActivityLogs";
import AboutWavygo from "@/pages/AboutWavygo";
import CompanyVault from "@/pages/CompanyVault";
import Finance from "@/pages/Finance";
import CRM from "@/pages/CRM";
import Marketing from "@/pages/Marketing";
import Analytics from "@/pages/Analytics";
import WavygoAI from "@/pages/WavygoAI";
import Marketplace from "@/pages/Marketplace";
import TaskBoard from "@/pages/TaskBoard";
import Employees from "@/pages/Employees";
import OpportunityHub from "@/pages/OpportunityHub";
import WavygoConnect from "@/pages/WavygoConnect";
import CalendarPage from "@/pages/Calendar";

function Shell({ children, module }) {
  return (
    <ProtectedRoute allowedModule={module}>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/login" element={<Login />} />
            <Route path="/accept-invite" element={<AcceptInvite />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/dashboard"       element={<Shell module="dashboard"><Dashboard /></Shell>} />
            <Route path="/marketplace"     element={<Shell module="marketplace"><Marketplace /></Shell>} />
            <Route path="/task-board"      element={<Shell module="task-board"><TaskBoard /></Shell>} />
            <Route path="/employees"       element={<Shell module="employees"><Employees /></Shell>} />
            <Route path="/opportunity-hub" element={<Shell module="opportunity-hub"><OpportunityHub /></Shell>} />
            <Route path="/wavygo-connect"  element={<Shell module="wavygo-connect"><WavygoConnect /></Shell>} />
            <Route path="/calendar"        element={<Shell module="calendar"><CalendarPage /></Shell>} />
            <Route path="/settings"        element={<Shell module="settings"><Settings /></Shell>} />
            <Route path="/notifications"   element={<Shell module="notifications"><NotificationsPage /></Shell>} />
            <Route path="/activity-logs"   element={<Shell module="activity-logs"><ActivityLogs /></Shell>} />
            <Route path="/about-wavygo"    element={<Shell module="about-wavygo"><AboutWavygo /></Shell>} />
            <Route path="/company-vault"  element={<Shell module="company-vault"><CompanyVault /></Shell>} />
            <Route path="/finance"        element={<Shell module="finance"><Finance /></Shell>} />
            <Route path="/crm"            element={<Shell module="crm"><CRM /></Shell>} />
            <Route path="/marketing"      element={<Shell module="marketing"><Marketing /></Shell>} />
            <Route path="/analytics"      element={<Shell module="analytics"><Analytics /></Shell>} />
            <Route path="/wavygo-ai"      element={<Shell module="wavygo-ai"><WavygoAI /></Shell>} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
          <Toaster richColors position="bottom-right" />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
