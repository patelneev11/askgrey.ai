import { useCallback, useState } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { StatusPill } from '@/components/StatusPill';
import {
  api,
  type DoseGroup,
  type GlpStatus,
  type PreclinicalReport,
  type Sex,
  type StudyFinding,
  type StudyMeasurement,
  type StudyTable,
} from '@/lib/api';
import { getAccessToken } from '@/lib/session';

import { Row, RowGroup, SelectField, TextField } from './fields';
import { errorMessage } from './errors';
import styles from './regulatory.module.css';

interface GroupDraft {
  label: string;
  doseValue: string;
  doseUnit: string;
  sex: Sex;
  animalsPerSex: string;
}

interface FindingDraft {
  groupLabel: string;
  endpoint: string;
  value: string;
  unit: string;
  severity: string;
}

interface MeasurementDraft {
  name: string;
  aliases: string;
  value: string;
  unit: string;
  textValue: string;
}

const emptyGroup: GroupDraft = {
  label: '',
  doseValue: '',
  doseUnit: '',
  sex: 'not_reported',
  animalsPerSex: '',
};
const emptyFinding: FindingDraft = {
  groupLabel: '',
  endpoint: '',
  value: '',
  unit: '',
  severity: '',
};
const emptyMeasurement: MeasurementDraft = {
  name: '',
  aliases: '',
  value: '',
  unit: '',
  textValue: '',
};

const SEXES: { value: Sex; label: string }[] = [
  { value: 'not_reported', label: 'Not reported' },
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'both', label: 'Both' },
];

const GLP: { value: GlpStatus; label: string }[] = [
  { value: 'not_reported', label: 'Not reported' },
  { value: 'compliant', label: 'GLP compliant' },
  { value: 'non_compliant', label: 'Not GLP compliant' },
];

/**
 * The study table plus the last report drafted from it.
 *
 * State lives here rather than in the form component so switching sub-feature tabs does not
 * silently discard a half-entered study.
 */
export function usePreclinical() {
  const [study, setStudy] = useState({
    studyId: '',
    title: '',
    testArticle: '',
    species: '',
    strain: '',
    route: '',
    duration: '',
    glpStatus: 'not_reported' as GlpStatus,
  });
  const [groups, setGroups] = useState<GroupDraft[]>([{ ...emptyGroup }]);
  const [findings, setFindings] = useState<FindingDraft[]>([{ ...emptyFinding }]);
  const [measurements, setMeasurements] = useState<MeasurementDraft[]>([{ ...emptyMeasurement }]);
  const [report, setReport] = useState<PreclinicalReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      setReport(
        await api.preclinicalReport(
          buildTable(study, groups, findings, measurements),
          getAccessToken(),
        ),
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setRunning(false);
    }
  }, [study, groups, findings, measurements]);

  return {
    study,
    setStudy,
    groups,
    setGroups,
    findings,
    setFindings,
    measurements,
    setMeasurements,
    report,
    running,
    error,
    submit,
  };
}

export type PreclinicalController = ReturnType<typeof usePreclinical>;

function quantity(value: string, unit: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 ? { value: trimmed, unit: unit.trim() } : null;
}

/** Blank rows are dropped rather than sent as empty records the auditor would have to ignore. */
function buildTable(
  study: PreclinicalController['study'],
  groups: GroupDraft[],
  findings: FindingDraft[],
  measurements: MeasurementDraft[],
): StudyTable {
  const doseGroups: DoseGroup[] = groups
    .filter((group) => group.label.trim().length > 0)
    .map((group) => ({
      label: group.label.trim(),
      dose: quantity(group.doseValue, group.doseUnit),
      sex: group.sex,
      animals_per_sex:
        group.animalsPerSex.trim().length > 0 ? Number(group.animalsPerSex.trim()) : null,
    }));

  const studyFindings: StudyFinding[] = findings
    .filter((finding) => finding.endpoint.trim().length > 0)
    .map((finding) => ({
      group_label: finding.groupLabel.trim(),
      endpoint: finding.endpoint.trim(),
      quantity: quantity(finding.value, finding.unit),
      severity: finding.severity.trim(),
    }));

  const studyMeasurements: StudyMeasurement[] = measurements
    .filter((measurement) => measurement.name.trim().length > 0)
    .map((measurement) => ({
      name: measurement.name.trim(),
      aliases: measurement.aliases
        .split(',')
        .map((alias) => alias.trim())
        .filter((alias) => alias.length > 0),
      quantity: quantity(measurement.value, measurement.unit),
      text_value: measurement.textValue.trim(),
    }));

  return {
    study_id: study.studyId.trim(),
    title: study.title.trim(),
    test_article: study.testArticle.trim(),
    species: study.species.trim(),
    strain: study.strain.trim(),
    route: study.route.trim(),
    duration: study.duration.trim(),
    glp_status: study.glpStatus,
    groups: doseGroups,
    findings: studyFindings,
    measurements: studyMeasurements,
  };
}

