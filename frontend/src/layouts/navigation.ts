export interface NavItem {
  label: string;
  to: string;
  /** Single-glyph mark shown when the sidebar is collapsed to its icon rail. */
  glyph: string;
}

/** Core operational tabs, in workflow order: discovery through funding. */
export const OPERATIONAL_TABS: NavItem[] = [
  { label: 'Literature', to: '/literature', glyph: 'L' },
  { label: 'Screening', to: '/screening', glyph: 'S' },
  { label: 'Protocol Creation', to: '/protocol', glyph: 'P' },
  { label: 'Regulatory', to: '/regulatory', glyph: 'R' },
  { label: 'Grants', to: '/grants', glyph: 'G' },
];

export const WORKSPACE_LINKS: NavItem[] = [
  { label: 'Workspace Profile', to: '/workspace', glyph: 'W' },
  { label: 'Audit Trails', to: '/audit', glyph: 'A' },
  { label: 'Settings', to: '/settings', glyph: '=' },
];
