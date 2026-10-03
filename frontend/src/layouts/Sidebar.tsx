import { NavLink } from 'react-router-dom';

import { BrandMark } from '@/components/BrandMark';
import { Icon } from '@/components/icons';

import { OPERATIONAL_TABS, WORKSPACE_LINKS, type NavItem } from './navigation';
import styles from './Sidebar.module.css';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  /** On a phone the rail is an off-canvas drawer instead of a column of the layout. */
  drawer?: boolean;
  drawerOpen?: boolean;
}

function SidebarLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  return (
    <NavLink
      to={item.to}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) => [styles.link, isActive ? styles.linkActive : ''].join(' ')}
    >
      <span className={styles.glyph}>
        <Icon name={item.icon} />
      </span>
      <span className={styles.linkLabel}>{item.label}</span>
    </NavLink>
  );
}

export function Sidebar({ collapsed, onToggle, drawer = false, drawerOpen = false }: SidebarProps) {
  return (
    <nav
      className={[
        styles.sidebar,
        collapsed ? styles.collapsed : '',
        drawer ? styles.drawer : '',
        drawer && drawerOpen ? styles.drawerOpen : '',
      ].join(' ')}
      aria-label="Primary"
      aria-hidden={drawer && !drawerOpen}
      data-collapsed={collapsed}
      data-drawer-open={drawer ? drawerOpen : undefined}
    >
      <div className={styles.brand}>
        <BrandMark className={styles.brandMark} aria-hidden="true" role="presentation" />
        <span className={styles.brandName}>askgrey</span>
      </div>

      <div className={styles.group}>
        {OPERATIONAL_TABS.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}
      </div>

      <div className={styles.spacer} />

      <div className={styles.group}>
        {WORKSPACE_LINKS.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}
      </div>

      <button
        type="button"
        className={[styles.toggle, drawer ? styles.toggleHidden : ''].join(' ')}
        onClick={onToggle}
        aria-expanded={!collapsed}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <span className={styles.glyph}>
          <Icon name={collapsed ? 'chevronRight' : 'chevronLeft'} />
        </span>
        <span className={styles.linkLabel}>Collapse</span>
      </button>
    </nav>
  );
}
