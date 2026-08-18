import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { SavedLibrary } from '@/components/SavedLibrary';
import { StatusPill } from '@/components/StatusPill';
import {
  api,
  type EvidenceKind,
  type EvidenceRecord,
  type IndDraft,
  type IndStructure,
} from '@/lib/api';
import { getAccessToken } from '@/lib/session';

import { errorMessage } from './errors';
import { Row, RowGroup, SelectField, TextField } from './fields';
import styles from './regulatory.module.css';

const MAX_SECTIONS = 12;

const EVIDENCE_KINDS: { value: EvidenceKind; label: string }[] = [
  { value: 'substance_identity', label: 'Substance identity' },
  { value: 'manufacturing_site', label: 'Manufacturing site' },
  { value: 'manufacturing_step', label: 'Manufacturing step' },
  { value: 'material_control', label: 'Material control' },
  { value: 'specification', label: 'Specification' },
  { value: 'analytical_method', label: 'Analytical method' },
  { value: 'assay_result', label: 'Assay result' },
  { value: 'batch', label: 'Batch' },
  { value: 'impurity', label: 'Impurity' },
  { value: 'stability_result', label: 'Stability result' },
  { value: 'reference_standard', label: 'Reference standard' },
  { value: 'container_closure', label: 'Container closure' },
  { value: 'formulation', label: 'Formulation' },
  { value: 'nonclinical_study', label: 'Nonclinical study' },
];

interface EvidenceDraft {
  kind: EvidenceKind;
  label: string;
  value: string;
  unit: string;
  batchId: string;
  studyId: string;
  sectionId: string;
  detail: string;
}

const emptyEvidence: EvidenceDraft = {
  kind: 'assay_result',
  label: '',
  value: '',
  unit: '',
  batchId: '',
  studyId: '',
  sectionId: '',
  detail: '',
};

const STATUS_LABEL: Record<IndDraft['sections'][number]['status'], string> = {
  drafted: 'first draft',
  drafted_with_gaps: 'first draft · gaps',
  not_drafted: 'not drafted',
};

export function useIndDraft() {
  const [structure, setStructure] = useState<IndStructure | null>(null);
  const [structureError, setStructureError] = useState<string | null>(null);
  const [program, setProgram] = useState({
    programName: '',
    substanceName: '',
    dosageForm: '',
  });
  const [selected, setSelected] = useState<string[]>([]);
  const [evidence, setEvidence] = useState<EvidenceDraft[]>([{ ...emptyEvidence }]);
  const [draft, setDraft] = useState<IndDraft | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The section list is the dated CTD transcription the backend owns; the UI never hardcodes it.
  useEffect(() => {
    let live = true;
    api
      .indStructure(getAccessToken())
      .then((loaded) => {
        if (live) setStructure(loaded);
      })
      .catch((cause: unknown) => {
        if (live) setStructureError(errorMessage(cause));
      });
    return () => {
      live = false;
    };
  }, []);

  const toggleSection = useCallback((id: string) => {
    setSelected((prev) =>
      prev.includes(id)
        ? prev.filter((existing) => existing !== id)
        : prev.length >= MAX_SECTIONS
          ? prev
          : [...prev, id],
    );
  }, []);

  const submit = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const records: EvidenceRecord[] = evidence
        .filter((record) => record.label.trim().length > 0)
        .map((record) => ({
          kind: record.kind,
          label: record.label.trim(),
          value: record.value.trim(),
          unit: record.unit.trim(),
          batch_id: record.batchId.trim(),
          study_id: record.studyId.trim(),
          section_id: record.sectionId.trim(),
          detail: record.detail.trim(),
        }));

      setDraft(
        await api.indDraft(
          {
            program_name: program.programName.trim(),
            substance_name: program.substanceName.trim(),
            dosage_form: program.dosageForm.trim(),
            section_ids: selected,
            evidence: records,
          },
          getAccessToken(),
        ),
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setRunning(false);
    }
  }, [program, selected, evidence]);

  return {
    structure,
    structureError,
    program,
    setProgram,
    selected,
    toggleSection,
    evidence,
    setEvidence,
    draft,
    setDraft,
    running,
    error,
    submit,
  };
}

