import { useState, type FormEvent } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { Panel } from '@/components/Panel';
import { StatusPill } from '@/components/StatusPill';
import { api } from '@/lib/api';
import {
  SOURCE_LABELS,
  daysUntilClose,
  deadlineLabel,
  fundingLabel,
  programLabel,
  type GrantOpportunity,
  type GrantSearchQuery,
  type OpportunityMatch,
  type SourceStatus,
} from '@/lib/grants';
import { getAccessToken } from '@/lib/session';

import styles from './grants.module.css';

const EMPTY_QUERY: GrantSearchQuery = {
  keyword: '',
  agency: '',
  program: '',
  open_only: true,
  closing_before: '',
};

interface Results {
  /** Present only when the ranking came from the matcher, so nothing else claims a fit score. */
  matched: boolean;
  /** `"claude"`, `"lexical"` or `"claude+lexical"` — what actually produced the scores. */
  matcher: string;
  opportunities: GrantOpportunity[];
  scores: Map<string, OpportunityMatch>;
  sources: SourceStatus[];
  totalCount: number;
  candidatesConsidered: number;
}

function key(opportunity: GrantOpportunity): string {
  return `${opportunity.source}:${opportunity.opportunity_id}`;
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'The search failed.';
}

function ProviderStatus({ sources }: { sources: SourceStatus[] }) {
  if (sources.length === 0) return null;
  return (
    <ul className={styles.providers}>
      {sources.map((status) => (
        <li key={status.source}>
          {status.ok ? (
            <StatusPill tone="validated">
              {SOURCE_LABELS[status.source]} · {status.returned} of {status.total_count}
            </StatusPill>
          ) : (
            <StatusPill tone="warning">
              {SOURCE_LABELS[status.source]} unavailable · {status.error || 'no response'}
            </StatusPill>
          )}
        </li>
      ))}
      {sources.some((status) => status.source === 'sbir' && !status.ok) && (
        <li className={styles.providerNote}>
          SBIR/STTR solicitations that are cross-posted to grants.gov still appear above; those
          only carried by SBIR.gov are missing from this result set.
        </li>
      )}
    </ul>
  );
}

/**
 * Whether a language model actually ranked this result set.
 *
 * The backend falls through to a keyword ranker when no key is configured or Claude fails, and
 * reports that as `lexical` / `claude+lexical`. The label and the caveat both have to follow it:
 * calling a term-overlap count a model prediction would be a false claim about provenance.
 */
function rankedByModel(matcher: string): boolean {
  return matcher === 'claude';
}

function OpportunityCard({
  opportunity,
  match,
  semantic,
}: {
  opportunity: GrantOpportunity;
  match?: OpportunityMatch;
  semantic: boolean;
}) {
  const days = daysUntilClose(opportunity);

  return (
    <article className={styles.opportunity}>
      <div className={styles.opportunityHead}>
        <span className={styles.eyebrow}>
          {[opportunity.agency, opportunity.branch].filter(Boolean).join(' / ') ||
            SOURCE_LABELS[opportunity.source]}
        </span>
        {match && (
          <span
            className={styles.matchScore}
            title={
              semantic
                ? 'Predicted fit from a language model reading the topic text'
                : `Keyword overlap on ${match.matched_terms.join(', ') || 'no matched terms'}`
            }
          >
            {Math.round(match.score * 100)}% {semantic ? 'predicted fit' : 'term overlap'}
          </span>
        )}
      </div>
      <h3 className={styles.opportunityTitle}>
        {opportunity.url ? (
          <a href={opportunity.url} target="_blank" rel="noreferrer">
            {opportunity.title}
          </a>
        ) : (
          opportunity.title
        )}
      </h3>
      {opportunity.number && <code className={styles.code}>{opportunity.number}</code>}
      <dl className={styles.facts}>
        <div>
          <dt>Ceiling</dt>
          <dd>{fundingLabel(opportunity)}</dd>
        </div>
        <div>
          <dt>Deadline</dt>
          <dd>{deadlineLabel(opportunity)}</dd>
        </div>
        <div>
          <dt>Program</dt>
          <dd
            title={
              opportunity.program_provenance === 'inferred'
                ? 'grants.gov publishes no set-aside field; this was read out of the title and synopsis'
                : undefined
            }
          >
            {programLabel(opportunity)}
          </dd>
        </div>
      </dl>
      {days !== null && (
        <span className={days < 30 ? styles.urgent : styles.calm}>
          {days < 0 ? `closed ${Math.abs(days)} days ago` : `${days} days remaining`}
        </span>
      )}
      {match?.rationale && <p className={styles.rationale}>{match.rationale}</p>}
    </article>
  );
}

/**
 * Live opportunity search over grants.gov and SBIR.gov, with optional LLM ranking.
 *
 * Nothing here is displayed until a provider answers: the counts, deadlines and per-provider
 * pills are all read off the response, and a provider that fails says so rather than being
 * silently dropped from the totals.
 */
