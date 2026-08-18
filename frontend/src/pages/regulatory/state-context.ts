import { createContext, useContext } from 'react';

import type { GuidelineController } from './GuidelineView';
import type { IndController } from './IndView';
import type { PreclinicalController } from './PreclinicalView';

export type RegulatoryFeature = 'preclinical' | 'ind' | 'guidelines';

export interface RegulatoryState {
  preclinical: PreclinicalController;
  ind: IndController;
  guidelines: GuidelineController;
  feature: RegulatoryFeature;
  setFeature: (feature: RegulatoryFeature) => void;
  /**
   * Lets the reference data load only once the tab is actually opened, so a researcher who never
   * touches Regulatory never pays for the CTD tree or the guideline listing.
   */
  activate: () => void;
}

export const RegulatoryContext = createContext<RegulatoryState | null>(null);

export function useRegulatory(): RegulatoryState {
  const state = useContext(RegulatoryContext);
  if (!state) {
    throw new Error('useRegulatory requires <RegulatoryProvider>');
  }
  return state;
}
