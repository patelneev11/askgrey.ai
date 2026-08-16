import { useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { api } from '@/lib/api';
import {
  EMPTY_PROFILE,
  VERDICT_LABELS,
  type AwardPhase,
  type CompanyProfile,
  type EligibilityReport,
  type GrantProgram,
  type OrganizationType,
  type PiEmployer,
  type RuleOutcome,
  type Verdict,
} from '@/lib/grants';
import { getAccessToken } from '@/lib/session';

import styles from './grants.module.css';

const VERDICT_TONES: Record<Verdict, 'validated' | 'warning' | 'idle'> = {
  pass: 'validated',
  fail: 'warning',
  needs_review: 'idle',
};

/** Blank means "not recorded", which the backend turns into `needs_review` rather than a pass. */
function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function triState(value: string): boolean | null {
  return value === '' ? null : value === 'yes';
}

function fromTriState(value: boolean | null): string {
  return value === null ? '' : value ? 'yes' : 'no';
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'The eligibility check failed.';
}

function Outcome({ outcome }: { outcome: RuleOutcome }) {
  return (
    <li className={styles.outcome}>
      <div className={styles.outcomeHead}>
        <span className={styles.outcomeTitle}>{outcome.title}</span>
        <StatusPill tone={VERDICT_TONES[outcome.verdict]}>
          {VERDICT_LABELS[outcome.verdict]}
        </StatusPill>
      </div>
      <p className={styles.outcomeExplanation}>{outcome.explanation}</p>
      {outcome.missing_fields.length > 0 && (
        <p className={styles.outcomeMissing}>Missing: {outcome.missing_fields.join(', ')}</p>
      )}
      {outcome.citation && <cite className={styles.citation}>{outcome.citation}</cite>}
    </li>
  );
}

/**
 * The rules-based eligibility screen.
 *
 * Every verdict on screen came from a numeric threshold in the service's rule config, so there
 * is no prediction caveat here — but it is still not a legal determination, and the panel says
 * so permanently rather than only in the intro notice.
 */
export function EligibilityChecklist() {
  const [profile, setProfile] = useState<CompanyProfile>(EMPTY_PROFILE);
  const [program, setProgram] = useState<GrantProgram>('SBIR');
  const [report, setReport] = useState<EligibilityReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = <K extends keyof CompanyProfile>(field: K, value: CompanyProfile[K]) =>
    setProfile((current) => ({ ...current, [field]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      setReport(await api.checkEligibility(profile, program, getAccessToken()));
    } catch (cause) {
      setError(errorMessage(cause));
      setReport(null);
    } finally {
      setRunning(false);
    }
  };

  return (
    <Panel
      title="Eligibility checklist"
      actions={
        report && (
          <StatusPill tone={VERDICT_TONES[report.verdict]}>
            {VERDICT_LABELS[report.verdict]}
          </StatusPill>
        )
      }
    >
      <form className={styles.form} onSubmit={submit}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-program">
            Program
          </label>
          <select
            id="eligibility-program"
            className={styles.input}
            value={program}
            onChange={(event) => setProgram(event.target.value as GrantProgram)}
          >
            <option value="SBIR">SBIR</option>
            <option value="STTR">STTR</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-phase">
            Phase
          </label>
          <select
            id="eligibility-phase"
            className={styles.input}
            value={profile.phase ?? ''}
            onChange={(event) => update('phase', (event.target.value || null) as AwardPhase | null)}
          >
            <option value="">Not recorded</option>
            <option value="phase_i">Phase I</option>
            <option value="phase_ii">Phase II</option>
            <option value="direct_phase_ii">Direct to Phase II</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-org-type">
            Organization type
          </label>
          <select
            id="eligibility-org-type"
            className={styles.input}
            value={profile.organization_type ?? ''}
            onChange={(event) =>
              update('organization_type', (event.target.value || null) as OrganizationType | null)
            }
          >
            <option value="">Not recorded</option>
            <option value="for_profit">For-profit</option>
            <option value="nonprofit">Nonprofit</option>
            <option value="academic">Academic</option>
            <option value="government">Government</option>
            <option value="individual">Individual</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-employees">
            Employees (including affiliates)
          </label>
          <input
            id="eligibility-employees"
            className={styles.input}
            type="number"
            min={0}
            max={100000}
            value={profile.employee_count ?? ''}
            onChange={(event) => update('employee_count', numberOrNull(event.target.value))}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-us">
            Principal place of business in the US
          </label>
          <select
            id="eligibility-us"
            className={styles.input}
            value={fromTriState(profile.principal_place_of_business_us)}
            onChange={(event) =>
              update('principal_place_of_business_us', triState(event.target.value))
            }
          >
            <option value="">Not recorded</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-us-owned">
            Owned by US citizens or permanent residents (%)
          </label>
          <input
            id="eligibility-us-owned"
            className={styles.input}
            type="number"
            min={0}
            max={100}
            value={profile.ownership.us_individuals_percent ?? ''}
            onChange={(event) =>
              update('ownership', {
                ...profile.ownership,
                us_individuals_percent: numberOrNull(event.target.value),
              })
            }
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-pi-employer">
            PI's primary employer
          </label>
          <select
            id="eligibility-pi-employer"
            className={styles.input}
            value={profile.pi_primary_employer ?? ''}
            onChange={(event) =>
              update('pi_primary_employer', (event.target.value || null) as PiEmployer | null)
            }
          >
            <option value="">Not recorded</option>
            <option value="company">The company</option>
            <option value="research_institution">A research institution</option>
            <option value="other">Elsewhere</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-pi-time">
            PI's time at the company during the award (%)
          </label>
          <input
            id="eligibility-pi-time"
            className={styles.input}
            type="number"
            min={0}
            max={100}
            value={profile.pi_company_time_percent ?? ''}
            onChange={(event) =>
              update('pi_company_time_percent', numberOrNull(event.target.value))
            }
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-work-company">
            Work performed by the company (%)
          </label>
          <input
            id="eligibility-work-company"
            className={styles.input}
            type="number"
            min={0}
            max={100}
            value={profile.work_by_company_percent ?? ''}
            onChange={(event) =>
              update('work_by_company_percent', numberOrNull(event.target.value))
            }
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-work-institution">
            Work performed by the research institution (%)
          </label>
          <input
            id="eligibility-work-institution"
            className={styles.input}
            type="number"
            min={0}
            max={100}
            value={profile.work_by_research_institution_percent ?? ''}
            onChange={(event) =>
              update('work_by_research_institution_percent', numberOrNull(event.target.value))
            }
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-sam">
            Registered in SAM.gov
          </label>
          <select
            id="eligibility-sam"
            className={styles.input}
            value={fromTriState(profile.sam_registered)}
            onChange={(event) => update('sam_registered', triState(event.target.value))}
          >
            <option value="">Not recorded</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="eligibility-registry">
            Registered in the SBA Company Registry
          </label>
          <select
            id="eligibility-registry"
            className={styles.input}
            value={fromTriState(profile.sba_company_registry_registered)}
            onChange={(event) =>
              update('sba_company_registry_registered', triState(event.target.value))
            }
          >
            <option value="">Not recorded</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <div className={styles.wideField}>
          <label className={styles.label} htmlFor="eligibility-focus">
            Research focus
          </label>
          <textarea
            id="eligibility-focus"
            className={styles.textarea}
            rows={2}
            maxLength={2000}
            value={profile.research_focus}
            onChange={(event) => update('research_focus', event.target.value)}
          />
        </div>
        <div className={styles.searchActions}>
          <Button type="submit" variant="primary" disabled={running}>
            {running ? 'Checking…' : 'Check eligibility'}
          </Button>
        </div>
      </form>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <CaveatBand label="Not a legal determination.">
        These are the encoded SBA baseline thresholds, not the agency's own supplements. Blank
        answers are reported as needing review rather than assumed. Confirm against the
        solicitation and, where money turns on it, with counsel.
      </CaveatBand>

      {report === null ? (
        <EmptyState title="No profile checked yet">
          Fill in what you know and leave the rest blank — every rule that cannot be decided from
          the facts given is reported as needing review, and names the field it is missing.
        </EmptyState>
      ) : (
        <>
          <p className={styles.summary}>{report.summary}</p>
          <p className={styles.provenance}>Rule set {report.config_version}</p>
          <ul className={styles.outcomes}>
            {report.outcomes.map((outcome) => (
              <Outcome key={outcome.rule_id} outcome={outcome} />
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
