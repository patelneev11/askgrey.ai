import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import { FirstRunTour } from '@/components/FirstRunTour';
import { Icon } from '@/components/icons';
import { TabIntroHost } from '@/components/TabIntro';
import { useAuth } from '@/lib/auth-context';
import { useIsCompact } from '@/lib/useMediaQuery';

import styles from './AppShell.module.css';
import { Sidebar } from './Sidebar';

const SIDEBAR_STORAGE_KEY = 'askgrey:sidebar-collapsed';

export function AppShell() {
  const { user, logout } = useAuth();
  const compact = useIsCompact();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(
    () => window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true',
  );
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggle = () => {
    setCollapsed((current) => {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(!current));
      return !current;
    });
  };

  // A tap on a destination has to leave the drawer, or the page it opened is behind it.
  useEffect(() => setDrawerOpen(false), [location.pathname]);
  useEffect(() => {
    if (!compact) setDrawerOpen(false);
  }, [compact]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [drawerOpen]);

  return (
    <div className={styles.shell} data-compact={compact || undefined}>
      {drawerOpen && (
        <button
          type="button"
          className={styles.scrim}
          aria-label="Close navigation"
          onClick={() => setDrawerOpen(false)}
        />
      )}
      <Sidebar
        collapsed={compact ? false : collapsed}
        onToggle={toggle}
        drawer={compact}
        drawerOpen={drawerOpen}
      />
      <div className={styles.main}>
        <header className={styles.topbar}>
          {compact ? (
            <button
              type="button"
              className={styles.menuButton}
              onClick={() => setDrawerOpen((open) => !open)}
              aria-expanded={drawerOpen}
              aria-label={drawerOpen ? 'Close navigation' : 'Open navigation'}
            >
              <Icon name={drawerOpen ? 'close' : 'menu'} size={20} />
            </button>
          ) : (
            <span className={styles.workspaceName}>Workspace</span>
          )}
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
