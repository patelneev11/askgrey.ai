import { useEffect, useMemo, type ReactNode } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { Panel } from '@/components/Panel';
import { DualPaneWorkspace } from '@/layouts/DualPaneWorkspace';

import { GuidelineForm, GuidelineOutput, type DraftSource } from './regulatory/GuidelineView';
import { IndForm, IndOutput } from './regulatory/IndView';
import { PreclinicalForm, PreclinicalOutput } from './regulatory/PreclinicalView';
import styles from './regulatory/regulatory.module.css';
import { useRegulatory, type RegulatoryFeature } from './regulatory/state-context';

/**
 * The banner every generated view in this tab carries, verbatim.
 *
 * Exported so the disclaimer tests assert the same string the UI renders, and duplicated into
 * both panes: a reviewer scrolling a long draft must not be able to leave the warning behind.
 */
export const REGULATORY_REVIEW_NOTICE =
  'Agent-drafted content. Requires qualified regulatory affairs review before any regulatory use.';

const FEATURES: {
  id: RegulatoryFeature;
  label: string;
  inputs: string;
  output: string;
}[] = [
  {
    id: 'preclinical',
    label: 'Preclinical report',
    inputs: 'Study record',
    output: 'Drafted narrative · numeric audit',
  },
  {
    id: 'ind',
    label: 'IND module 3 / 4',
    inputs: 'Sections and submitted data',
    output: 'Drafted sections · stated gaps',
  },
  {
    id: 'guidelines',
    label: 'Guideline check',
    inputs: 'Draft section',
    output: 'Per-jurisdiction findings',
  },
];

interface SlotProps {
  active: boolean;
  /** Names the region so each sub-feature's inputs and output are addressable on their own. */
  label: string;
  children: ReactNode;
}

/** Inactive features stay mounted so switching sub-features does not discard entered data. */
function Slot({ active, label, children }: SlotProps) {
  return (
    <section aria-label={label} hidden={!active}>
      {children}
    </section>
  );
}

export function RegulatoryPage() {
  // State lives in `RegulatoryProvider`, above the router, so leaving the tab and coming back
  // does not throw away an entered study or a drafted narrative.
  const { preclinical, ind, guidelines, feature, setFeature, activate } = useRegulatory();
  const active = FEATURES.find((entry) => entry.id === feature) ?? FEATURES[0];

  useEffect(activate, [activate]);

  // Anything already drafted in this tab can be checked directly, rather than the user
  // re-typing a section and checking something subtly different from what was drafted.
  const draftSources = useMemo<DraftSource[]>(
    () => [
      ...(preclinical.report?.sections ?? [])
        .filter((section) => section.text.length > 0)
        .map((section) => ({
          id: section.key,
          label: `Preclinical · ${section.heading}`,
          text: section.text,
        })),
      ...(ind.draft?.sections ?? [])
        .filter((section) => section.text.length > 0)
        .map((section) => ({
          id: section.section_id,
          label: `IND · ${section.section_id} ${section.title}`,
          text: section.text,
        })),
    ],
    [preclinical.report, ind.draft],
  );

  const tabs = (
    <div className={styles.tabs} role="tablist" aria-label="Regulatory drafting aids">
      {FEATURES.map((entry) => (
        <Button
          key={entry.id}
          size="sm"
          variant={entry.id === feature ? 'primary' : 'ghost'}
          role="tab"
          aria-selected={entry.id === feature}
          onClick={() => setFeature(entry.id)}
        >
          {entry.label}
        </Button>
      ))}
    </div>
  );

  return (
    <DualPaneWorkspace
      storageKey="regulatory"
      defaultRatio={0.45}
      leftLabel="Regulatory inputs"
      rightLabel="Drafted output"
      left={
        <Panel title={active.inputs} actions={tabs} className={styles.fill} flush>
          <div className={styles.pane}>
            <div className={styles.sticky}>
              <CaveatBand label="Draft">{REGULATORY_REVIEW_NOTICE}</CaveatBand>
            </div>
            <div className={styles.scroll}>
              <Slot active={feature === 'preclinical'} label="Preclinical inputs">
                <PreclinicalForm controller={preclinical} />
              </Slot>
              <Slot active={feature === 'ind'} label="IND inputs">
                <IndForm controller={ind} />
              </Slot>
              <Slot active={feature === 'guidelines'} label="Guideline inputs">
                <GuidelineForm controller={guidelines} sources={draftSources} />
              </Slot>
            </div>
          </div>
        </Panel>
      }
      right={
        <Panel title={active.output} className={styles.fill} flush>
          <div className={styles.pane}>
            <div className={styles.sticky}>
              <CaveatBand label="Draft">{REGULATORY_REVIEW_NOTICE}</CaveatBand>
            </div>
            <div className={styles.scroll}>
              <Slot active={feature === 'preclinical'} label="Preclinical output">
                <PreclinicalOutput controller={preclinical} />
              </Slot>
              <Slot active={feature === 'ind'} label="IND output">
                <IndOutput controller={ind} />
              </Slot>
              <Slot active={feature === 'guidelines'} label="Guideline output">
                <GuidelineOutput controller={guidelines} />
              </Slot>
            </div>
          </div>
        </Panel>
      }
    />
  );
}
