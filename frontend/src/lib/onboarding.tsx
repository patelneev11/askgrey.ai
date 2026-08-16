import { useCallback, useMemo, useState, type ReactNode } from 'react';

import { OnboardingContext, type OnboardingState, type TourStatus } from './onboarding-context';
import { logger } from './observability';

const STORAGE_KEY = 'askgrey:onboarding:v1';

const EMPTY: OnboardingState = { tour: 'unseen', step: 0, acknowledged: [] };

function isTourStatus(value: unknown): value is TourStatus {
  return value === 'unseen' || value === 'skipped' || value === 'completed';
}

/**
 * Onboarding state is a convenience, not a record: a browser that cannot parse it, or that has
 * no storage at all, gets the first run again rather than an error.
 */
function read(): OnboardingState {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return EMPTY;
  }
  if (!raw) return EMPTY;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return EMPTY;
    const record = parsed as Record<string, unknown>;
    const acknowledged = Array.isArray(record.acknowledged)
      ? record.acknowledged.filter((entry): entry is string => typeof entry === 'string')
      : [];
    return {
      tour: isTourStatus(record.tour) ? record.tour : 'unseen',
      step: typeof record.step === 'number' && record.step >= 0 ? Math.floor(record.step) : 0,
      acknowledged,
    };
  } catch {
    return EMPTY;
  }
}

function write(state: OnboardingState): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Private-mode or quota failures must not break the app; the tour simply reappears.
  }
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<OnboardingState>(read);

  const update = useCallback((next: OnboardingState) => {
    write(next);
    setState(next);
  }, []);

  const value = useMemo(
    () => ({
      ...state,
      // A user who closed the tab mid-tour comes back to the step they left, not to step one.
      goToStep: (step: number) => update({ ...state, step: Math.max(0, step) }),
      skipTour: () => {
        logger.info('onboarding.skipped', { step: state.step });
        update({ ...state, tour: 'skipped' });
      },
      completeTour: () => {
        logger.info('onboarding.completed', { step: state.step });
        update({ ...state, tour: 'completed', step: 0 });
      },
      restartTour: () => update({ ...state, tour: 'unseen', step: 0 }),
      acknowledge: (id: string) => {
        if (state.acknowledged.includes(id)) return;
        logger.info('onboarding.acknowledged', { surface: id });
        update({ ...state, acknowledged: [...state.acknowledged, id] });
      },
      hasAcknowledged: (id: string) => state.acknowledged.includes(id),
    }),
    [state, update],
  );

  return <OnboardingContext.Provider value={value}>{children}</OnboardingContext.Provider>;
}
