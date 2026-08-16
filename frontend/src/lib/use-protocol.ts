import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from './api';
import { logger } from './observability';
import {
  reorderSteps,
  type ChecklistItem,
  type ElnExportPayload,
  type MasterMixResult,
  type ProtocolDraft,
  type ProtocolHistory,
  type ProtocolReview,
  type ProtocolStep,
} from './protocols';
import { getAccessToken } from './session';

export interface MixRow {
  id: string;
  name: string;
  volume: string;
  unit: string;
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

const EMPTY_MIX: MixRow[] = [
  { id: 'mix-1', name: '', volume: '', unit: 'uL' },
  { id: 'mix-2', name: '', volume: '', unit: 'uL' },
];

/**
 * All Protocol-tab state: the draft, the researcher's edits, the control review, the inline
 * calculator and the ELN payload.
 *
 * Nothing here is seeded with invented content. A field the researcher has not filled in stays
 * empty rather than being pre-populated with a plausible-looking value.
 */
export function useProtocolWorkspace() {
  const [goal, setGoal] = useState('');
  const [sample, setSample] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState<ProtocolDraft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [savedId, setSavedId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<ProtocolHistory | null>(null);

  const [review, setReview] = useState<ProtocolReview | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [checklist, setChecklist] = useState<ChecklistItem[]>([]);

  const [mix, setMix] = useState<MixRow[]>(EMPTY_MIX);
  const [batchScale, setBatchScale] = useState(24);
  const [mixResult, setMixResult] = useState<MasterMixResult | null>(null);
  const [mixError, setMixError] = useState<string | null>(null);

  const [exportPayload, setExportPayload] = useState<ElnExportPayload | null>(null);
  const [exporting, setExporting] = useState(false);
  const draftRef = useRef<ProtocolDraft | null>(null);

  const applyDraft = useCallback((next: ProtocolDraft | null) => {
    draftRef.current = next;
    setDraft(next);
  }, []);

  const generate = useCallback(async () => {
    if (goal.trim().length < 10) {
      setError('Describe the experiment in a sentence or more before drafting.');
      return;
    }
    setDrafting(true);
    setError(null);
    try {
      const next = await api.draftProtocol(
        { goal: goal.trim(), organism_or_sample: sample.trim() },
        getAccessToken(),
      );
      applyDraft(next);
      setSavedId(null);
      setVersion(null);
      setDirty(false);
      setReview(null);
      setExportPayload(null);
      setHistory(null);
      // Deterministic, so it costs nothing and can load with the draft.
      setChecklist(await api.reagentChecklist(next, getAccessToken()));
    } catch (cause) {
      logger.warn('protocol.draft_failed', { message: message(cause, 'unknown') });
      setError(message(cause, 'Drafting failed.'));
    } finally {
      setDrafting(false);
    }
  }, [applyDraft, goal, sample]);

  const editStep = useCallback(
    (id: string, field: keyof ProtocolStep, value: string) => {
      const current = draftRef.current;
      if (!current) return;
      applyDraft({
        ...current,
        steps: current.steps.map((step) => (step.id === id ? { ...step, [field]: value } : step)),
      });
      setDirty(true);
    },
    [applyDraft],
  );

  const moveStep = useCallback(
    (index: number, delta: number) => {
      const current = draftRef.current;
      if (!current) return;
      const steps = reorderSteps(current.steps, index, index + delta);
      if (steps === current.steps) return;
      applyDraft({ ...current, steps });
      setDirty(true);
    },
    [applyDraft],
  );

  const save = useCallback(async () => {
    const current = draftRef.current;
    if (!current) return;
    setSaving(true);
    setError(null);
    try {
      const saved = savedId
        ? await api.updateProtocol(savedId, current, '', getAccessToken())
        : await api.saveProtocol(current, '', getAccessToken());
      setSavedId(saved.id);
      setVersion(saved.version);
      // The server owns `origin`: saving an edit is what makes it researcher-edited.
      applyDraft(saved.protocol);
      setDirty(false);
      setHistory(await api.protocolHistory(saved.id, getAccessToken()));
    } catch (cause) {
      setError(message(cause, 'Saving failed.'));
    } finally {
      setSaving(false);
    }
  }, [applyDraft, savedId]);

  const reviewControls = useCallback(async () => {
    const current = draftRef.current;
    if (!current) return;
    setReviewing(true);
    setError(null);
    try {
      const next = await api.reviewControls(current, getAccessToken());
      setReview(next);
      if (next.reagent_checklist.length > 0) setChecklist(next.reagent_checklist);
    } catch (cause) {
      setError(message(cause, 'Control review failed.'));
    } finally {
      setReviewing(false);
    }
  }, []);

  const exportEln = useCallback(async (folderId: string) => {
    const current = draftRef.current;
    if (!current) return;
    setExporting(true);
    setError(null);
    try {
      setExportPayload(await api.exportEln(current, folderId.trim(), getAccessToken()));
    } catch (cause) {
      setError(message(cause, 'Export failed.'));
    } finally {
      setExporting(false);
    }
  }, []);

  const editMix = useCallback((id: string, field: 'name' | 'volume' | 'unit', value: string) => {
    setMix((rows) => rows.map((row) => (row.id === id ? { ...row, [field]: value } : row)));
  }, []);

  const addMixRow = useCallback(() => {
    setMix((rows) => [
      ...rows,
      { id: `mix-${rows.length + 1}-${Date.now()}`, name: '', volume: '', unit: 'uL' },
    ]);
  }, []);

  // Live recalculation: any change to the recipe or the sample/well count re-solves the mix
  // server-side, because the arithmetic must be the same deterministic code the API tests cover
  // rather than a second implementation in the browser.
  useEffect(() => {
    const filled = mix.filter((row) => row.name.trim() !== '' && row.volume.trim() !== '');
    if (filled.length === 0) {
      setMixResult(null);
      setMixError(null);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const response = await api.recalculate(
          [
            {
              id: 'master-mix',
              master_mix: {
                components: filled.map((row) => ({
                  name: row.name.trim(),
                  per_reaction_volume: { value: row.volume.trim(), unit: row.unit },
                })),
                reactions: batchScale,
              },
            },
          ],
          batchScale,
          getAccessToken(),
        );
        if (cancelled) return;
        const outcome = response.outcomes[0];
        setMixResult(outcome?.result ?? null);
        setMixError(outcome?.error ?? null);
      } catch (cause) {
        if (!cancelled) {
          setMixResult(null);
          setMixError(message(cause, 'Recalculation failed.'));
        }
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [batchScale, mix]);

  return {
    goal,
    sample,
    drafting,
    draft,
    error,
    savedId,
    version,
    dirty,
    saving,
    history,
    review,
    reviewing,
    checklist,
    mix,
    batchScale,
    mixResult,
    mixError,
    exportPayload,
    exporting,
    setGoal,
    setSample,
    setBatchScale,
    generate,
    editStep,
    moveStep,
    save,
    reviewControls,
    exportEln,
    editMix,
    addMixRow,
  };
}
