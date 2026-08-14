import { NavLink } from 'react-router-dom';

import { OPERATIONAL_TABS, WORKSPACE_LINKS, type NavItem } from './navigation';
import styles from './Sidebar.module.css';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

function SidebarLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  return (
    <NavLink
      to={item.to}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) => [styles.link, isActive ? styles.linkActive : ''].join(' ')}
    >
      <span className={styles.glyph} aria-hidden="true">
        {item.glyph}
      </span>
      <span className={styles.linkLabel}>{item.label}</span>
    </NavLink>
  );
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <nav
      className={[styles.sidebar, collapsed ? styles.collapsed : ''].join(' ')}
      aria-label="Primary"
      data-collapsed={collapsed}
    >
      <div className={styles.brand}>
        <span className={styles.brandMark} aria-hidden="true">
          ag
        </span>
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
        className={styles.toggle}
        onClick={onToggle}
        aria-expanded={!collapsed}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <span className={styles.glyph} aria-hidden="true">
          {collapsed ? '»' : '«'}
        </span>
        <span className={styles.linkLabel}>Collapse</span>
      </button>
    </nav>
  );
}
