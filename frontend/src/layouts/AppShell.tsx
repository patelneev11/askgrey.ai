import { useState } from 'react';
import { Outlet } from 'react-router-dom';

import { FirstRunTour } from '@/components/FirstRunTour';
import { TabIntroHost } from '@/components/TabIntro';
import { useAuth } from '@/lib/auth-context';

import styles from './AppShell.module.css';
import { Sidebar } from './Sidebar';

const SIDEBAR_STORAGE_KEY = 'askgrey:sidebar-collapsed';

export function AppShell() {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(
    () => window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true',
  );

  const toggle = () => {
    setCollapsed((current) => {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(!current));
      return !current;
    });
  };

  return (
    <div className={styles.shell}>
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <div className={styles.main}>
        <header className={styles.topbar}>
          <span className={styles.workspaceName}>Workspace</span>
          <div className={styles.identity}>
            <span className={styles.email}>{user?.email}</span>
            <button type="button" className={styles.signOut} onClick={logout}>
              Sign out
            </button>
          </div>
        </header>
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
      <FirstRunTour />
      <TabIntroHost />
    </div>
  );
}
