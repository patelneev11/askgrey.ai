import type { ReactNode } from 'react';

import styles from './marketing.module.css';
import { useReveal } from './useReveal';

interface SectionProps {
  id?: string;
  eyebrow?: string;
  title: string;
  lead?: ReactNode;
  children?: ReactNode;
}

/** A marketing section that fades in the first time it scrolls into view. */
export function Section({ id, eyebrow, title, lead, children }: SectionProps) {
  const ref = useReveal<HTMLElement>();

  return (
    <section id={id} className={styles.section} ref={ref}>
      {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
      <h2 className={styles.sectionTitle}>{title}</h2>
      {lead && <p className={styles.sectionLead}>{lead}</p>}
      {children}
    </section>
  );
}