export type IndController = ReturnType<typeof useIndDraft>;

function replace(rows: EvidenceDraft[], index: number, patch: Partial<EvidenceDraft>) {
  return rows.map((row, position) => (position === index ? { ...row, ...patch } : row));
}

export function IndForm({ controller }: { controller: IndController }) {
  const {
    structure,
    structureError,
    program,
    setProgram,
    selected,
    toggleSection,
    evidence,
    setEvidence,
    running,
    error,
    submit,
  } = controller;

  const canSubmit = !running && program.programName.trim().length > 0 && selected.length > 0;

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <TextField
        label="Programme"
        value={program.programName}
        onChange={(value) => setProgram((prev) => ({ ...prev, programName: value }))}
        maxLength={200}
        required
      />
      <TextField
        label="Substance"
        value={program.substanceName}
        onChange={(value) => setProgram((prev) => ({ ...prev, substanceName: value }))}
        maxLength={200}
      />
      <TextField
        label="Dosage form"
        value={program.dosageForm}
        onChange={(value) => setProgram((prev) => ({ ...prev, dosageForm: value }))}
        maxLength={200}
      />

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Sections to draft</legend>
        {structure ? (
          <>
            <p className={styles.hint}>
              CTD headings as transcribed on {structure.reference.retrieved} (version{' '}
              {structure.reference.version}). Choosing a heading does not mean an IND requires it —
              what an IND must contain is governed by 21 CFR 312.23, not by this tree. Up to{' '}
              {MAX_SECTIONS} sections per draft.
            </p>
            <ul className={styles.checkGrid}>
              {structure.sections.map((section) => (
                <li key={section.id}>
                  <label
                    className={[styles.check, section.draftable ? '' : styles.checkDisabled]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(section.id)}
                      disabled={!section.draftable}
                      onChange={() => toggleSection(section.id)}
                    />
                    <span>
                      <span className={styles.sectionId}>{section.id}</span> {section.title}
                      {!section.draftable && ' — heading only, nothing drafted from data'}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className={styles.hint}>
            {structureError ?? 'Loading the dated CTD heading tree from the service…'}
          </p>
        )}
      </fieldset>

      <RowGroup
        title="Submitted data"
        hint="Each record is filed under a kind, and a section is only drafted from the kinds mapped to it. A section with no matching record comes back empty with the gap stated — never filled with placeholder prose. Set a section id to keep a record scoped to one section."
        addLabel="Add record"
        onAdd={() => setEvidence((prev) => [...prev, { ...emptyEvidence }])}
      >
        {evidence.map((record, index) => (
          <Row
            key={index}
            onRemove={() => setEvidence((prev) => prev.filter((_, i) => i !== index))}
          >
            <SelectField
              label="Kind"
              value={record.kind}
              options={EVIDENCE_KINDS}
              onChange={(value) => setEvidence((prev) => replace(prev, index, { kind: value }))}
            />
            <TextField
              label="Label"
              value={record.label}
              onChange={(value) => setEvidence((prev) => replace(prev, index, { label: value }))}
            />
            <TextField
              label="Value"
              value={record.value}
              onChange={(value) => setEvidence((prev) => replace(prev, index, { value }))}
            />
            <TextField
              label="Unit"
              value={record.unit}
              onChange={(value) => setEvidence((prev) => replace(prev, index, { unit: value }))}
            />
            <TextField
              label="Batch"
              value={record.batchId}
              onChange={(value) => setEvidence((prev) => replace(prev, index, { batchId: value }))}
            />
            <TextField
              label="Study"
              value={record.studyId}
              onChange={(value) => setEvidence((prev) => replace(prev, index, { studyId: value }))}
            />
            <TextField
              label="Section id"
              value={record.sectionId}
              onChange={(value) =>
                setEvidence((prev) => replace(prev, index, { sectionId: value }))
              }
            />
            <TextField
              label="Detail"
              value={record.detail}
              onChange={(value) => setEvidence((prev) => replace(prev, index, { detail: value }))}
            />
          </Row>
        ))}
      </RowGroup>

      <p className={styles.hint}>
        The records you enter are sent to Anthropic (Claude) to draft the selected sections. Do not
        enter material you are not permitted to share with a third-party processor.
      </p>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <Button type="submit" variant="primary" disabled={!canSubmit}>
        {running ? 'Drafting…' : 'Draft selected sections'}
      </Button>
    </form>
  );
}

export function IndOutput({ controller }: { controller: IndController }) {
  const { draft, running, setDraft } = controller;

  const library = (
    <SavedLibrary<IndDraft>
      kind="regulatory_ind"
      current={
        draft
          ? {
              title: `${draft.program_name} — IND sections`,
              subtitle: `${draft.sections.length} drafted sections · requires expert review`,
              payload: draft,
            }
          : null
      }
      onOpen={setDraft}
    />
  );

  if (!draft) {
    return (
      <div className={styles.output}>
        {library}
        <EmptyState title={running ? 'Drafting…' : 'No sections drafted yet'}>
          <p>
            Pick the CTD headings to draft and enter the data they should be drafted from. Sections
            come back with whatever the data supports and an explicit list of what it does not.
          </p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className={styles.output}>
      {library}
      <p className={styles.meta}>
        {draft.program_name} · drafted {new Date(draft.generated_at).toLocaleString()} · structure
        version {draft.reference.version} (transcribed {draft.reference.retrieved})
      </p>

      {draft.sections.map((section) => (
        <article key={section.section_id} className={styles.card}>
          <div className={styles.cardHead}>
            <h3 className={styles.cardTitle}>
              <span className={styles.sectionId}>{section.section_id}</span> {section.title}
            </h3>
            <StatusPill tone={section.status === 'drafted' ? 'warning' : 'idle'}>
              {STATUS_LABEL[section.status]}
            </StatusPill>
          </div>
          {section.text.length > 0 ? (
            <p className={styles.body}>{section.text}</p>
          ) : (
            <p className={styles.hint}>
              Nothing was drafted for this section. The submitted data did not support any text for
              it, and the service does not invent text to fill the space.
            </p>
          )}

          {section.gaps.length > 0 && (
            <>
              <h4 className={styles.subTitle}>Gaps · must be completed by the author</h4>
              <ul className={styles.list}>
                {section.gaps.map((gap, index) => (
                  <li key={`${gap.kind}-${index}`} className={styles.gap}>
                    {gap.description}
                  </li>
                ))}
              </ul>
            </>
          )}

          {section.evidence_used.length > 0 && (
            <>
              <h4 className={styles.subTitle}>Drafted from</h4>
              <ul className={styles.list}>
                {section.evidence_used.map((used) => (
                  <li key={used} className={styles.meta}>
                    {used}
                  </li>
                ))}
              </ul>
            </>
          )}

          {section.source_reference && (
            <p className={styles.meta}>Heading source: {section.source_reference}</p>
          )}
          <p className={styles.notice}>{section.review_notice}</p>
        </article>
      ))}

      {draft.unknown_section_ids.length > 0 && (
        <p className={styles.error} role="alert">
          Not in the transcribed structure, so nothing was drafted for them:{' '}
          {draft.unknown_section_ids.join(', ')}
        </p>
      )}

      {draft.unused_evidence.length > 0 && (
        <section className={styles.card}>
          <h3 className={styles.cardTitle}>Submitted data not used</h3>
          <p className={styles.hint}>
            No drafted section maps to these records, so nothing in the draft rests on them.
          </p>
          <ul className={styles.list}>
            {draft.unused_evidence.map((record) => (
              <li key={record} className={styles.meta}>
                {record}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={styles.card}>
        <h3 className={styles.cardTitle}>Structure sources</h3>
        <ul className={styles.list}>
          {draft.reference.sources.map((source) => (
            <li key={source.id}>
              <a className={styles.link} href={source.url} target="_blank" rel="noreferrer">
                {source.id} — {source.title} ({source.document_date})
              </a>
            </li>
          ))}
        </ul>
        {draft.reference.notes.map((note) => (
          <p key={note} className={styles.hint}>
            {note}
          </p>
        ))}
      </section>

      <p className={styles.notice}>{draft.review_notice}</p>
    </div>
  );
}
