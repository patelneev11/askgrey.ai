import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { AppShell } from '@/layouts/AppShell';
import { AuthProvider } from '@/lib/auth';
import { useAuth } from '@/lib/auth-context';
import { WorkspaceProvider } from '@/lib/workspace';
import { AuditPage } from '@/pages/AuditPage';
import { GrantsPage } from '@/pages/GrantsPage';
import { LiteraturePage } from '@/pages/LiteraturePage';
import { LoginPage } from '@/pages/LoginPage';
import { ProtocolPage } from '@/pages/ProtocolPage';
import { RegulatoryPage } from '@/pages/RegulatoryPage';
import { ScreeningPage } from '@/pages/ScreeningPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { WorkspacePage } from '@/pages/WorkspacePage';

function RequireAuth({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return null;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <WorkspaceProvider>
              <AppShell />
            </WorkspaceProvider>
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/literature" replace />} />
        <Route path="/literature" element={<LiteraturePage />} />
        <Route path="/screening" element={<ScreeningPage />} />
        <Route path="/protocol" element={<ProtocolPage />} />
        <Route path="/regulatory" element={<RegulatoryPage />} />
        <Route path="/grants" element={<GrantsPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
