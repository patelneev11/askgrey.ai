import { createContext, useContext } from 'react';

export type TourStatus = 'unseen' | 'skipped' | 'completed';

export interface OnboardingState {
  tour: TourStatus;
  /** Where an interrupted tour resumes; meaningless once the tour is finished. */
  step: number;
  /** Ids of the per-tab notices whose caveats the user has read and accepted. */
  acknowledged: string[];
}

export interface OnboardingContextValue extends OnboardingState {
  goToStep: (step: number) => void;
  skipTour: () => void;
  completeTour: () => void;
  restartTour: () => void;
  acknowledge: (id: string) => void;
  hasAcknowledged: (id: string) => boolean;
}

export const OnboardingContext = createContext<OnboardingContextValue | null>(null);

export function useOnboarding(): OnboardingContextValue {
  const context = useContext(OnboardingContext);
  if (!context) {
    throw new Error('useOnboarding must be used inside an OnboardingProvider');
  }
  return context;
}