export function OpportunityFinder() {
  const [query, setQuery] = useState<GrantSearchQuery>(EMPTY_QUERY);
  const [focus, setFocus] = useState('');
  const [results, setResults] = useState<Results | null>(null);
  const [running, setRunning] = useState<'search' | 'match' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const update = <K extends keyof GrantSearchQuery>(field: K, value: GrantSearchQuery[K]) =>
    setQuery((current) => ({ ...current, [field]: value }));

  const search = async () => {
    setRunning('search');
    setError(null);
    try {
      const page = await api.searchGrants(query, getAccessToken());
      setResults({
        matched: false,
        matcher: '',
        opportunities: page.opportunities,
        scores: new Map(),
        sources: page.sources,
        totalCount: page.total_count,
        candidatesConsidered: 0,
      });
    } catch (cause) {
      setError(errorMessage(cause));
      setResults(null);
    } finally {
      setRunning(null);
    }
  };

  const rank = async () => {
    setRunning('match');
    setError(null);
    try {
      const result = await api.matchGrants(focus.trim(), query, getAccessToken());
      setResults({
        matched: true,
        matcher: result.matcher,
        opportunities: result.matches.map((match) => match.opportunity),
        scores: new Map(result.matches.map((match) => [key(match.opportunity), match])),
        sources: result.sources,
        totalCount: result.matches.length,
        candidatesConsidered: result.candidates_considered,
      });
    } catch (cause) {
      setError(errorMessage(cause));
      setResults(null);
    } finally {
      setRunning(null);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void (focus.trim() ? rank() : search());
  };

  return (
    <Panel
      title="Open opportunities"
      actions={
        results && (
          <span className={styles.resultCount}>
            {results.matched
              ? `${results.opportunities.length} ranked of ${results.candidatesConsidered} considered`
              : `${results.opportunities.length} shown of ${results.totalCount} matching`}
          </span>
        )
      }
    >
      <form className={styles.filters} onSubmit={submit}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="grants-keyword">
            Topic keyword
          </label>
          <input
            id="grants-keyword"
            className={styles.input}
            value={query.keyword}
            maxLength={200}
            onChange={(event) => update('keyword', event.target.value)}
            placeholder="metabolic disease therapeutics"
            autoComplete="off"
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="grants-agency">
            Agency
          </label>
          <input
            id="grants-agency"
            className={styles.input}
            value={query.agency}
            maxLength={200}
            onChange={(event) => update('agency', event.target.value)}
            placeholder="NIH, BARDA, DoD"
            autoComplete="off"
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="grants-program">
            Set-aside
          </label>
          <select
            id="grants-program"
            className={styles.input}
            value={query.program}
            onChange={(event) => update('program', event.target.value as GrantSearchQuery['program'])}
          >
            <option value="">Any</option>
            <option value="SBIR">SBIR</option>
            <option value="STTR">STTR</option>
            <option value="BOTH">SBIR/STTR</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="grants-closing-before">
            Closing before
          </label>
          <input
            id="grants-closing-before"
            className={styles.input}
            type="date"
            value={query.closing_before}
            onChange={(event) => update('closing_before', event.target.value)}
          />
        </div>
        <label className={styles.checkbox}>
          <input
            type="checkbox"
            checked={query.open_only}
            onChange={(event) => update('open_only', event.target.checked)}
          />
          Open only
        </label>
        <div className={styles.focusField}>
          <label className={styles.label} htmlFor="grants-focus">
            Research focus (optional — ranks results by topic fit)
          </label>
          <textarea
            id="grants-focus"
            className={styles.textarea}
            value={focus}
            maxLength={2000}
            rows={2}
            onChange={(event) => setFocus(event.target.value)}
            placeholder="GLP-1 co-agonists for metabolic disease, organoid safety screening"
          />
        </div>
        <div className={styles.searchActions}>
          <Button type="submit" variant="primary" disabled={running !== null}>
            {running === 'match'
              ? 'Ranking…'
              : running === 'search'
                ? 'Searching…'
                : focus.trim()
                  ? 'Search and rank by focus'
                  : 'Search'}
          </Button>
        </div>
      </form>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      {results && <ProviderStatus sources={results.sources} />}

      {results?.matched &&
        (rankedByModel(results.matcher) ? (
          <CaveatBand label="Unvalidated prediction.">
            Fit percentages and the reasoning beside them are produced by a language model reading
            each opportunity's topic text. They are not an agency assessment — read the solicitation
            before deciding what to apply for.
          </CaveatBand>
        ) : (
          <CaveatBand label="Keyword ranking, not a semantic match.">
            No language model ranked these{' '}
            {results.matcher === 'claude+lexical'
              ? 'because the model call failed'
              : 'because none is configured'}
            . The percentages are how many of your focus terms appear in each topic description —
            they are not a prediction of fit and not an agency assessment. Read the solicitation
            before deciding what to apply for.
          </CaveatBand>
        ))}

      {results === null ? (
        <EmptyState title="No search run yet">
          Filter by keyword, agency, set-aside or deadline and search. Results come from the
          providers live; add a research focus to have the topics ranked against it.
        </EmptyState>
      ) : results.opportunities.length === 0 ? (
        <EmptyState title="No opportunities matched those filters">
          The providers answered with nothing for this combination. Widen the keyword or clear the
          deadline bound.
        </EmptyState>
      ) : (
        <div className={styles.opportunities}>
          {results.opportunities.map((opportunity) => (
            <OpportunityCard
              key={key(opportunity)}
              opportunity={opportunity}
              match={results.scores.get(key(opportunity))}
              semantic={rankedByModel(results.matcher)}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}
