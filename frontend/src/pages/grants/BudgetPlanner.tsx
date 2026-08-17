import { useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { api, type ExportFormat } from '@/lib/api';
import { saveFile } from '@/lib/download';
import {
  money,
  type AwardPhase,
  type BudgetRequest,
  type CostCategory,
  type CostLine,
  type GrantBudget,
  type PersonnelLine,
} from '@/lib/grants';
import { getAccessToken } from '@/lib/session';

import styles from './grants.module.css';

const CATEGORIES: { value: CostCategory; label: string }[] = [
  { value: 'equipment', label: 'Equipment' },
  { value: 'travel', label: 'Travel' },
  { value: 'materials', label: 'Materials & supplies' },
  { value: 'consultant', label: 'Consultant' },
  { value: 'subaward', label: 'Subaward / contract research' },
  { value: 'participant_support', label: 'Participant support' },
  { value: 'other', label: 'Other direct' },
];

function emptyPerson(): PersonnelLine {
  return {
    role: '',
    name: '',
    key_person: true,
    base_salary_annual: '',
    effort_percent: '',
    months: '',
    fringe_rate_percent: '',
  };
}

function emptyCost(): CostLine {
  return { category: 'materials', description: '', quantity: '1', unit_cost: '' };
}

const EMPTY_REQUEST: BudgetRequest = {
  program: 'SBIR',
  phase: 'phase_i',
  period_months: 6,
  organization: '',
  project_title: '',
  personnel: [emptyPerson()],
  costs: [emptyCost()],
  indirect_rate_percent: '',
  fee_percent: '',
};

/** The wire model takes `Decimal | null`; an empty box means "unset", not zero. */
function decimalOrNull(value: string): string | null {
  return value.trim() === '' ? null : value.trim();
}

/** Drops the rows the user started and left blank rather than sending them as zeroes. */
function toRequest(draft: BudgetRequest): BudgetRequest {
  return {
    ...draft,
    personnel: draft.personnel
      .filter((line) => line.role.trim() && line.base_salary_annual.trim())
      .map((line) => ({ ...line, fringe_rate_percent: decimalOrNull(line.fringe_rate_percent ?? '') })),
    costs: draft.costs.filter((line) => line.description.trim() && line.unit_cost.trim()),
    indirect_rate_percent: decimalOrNull(draft.indirect_rate_percent ?? ''),
    fee_percent: decimalOrNull(draft.fee_percent ?? ''),
  };
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'The budget could not be costed.';
}

/**
 * The SF-424 (R&R) budget builder.
 *
 * Every figure on screen is returned by the backend calculator, including the subtotals and the
 * total, so the page never does its own arithmetic on money and can never disagree with the file
 * the export produces.
 */
export function BudgetPlanner() {
  const [draft, setDraft] = useState<BudgetRequest>(EMPTY_REQUEST);
  const [budget, setBudget] = useState<GrantBudget | null>(null);
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const update = <K extends keyof BudgetRequest>(field: K, value: BudgetRequest[K]) =>
    setDraft((current) => ({ ...current, [field]: value }));

  const updatePerson = (index: number, patch: Partial<PersonnelLine>) =>
    setDraft((current) => ({
      ...current,
      personnel: current.personnel.map((line, at) => (at === index ? { ...line, ...patch } : line)),
    }));

  const updateCost = (index: number, patch: Partial<CostLine>) =>
    setDraft((current) => ({
      ...current,
      costs: current.costs.map((line, at) => (at === index ? { ...line, ...patch } : line)),
    }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      setBudget(await api.buildBudget(toRequest(draft), getAccessToken()));
    } catch (cause) {
      setError(errorMessage(cause));
      setBudget(null);
    } finally {
      setRunning(false);
    }
  };

  const download = async (format: ExportFormat) => {
    setExporting(format);
    setError(null);
    try {
      const file = await api.exportBudget(toRequest(draft), format, getAccessToken());
      saveFile(file.blob, file.filename);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setExporting(null);
    }
  };

  return (
    <Panel
      title="Budget builder"
      actions={
        <div className={styles.panelActions}>
          {budget && <StatusPill tone="validated">Rules {budget.rules_version}</StatusPill>}
          <Button
            size="sm"
            disabled={budget === null || exporting !== null}
            onClick={() => void download('xlsx')}
          >
            {exporting === 'xlsx' ? 'Exporting…' : 'Export .xlsx'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={budget === null || exporting !== null}
            onClick={() => void download('csv')}
          >
            {exporting === 'csv' ? 'Exporting…' : 'Export .csv'}
          </Button>
        </div>
      }
    >
      <form className={styles.form} onSubmit={submit}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="budget-phase">
            Phase
          </label>
          <select
            id="budget-phase"
            className={styles.input}
            value={draft.phase}
            onChange={(event) => update('phase', event.target.value as AwardPhase)}
          >
            <option value="phase_i">Phase I</option>
            <option value="phase_ii">Phase II</option>
            <option value="direct_phase_ii">Direct to Phase II</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="budget-months">
            Period of performance (months)
          </label>
          <input
            id="budget-months"
            className={styles.input}
            type="number"
            min={1}
            max={60}
            value={draft.period_months}
            onChange={(event) => update('period_months', Number(event.target.value))}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="budget-indirect">
            Indirect cost rate (%) — blank uses the de minimis rate
          </label>
          <input
            id="budget-indirect"
            className={styles.input}
            type="number"
            min={0}
            max={200}
            step="0.1"
            value={draft.indirect_rate_percent ?? ''}
            onChange={(event) => update('indirect_rate_percent', event.target.value)}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="budget-fee">
            Fee / profit (%)
          </label>
          <input
            id="budget-fee"
            className={styles.input}
            type="number"
            min={0}
            max={100}
            step="0.1"
            value={draft.fee_percent ?? ''}
            onChange={(event) => update('fee_percent', event.target.value)}
          />
        </div>

        <fieldset className={styles.lineGroup}>
          <legend className={styles.label}>Personnel</legend>
          {draft.personnel.map((line, index) => (
            <div className={styles.lineRow} key={`person-${index}`}>
              <input
                className={styles.input}
                aria-label={`Role ${index + 1}`}
                value={line.role}
                maxLength={120}
                placeholder="Principal Investigator"
                onChange={(event) => updatePerson(index, { role: event.target.value })}
              />
              <input
                className={styles.input}
                aria-label={`Base salary ${index + 1}`}
                type="number"
                min={0}
                value={line.base_salary_annual}
                placeholder="Base salary / yr"
                onChange={(event) => updatePerson(index, { base_salary_annual: event.target.value })}
              />
              <input
                className={styles.input}
                aria-label={`Effort percent ${index + 1}`}
                type="number"
                min={0}
                max={100}
                value={line.effort_percent}
                placeholder="Effort %"
                onChange={(event) => updatePerson(index, { effort_percent: event.target.value })}
              />
              <input
                className={styles.input}
                aria-label={`Months ${index + 1}`}
                type="number"
                min={0}
                max={60}
                value={line.months}
                placeholder="Months"
                onChange={(event) => updatePerson(index, { months: event.target.value })}
              />
              <input
                className={styles.input}
                aria-label={`Fringe rate ${index + 1}`}
                type="number"
                min={0}
                max={100}
                value={line.fringe_rate_percent ?? ''}
                placeholder="Fringe %"
                onChange={(event) => updatePerson(index, { fringe_rate_percent: event.target.value })}
              />
            </div>
          ))}
          <Button
            size="sm"
            variant="ghost"
            disabled={draft.personnel.length >= 50}
            onClick={() => update('personnel', [...draft.personnel, emptyPerson()])}
          >
            Add person
          </Button>
        </fieldset>

        <fieldset className={styles.lineGroup}>
          <legend className={styles.label}>Other direct costs</legend>
          {draft.costs.map((line, index) => (
            <div className={styles.lineRow} key={`cost-${index}`}>
              <select
                className={styles.input}
                aria-label={`Category ${index + 1}`}
                value={line.category}
                onChange={(event) =>
                  updateCost(index, { category: event.target.value as CostCategory })
                }
              >
                {CATEGORIES.map((category) => (
                  <option key={category.value} value={category.value}>
                    {category.label}
                  </option>
                ))}
              </select>
              <input
                className={styles.input}
                aria-label={`Description ${index + 1}`}
                value={line.description}
                maxLength={200}
                placeholder="Assay plates"
                onChange={(event) => updateCost(index, { description: event.target.value })}
              />
              <input
                className={styles.input}
                aria-label={`Quantity ${index + 1}`}
                type="number"
                min={1}
                value={line.quantity}
                onChange={(event) => updateCost(index, { quantity: event.target.value })}
              />
              <input
                className={styles.input}
                aria-label={`Unit cost ${index + 1}`}
                type="number"
                min={0}
                value={line.unit_cost}
                placeholder="Unit cost"
                onChange={(event) => updateCost(index, { unit_cost: event.target.value })}
              />
            </div>
          ))}
          <Button
            size="sm"
            variant="ghost"
            disabled={draft.costs.length >= 200}
            onClick={() => update('costs', [...draft.costs, emptyCost()])}
          >
            Add cost line
          </Button>
        </fieldset>

        <div className={styles.searchActions}>
          <Button type="submit" variant="primary" disabled={running}>
            {running ? 'Costing…' : 'Cost the budget'}
          </Button>
        </div>
      </form>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <CaveatBand label="Planning figures, not a submission.">
        Amounts are computed from the federal rules in the service's config — the salary cap,
        indirect base and fee ceiling — which are revised annually and vary by agency. Check them
        against the solicitation, and have your finance office confirm the rates before you
        submit.
      </CaveatBand>

      {budget === null ? (
        <EmptyState title="Nothing costed yet">
          Enter at least one person or cost line and cost the budget. The salary cap, indirect base
          and fee are applied by the backend, and every change it makes is listed with the rule
          behind it.
        </EmptyState>
      ) : (
        <div className={styles.budget}>
          <div className={styles.budgetTotal}>
            <span className={styles.budgetAmount}>{money(budget.total)}</span>
            <span className={styles.budgetLabel}>
              Total request over {budget.period_months} months — {money(budget.total_direct)} direct,{' '}
              {money(budget.indirect)} indirect at {budget.indirect_rate_percent}%,{' '}
              {money(budget.fee)} fee
            </span>
          </div>
          <table className={styles.budgetTable}>
            <thead>
              <tr>
                <th scope="col">Section</th>
                <th scope="col">Basis</th>
                <th scope="col">Amount</th>
              </tr>
            </thead>
            <tbody>
              {budget.sections.map((section) => (
                <tr key={section.code}>
                  <th scope="row">{section.title}</th>
                  <td>
                    <ul className={styles.lineList}>
                      {section.lines.map((line) => (
                        <li key={`${section.code}-${line.label}-${line.basis}`}>
                          <span>{line.label}</span>
                          <span className={styles.basis}>{line.basis}</span>
                        </li>
                      ))}
                    </ul>
                  </td>
                  <td className={styles.amount}>{money(section.subtotal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {budget.adjustments.length > 0 && (
            <div className={styles.adjustments}>
              <h4 className={styles.subheading}>Rules applied</h4>
              <ul>
                {budget.adjustments.map((adjustment) => (
                  <li key={`${adjustment.rule_id}-${adjustment.message}`}>
                    {adjustment.message}
                    {adjustment.authority && (
                      <cite className={styles.citation}>{adjustment.authority}</cite>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {budget.warnings.length > 0 && (
            <div className={styles.adjustments}>
              <h4 className={styles.subheading}>Check before submitting</h4>
              <ul>
                {budget.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
