/**
 * Types mirroring `backend/app/services/screening/**` plus the small amount of presentation
 * logic the Screening tab needs.
 *
 * Nothing in here invents a value. Where the backend says a property is unavailable, the UI
 * renders that statement; where the backend calls something predicted, the label travels with
 * the number rather than being reconstructed here.
 */

/** Mirrors `sar.models.Descriptor`. */
export interface Descriptor {
  key: string;
  label: string;
  value: number;
  display: string;
  unit: string;
  method: string;
}

/** Mirrors `sar.models.RuleCheck`. */
export interface RuleCheck {
  key: string;
  label: string;
  value_display: string;
  limit: string;
  passed: boolean;
}

/** Mirrors `sar.models.RuleSet`. */
export interface RuleSet {
  key: string;
  name: string;
  citation: string;
  description: string;
  compliant: boolean;
  violations: number;
  checks: RuleCheck[];
}

/** Mirrors `sar.models.UnavailableProperty` — a property the backend refuses to invent. */
export interface UnavailableProperty {
  key: string;
  label: string;
  available: boolean;
  reason: string;
  requires: string;
}

/** Mirrors `sar.models.DescriptorProfile`. */
export interface DescriptorProfile {
  input_smiles: string;
  canonical_smiles: string;
  molecular_formula: string;
  inchikey: string;
  heavy_atom_count: number;
  descriptors: Descriptor[];
  rule_sets: RuleSet[];
  unavailable: UnavailableProperty[];
  basis: string;
  caveat: string;
}

/** Mirrors `sar.models.SubstituentSuggestion`. */
export interface SubstituentSuggestion {
  title: string;
  site: string;
  transformation: string;
  rationale: string;
  expected_effect: string;
  risk: string;
}

/** Mirrors `sar.models.SuggestionSet`. */
export interface SuggestionSet {
  canonical_smiles: string;
  source: 'llm' | 'rules';
  model: string;
  generator: string;
  suggestions: SubstituentSuggestion[];
  caveat: string;
  validated: boolean;
}

/** Mirrors `admet.models.Outcome`. `unavailable` is a first-class outcome, not an error. */
export type Outcome = 'favourable' | 'borderline' | 'unfavourable' | 'unavailable';

/** Mirrors `admet.models.RuleInput`. */
export interface RuleInput {
  label: string;
  value_display: string;
  threshold: string;
  within: boolean;
}

/** Mirrors `admet.models.AdmetEstimate`. `model_basis` is always populated and always shown. */
export interface AdmetEstimate {
  key: string;
  label: string;
  available: boolean;
  outcome: Outcome;
  verdict: string;
  scope: string;
  model_basis: string;
  citation: string;
  inputs: RuleInput[];
  reason: string;
  requires: string;
  predicted: boolean;
}

/** Mirrors `admet.models.StructuralAlert`. */
export interface StructuralAlert {
  key: string;
  label: string;
  concern: string;
  citation: string;
  matched: boolean;
}

/** Mirrors `admet.models.AdmetProfile`. */
export interface AdmetProfile {
  canonical_smiles: string;
  molecular_formula: string;
  estimates: AdmetEstimate[];
  alerts: StructuralAlert[];
  caveat: string;
  alert_caveat: string;
}

export type OutcomeTone = 'warning' | 'validated' | 'idle';

/**
 * Outcome → the product's status vocabulary. Borderline reads amber alongside unfavourable
 * rather than emerald: on a safety surface, "one property outside the envelope" is a prompt to
 * look, not a pass.
 */
export function outcomeTone(outcome: Outcome): OutcomeTone {
  switch (outcome) {
    case 'favourable':
      return 'validated';
    case 'borderline':
    case 'unfavourable':
      return 'warning';
    case 'unavailable':
      return 'idle';
  }
}

export interface LiabilityFlag {
  key: string;
  title: string;
  body: string;
  basis: string;
  /** True when the flag comes from a predicted classification rather than a substructure match. */
  predicted: boolean;
}

/**
 * The toxicity/liability list, assembled from what the backend already said.
 *
 * Two sources, kept distinguishable: rule classifications that came out unfavourable (predicted)
 * and structural-alert substructure matches (deterministic matches to literature motifs). A
 * borderline classification is not promoted to a flag — it stays in the ADMET section with its
 * own amber outcome pill — so this list means "something to act on".
 */