function replace<T>(rows: T[], index: number, patch: Partial<T>): T[] {
  return rows.map((row, position) => (position === index ? { ...row, ...patch } : row));
}

export function PreclinicalForm({ controller }: { controller: PreclinicalController }) {
  const {
    study,
    setStudy,
    groups,
    setGroups,
    findings,
    setFindings,
    measurements,
    setMeasurements,
    running,
    error,
    submit,
  } = controller;

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <TextField
        label="Study id"
        value={study.studyId}
        onChange={(value) => setStudy((prev) => ({ ...prev, studyId: value }))}
        placeholder="TOX-2026-014"
        maxLength={80}
        required
      />
      <TextField
        label="Test article"
        value={study.testArticle}
        onChange={(value) => setStudy((prev) => ({ ...prev, testArticle: value }))}
        maxLength={200}
      />
      <TextField
        label="Species"
        value={study.species}
        onChange={(value) => setStudy((prev) => ({ ...prev, species: value }))}
        maxLength={120}
      />
      <TextField
        label="Strain"
        value={study.strain}
        onChange={(value) => setStudy((prev) => ({ ...prev, strain: value }))}
        maxLength={120}
      />
      <TextField
        label="Route"
        value={study.route}
        onChange={(value) => setStudy((prev) => ({ ...prev, route: value }))}
        maxLength={120}
      />
      <TextField
        label="Duration"
        value={study.duration}
        onChange={(value) => setStudy((prev) => ({ ...prev, duration: value }))}
        placeholder="28 days"
        maxLength={120}
      />
      <SelectField
        label="GLP status"
        value={study.glpStatus}
        options={GLP}
        onChange={(value) => setStudy((prev) => ({ ...prev, glpStatus: value }))}
      />

      <RowGroup
        title="Dose groups"
        hint="Doses are written into the narrative exactly as entered here — they are never rounded or converted."
        addLabel="Add dose group"
        onAdd={() => setGroups((prev) => [...prev, { ...emptyGroup }])}
      >
        {groups.map((group, index) => (
          <Row key={index} onRemove={() => setGroups((prev) => prev.filter((_, i) => i !== index))}>
            <TextField
              label="Group label"
              value={group.label}
              onChange={(value) => setGroups((prev) => replace(prev, index, { label: value }))}
            />
            <TextField
              label="Dose"
              value={group.doseValue}
              onChange={(value) => setGroups((prev) => replace(prev, index, { doseValue: value }))}
            />
            <TextField
              label="Dose unit"
              value={group.doseUnit}
              onChange={(value) => setGroups((prev) => replace(prev, index, { doseUnit: value }))}
              placeholder="mg/kg/day"
            />
            <TextField
              label="Animals per sex"
              value={group.animalsPerSex}
              onChange={(value) =>
                setGroups((prev) => replace(prev, index, { animalsPerSex: value }))
              }
            />
            <SelectField
              label="Sex"
              value={group.sex}
              options={SEXES}
              onChange={(value) => setGroups((prev) => replace(prev, index, { sex: value }))}
            />
          </Row>
        ))}
      </RowGroup>

      <RowGroup
        title="Findings"
        hint="One row per observed endpoint. Anything not entered here cannot appear in the narrative."
        addLabel="Add finding"
        onAdd={() => setFindings((prev) => [...prev, { ...emptyFinding }])}
      >
        {findings.map((finding, index) => (
          <Row
            key={index}
            onRemove={() => setFindings((prev) => prev.filter((_, i) => i !== index))}
          >
            <TextField
              label="Group"
              value={finding.groupLabel}
              onChange={(value) =>
                setFindings((prev) => replace(prev, index, { groupLabel: value }))
              }
            />
            <TextField
              label="Endpoint"
              value={finding.endpoint}
              onChange={(value) => setFindings((prev) => replace(prev, index, { endpoint: value }))}
            />
            <TextField
              label="Value"
              value={finding.value}
              onChange={(value) => setFindings((prev) => replace(prev, index, { value }))}
            />
            <TextField
              label="Unit"
              value={finding.unit}
              onChange={(value) => setFindings((prev) => replace(prev, index, { unit: value }))}
            />
            <TextField
              label="Severity"
              value={finding.severity}
              onChange={(value) => setFindings((prev) => replace(prev, index, { severity: value }))}
            />
          </Row>
        ))}
      </RowGroup>

      <RowGroup
        title="Named study values"
        hint="Values the narrative is expected to state, e.g. NOAEL. Aliases (comma separated) are how the audit finds the claim in the text; a value of 'not established' with no number is checked too."
        addLabel="Add named value"
        onAdd={() => setMeasurements((prev) => [...prev, { ...emptyMeasurement }])}
      >
        {measurements.map((measurement, index) => (
          <Row
            key={index}
            onRemove={() => setMeasurements((prev) => prev.filter((_, i) => i !== index))}
          >
            <TextField
              label="Name"
              value={measurement.name}
              onChange={(value) => setMeasurements((prev) => replace(prev, index, { name: value }))}
            />
            <TextField
              label="Aliases"
              value={measurement.aliases}
              onChange={(value) =>
                setMeasurements((prev) => replace(prev, index, { aliases: value }))
              }
              placeholder="no-observed-adverse-effect level"
            />
            <TextField
              label="Value"
              value={measurement.value}
              onChange={(value) => setMeasurements((prev) => replace(prev, index, { value }))}
            />
            <TextField
              label="Unit"
              value={measurement.unit}
              onChange={(value) => setMeasurements((prev) => replace(prev, index, { unit: value }))}
            />
            <TextField
              label="Text value"
              value={measurement.textValue}
              onChange={(value) =>
                setMeasurements((prev) => replace(prev, index, { textValue: value }))
              }
              placeholder="not established"
            />
          </Row>
        ))}
      </RowGroup>

      <p className={styles.hint}>
        The study data you enter is sent to Anthropic (Claude) to draft the narrative. Every number
        it writes is then checked against this table by exact decimal matching, with no model
        involved in the check.
      </p>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <Button
        type="submit"
        variant="primary"
        disabled={running || study.studyId.trim().length === 0}
      >
        {running ? 'Drafting…' : 'Draft narrative and audit numbers'}
      </Button>
    </form>
  );
}

