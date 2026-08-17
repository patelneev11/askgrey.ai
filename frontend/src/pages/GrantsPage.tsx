import { PageCanvas } from '@/components/PageCanvas';

import styles from './GrantsPage.module.css';
import { BudgetPlanner } from './grants/BudgetPlanner';
import { EligibilityChecklist } from './grants/EligibilityChecklist';
import { OpportunityFinder } from './grants/OpportunityFinder';
import { ReviewBoard } from './grants/ReviewBoard';

export function GrantsPage() {
  return (
    <PageCanvas
      title="Grants"
      description="Search federal opportunities, screen eligibility against the encoded SBIR/STTR rules, cost a budget into SF-424 (R&R) shape, and put a draft section in front of a mock review board."
    >
      <div className={styles.stack}>
        <OpportunityFinder />
        <EligibilityChecklist />
        <BudgetPlanner />
        <ReviewBoard />
      </div>
    </PageCanvas>
  );
}