export function liabilityFlags(profile: AdmetProfile): LiabilityFlag[] {
  const fromRules = profile.estimates
    .filter((estimate) => estimate.available && estimate.outcome === 'unfavourable')
    .map((estimate) => ({
      key: estimate.key,
      title: `${estimate.label} — ${estimate.verdict}`,
      body: estimate.scope,
      basis: estimate.model_basis,
      predicted: estimate.predicted,
    }));

  const fromAlerts = profile.alerts
    .filter((alert) => alert.matched)
    .map((alert) => ({
      key: `alert:${alert.key}`,
      title: `${alert.label} (structural alert)`,
      body: alert.concern,
      basis: `Substructure match. ${alert.citation}`,
      predicted: false,
    }));

  return [...fromRules, ...fromAlerts];
}

/** The estimates the UI shows in the ADMET section, unavailable ones included. */
export function admetOrder(profile: AdmetProfile): AdmetEstimate[] {
  return profile.estimates;
}

const SMILES_MAX_LENGTH = 600;

/**
 * A cheap client-side gate so an obviously empty or oversized box does not cost a round trip.
 * Structural validity is the server's call — RDKit is the only thing that can make it.
 */
export function smilesInputError(smiles: string): string | null {
  const trimmed = smiles.trim();
  if (trimmed.length === 0) {
    return 'Enter a SMILES string to profile a structure.';
  }
  if (trimmed.length > SMILES_MAX_LENGTH) {
    return `SMILES is limited to ${SMILES_MAX_LENGTH} characters.`;
  }
  return null;
}

export interface ExampleStructure {
  name: string;
  smiles: string;
  note: string;
}

/**
 * Real, published structures to try the tab with — not sample *results*. Every number shown
 * for these is computed by the backend from the structure at request time.
 */
export const EXAMPLE_STRUCTURES: ExampleStructure[] = [
  {
    name: 'Aspirin',
    smiles: 'CC(=O)OC1=CC=CC=C1C(=O)O',
    note: 'Small, polar, no alerts',
  },
  {
    name: 'Caffeine',
    smiles: 'CN1C=NC2=C1C(=O)N(C)C(=O)N2C',
    note: 'CNS-penetrant property space',
  },
  {
    name: 'Terfenadine',
    smiles:
      'CC(C)(C)c1ccc(cc1)C(O)CCCN1CCC(CC1)C(O)(c1ccccc1)c1ccccc1',
    note: 'Withdrawn — matches the hERG pharmacophore',
  },
  {
    name: 'Atorvastatin',
    smiles:
      'CC(C)c1c(C(=O)Nc2ccccc2)c(-c2ccccc2)c(-c2ccc(F)cc2)n1CC[C@@H](O)C[C@@H](O)CC(=O)O',
    note: 'Large and polar — outside the passive-absorption region',
  },
];

/* ---- Patents: keyword prior art, never structural novelty ---- */

/** Mirrors `patents.models.QueryDerivation`. */
export type QueryDerivation = 'keywords' | 'structure_formula' | 'structure_formula_and_keywords';

export interface StructureBasis {
  input_smiles: string;
  canonical_smiles: string;
  molecular_formula: string;
  inchikey: string;
  /** Always false on this source: it indexes text, not structures. */
  searched_by_structure: boolean;
  note: string;
}

export interface DerivedQuery {
  query_used: string;
  derived_from: QueryDerivation;
  terms: string[];
  derivation: string;
  field_scope: string;
  structure: StructureBasis | null;
}

export interface PatentHit {
  application_number: string;
  patent_number: string;
  publication_number: string;
  title: string;
  abstract: string;
  filing_date: string;
  grant_date: string;
  publication_date: string;
  status: string;
  applicants: string[];
  inventors: string[];
  cpc_classifications: string[];
  url: string;
}

/**
 * Mirrors `patents.models.PatentLandscape`.
 *
 * `source_available: false` is a normal outcome (the upstream API needs a key), and the UI must
 * render `source_status` for it — an empty hit list from an unavailable source is not a finding.
 */
export interface PatentLandscape {
  source: string;
  source_available: boolean;
  source_status: string;
  query: DerivedQuery;
  sort: string;
  page_size: number;
  offset: number;
  returned: number;
  total_found: number | null;
  hits: PatentHit[];
  /** Non-empty only when the search actually ran and matched nothing. */
  no_match_statement: string;
  caveat: string;
  unavailable: UnavailableProperty[];
}

/** Matches `patents.query.MAX_KEYWORD_LENGTH`, so the box stops at the bound the server enforces. */
export const PATENT_KEYWORDS_MAX_LENGTH = 200;
