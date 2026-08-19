import { useCallback, useMemo, useState, type ReactNode } from 'react';

import { useGuidelines } from './GuidelineView';
import { useIndDraft } from './IndView';
import { usePreclinical } from './PreclinicalView';
import {
  RegulatoryContext,
  type RegulatoryFeature,
  type RegulatoryState,
} from './state-context';

/**
 * Holds the Regulatory tab's working state above the router.
 *
 * A drafted narrative costs a model call and a study record costs a researcher's typing, and both
 * used to be destroyed by a single click on another tab. Keeping the controllers here means the
 * route can unmount freely.
 *
 * Memory only, deliberately: study records and manufacturing data are the most sensitive input in
 * the product, so none of it is written to localStorage or sessionStorage, where any injected
 * script could read it and where it would outlive the session. Signing out or reloading discards
 * it, which is the trade this tab should make.
 */
export function RegulatoryProvider({ children }: { children: ReactNode }) {
  const [feature, setFeature] = useState<RegulatoryFeature>('preclinical');
  const [visited, setVisited] = useState(false);
  const preclinical = usePreclinical();
  const ind = useIndDraft(visited);
  const guidelines = useGuidelines(visited);
  const activate = useCallback(() => setVisited(true), []);

  const value = useMemo<RegulatoryState>(
    () => ({ preclinical, ind, guidelines, feature, setFeature, activate }),
    [preclinical, ind, guidelines, feature, activate],
  );

  return <RegulatoryContext.Provider value={value}>{children}</RegulatoryContext.Provider>;
}
