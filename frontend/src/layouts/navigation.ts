import type { IconName } from '@/components/icons';

export interface NavItem {
  label: string;
  to: string;
  /** Icon shown beside the label, and alone when the sidebar collapses to its rail. */
  icon: IconName;
}

/** Core operational tabs, in workflow order: discovery through funding. */
export const OPERATIONAL_TABS: NavItem[] = [
  { label: 'Literature', to: '/literature', icon: 'literature' },
  { label: 'Screening', to: '/screening', icon: 'screening' },
  { label: 'Protocol Creation', to: '/protocol', icon: 'protocol' },
  { label: 'Regulatory', to: '/regulatory', icon: 'regulatory' },
  { label: 'Grants', to: '/grants', icon: 'grants' },
];

export const WORKSPACE_LINKS: NavItem[] = [
  { label: 'Workspace Profile', to: '/workspace', icon: 'workspace' },
  { label: 'Audit Trails', to: '/audit', icon: 'audit' },
  { label: 'Settings', to: '/settings', icon: 'settings' },
];
