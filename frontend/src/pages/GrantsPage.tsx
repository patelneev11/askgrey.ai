import { EmptyState } from '@/components/EmptyState';
import { PageCanvas } from '@/components/PageCanvas';
import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';

import styles from './GrantsPage.module.css';
import { BudgetPlanner } from './grants/BudgetPlanner';
import { EligibilityChecklist } from './grants/EligibilityChecklist';
import { OpportunityFinder } from './grants/OpportunityFinder';

export function GrantsPage() {
  return (
    <PageCanvas
      title="Grants"
      description="Search federal opportunities, screen eligibility against the encoded SBIR/STTR rules, and cost a budget into SF-424 (R&R) shape."
    >
      <div className={styles.stack}>
        <OpportunityFinder />
        <EligibilityChecklist />
        <BudgetPlanner />
        <Panel
          title="Mock review board"
          actions={<StatusPill tone="idle">Not wired up yet</StatusPill>}
        >
          <EmptyState title="No review board endpoint yet">
            Persona critiques and NIH-style scores are being built behind{' '}
            <code>/api/grants/review-board</code>. Nothing is shown here until that endpoint
            answers — a sample score set would read as a real review of your draft.
          </EmptyState>
        </Panel>
      </div>
    </PageCanvas>
  );
}
