import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { AppShell } from '@/layouts/AppShell';
import { AuthProvider } from '@/lib/auth';
import { useAuth } from '@/lib/auth-context';
import { isMarketingHost } from '@/lib/hosts';
import { OnboardingProvider } from '@/lib/onboarding';
import { WorkspaceProvider } from '@/lib/workspace';
import { MarketingSite } from '@/marketing/MarketingSite';
import { AuditPage } from '@/pages/AuditPage';
import { ChatPage } from '@/pages/ChatPage';
import { GrantsPage } from '@/pages/GrantsPage';
import { LiteraturePage } from '@/pages/LiteraturePage';
import { LoginPage } from '@/pages/LoginPage';
import { ProtocolPage } from '@/pages/ProtocolPage';
import { RegulatoryPage } from '@/pages/RegulatoryPage';
import { RegulatoryProvider } from '@/pages/regulatory/state';
import { ScreeningPage } from '@/pages/ScreeningPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { TermsPage } from '@/pages/TermsPage';
import { WorkspacePage } from '@/pages/WorkspacePage';

function RequireAuth({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return null;
  }
  if (!user) {
    // The query string comes back too: an emailed invitation carries its token there, and a
    // recipient who has to register first would otherwise arrive at a bare page.
    return (
      <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />
    );
  }
  return children;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Outside the auth guard: the terms have to be readable before there is an account to
          accept them with. */}
      <Route path="/terms" element={<TermsPage />} />
      <Route
        element={
          <RequireAuth>
            <OnboardingProvider>
              <WorkspaceProvider>
                <RegulatoryProvider>
                  <AppShell />
                </RegulatoryProvider>
              </WorkspaceProvider>
            </OnboardingProvider>
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/literature" replace />} />
        <Route path="/assistant" element={<ChatPage />} />
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
  // One bundle, two hostnames: the public site on the marketing host, the signed-in product on
  // its own. The product's routes are never mounted on the public host, so there is no page
  // there that could redirect a visitor into an auth guard.
  if (isMarketingHost(window.location)) {
    return (
      <BrowserRouter>
        <MarketingSite />
      </BrowserRouter>
    );
  }

  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