export function PreclinicalOutput({ controller }: { controller: PreclinicalController }) {
  const { report, running } = controller;

  if (!report) {
    return (
      <EmptyState title={running ? 'Drafting…' : 'No narrative drafted yet'}>
        <p>
          Enter the study record on the left. The drafted narrative appears here alongside every
          number the audit could not match back to that record.
        </p>
      </EmptyState>
    );
  }

  return (
    <div className={styles.output}>
      {/* The backend only sets this for its development-only fixture drafter, whose numbers are
          deliberately wrong so the flags below can be seen. Saying so here keeps fixture output
          from reading as a draft of anything. */}
      {report.fixture_draft && (
        <CaveatBand label="Fixture output, not a draft.">
          This narrative was generated by the development fixture drafter ({report.drafter}), which
          writes deliberately incorrect numbers so the discrepancy audit below can be exercised. It
          is not model output and none of it describes the submitted study.
        </CaveatBand>
      )}
      <p className={styles.meta}>
        {report.study_id} · drafted {new Date(report.generated_at).toLocaleString()} ·{' '}
        {report.audit.numbers_matched}/{report.audit.numbers_checked} numbers matched to the
        submitted table · auditor {report.audit.auditor_version}
      </p>
      <p className={styles.hint}>{report.audit.method}</p>

      {report.sections.map((section) => (
        <article key={section.key} className={styles.card}>
          <div className={styles.cardHead}>
            <h3 className={styles.cardTitle}>{section.heading}</h3>
            <StatusPill tone="warning">first draft</StatusPill>
          </div>
          {section.text.length > 0 ? (
            <p className={styles.body}>{section.text}</p>
          ) : (
            <p className={styles.hint}>No text drafted for this section.</p>
          )}
          {section.gaps.length > 0 && (
            <>
              <h4 className={styles.subTitle}>Stated gaps</h4>
              <ul className={styles.list}>
                {section.gaps.map((gap) => (
                  <li key={gap} className={styles.gap}>
                    {gap}
                  </li>
                ))}
              </ul>
            </>
          )}
          {/* Rendered from the payload, so a section cannot reach the screen without the
              marker the service attached to it. */}
          <p className={styles.notice}>{section.review_notice}</p>
        </article>
      ))}

      <section className={styles.card}>
        <div className={styles.cardHead}>
          <h3 className={styles.cardTitle}>Discrepancy audit</h3>
          {report.discrepancies.length > 0 ? (
            <StatusPill tone="warning">
              {report.discrepancies.length} flagged{' '}
              {report.discrepancies.length === 1 ? 'number' : 'numbers'}
            </StatusPill>
          ) : (
            <StatusPill tone="validated">no mismatches found</StatusPill>
          )}
        </div>
        {report.discrepancies.length === 0 ? (
          <p className={styles.hint}>
            Every number in the draft matched a value in the submitted table. This is a numeric
            check only — it says nothing about whether the surrounding claims are correct.
          </p>
        ) : (
          <ul className={styles.list}>
            {report.discrepancies.map((flag, index) => (
              <li key={`${flag.section}-${flag.start_char}-${index}`} className={styles.flag}>
                <span className={styles.flagHead}>
                  <span className={styles.flagKind}>
                    {flag.section} · {flag.kind.replace(/_/g, ' ')}
                  </span>
                  <span className={styles.severity}>{flag.severity}</span>
                </span>
                <p className={styles.flagBody}>{flag.explanation}</p>
                <p className={styles.flagBody}>
                  Draft says <strong>{flag.narrative_value}</strong>
                  {flag.source_value && (
                    <>
                      {' · '}table says <strong>{flag.source_value}</strong>
                      {flag.source_label && ` (${flag.source_label})`}
                    </>
                  )}
                </p>
                {flag.context && <p className={styles.quote}>…{flag.context}…</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className={styles.notice}>{report.review_notice}</p>
    </div>
  );
}
