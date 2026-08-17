import type {
  Citation,
  ExtractionCell,
  ExtractionTable,
  MatchQuality,
  PaperRow,
} from '@/lib/extraction';
import type {
  AdmetEstimate,
  AdmetProfile,
  DescriptorProfile,
  PatentLandscape,
  SuggestionSet,
} from '@/lib/screening';

export function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    document_id: 'doc-1',
    source_url: 'https://example.org/paper.pdf',
    page_number: 4,
    page_width: 612,
    page_height: 792,
    block_id: 'p4-b2',
    text: '73 patients were randomized to ziprasidone or placebo',
    start_char: 120,
    end_char: 173,
    bbox: { x0: 72, top: 300, x1: 520, bottom: 316 },
    rects: [{ x0: 72, top: 300, x1: 520, bottom: 316 }],
    match: 'exact',
    ...overrides,
  };
}

export function grounded(value: string, match: MatchQuality = 'exact'): ExtractionCell {
  return { value, citation: citation({ match }), status: 'grounded', note: '' };
}

export function ungrounded(value: string): ExtractionCell {
  return { value, citation: null, status: 'ungrounded', note: 'quote not found in parsed text' };
}

export function notFound(): ExtractionCell {
  return { value: null, citation: null, status: 'not_found', note: '' };
}

export function paperRow(overrides: Partial<PaperRow> = {}): PaperRow {
  return {
    document_id: 'doc-1',
    title: 'Ziprasidone in acute mania',
    source_url: 'https://example.org/paper.pdf',
    filename: 'paper.pdf',
    page_count: 9,
    status: 'extracted',
    cells: {},
    warnings: [],
    ...overrides,
  };
}

export function table(overrides: Partial<ExtractionTable> = {}): ExtractionTable {
  return {
    goal: 'sample size',
    columns: [{ key: 'sample_size', label: 'sample size', description: '' }],
    rows: [paperRow({ cells: { sample_size: grounded('73 patients') } })],
    ...overrides,
  };
}

/**
 * Screening fixtures, shaped like the terfenadine response the backend actually returns —
 * a compound that fires the hERG pharmacophore, so the liability path is exercised.
 */
export function descriptorProfile(overrides: Partial<DescriptorProfile> = {}): DescriptorProfile {
  return {
    input_smiles: 'CC(C)(C)c1ccc(cc1)C(O)CCCN1CCC(CC1)C(O)(c1ccccc1)c1ccccc1',
    canonical_smiles: 'CC(C)(C)c1ccc(C(O)CCCN2CCC(C(O)(c3ccccc3)c3ccccc3)CC2)cc1',
    molecular_formula: 'C32H41NO2',
    inchikey: 'GUGOEEXESWIERI-UHFFFAOYSA-N',
    heavy_atom_count: 35,
    descriptors: [
      {
        key: 'molecular_weight',
        label: 'Molecular weight',
        value: 471.69,
        display: '471.69 g/mol',
        unit: 'g/mol',
        method: 'RDKit Descriptors.MolWt',
      },
      {
        key: 'clogp',
        label: 'cLogP',
        value: 6.19,
        display: '6.19',
        unit: '',
        method: 'RDKit Crippen.MolLogP (Wildman-Crippen)',
      },
    ],
    rule_sets: [
      {
        key: 'lipinski',
        name: "Lipinski's rule of five",
        citation: 'Lipinski et al., Adv. Drug Deliv. Rev. 23 (1997) 3-25',
        description: 'A guideline for oral absorption, not a pass/fail gate.',
        compliant: false,
        violations: 2,
        checks: [
          {
            key: 'molecular_weight',
            label: 'Molecular weight',
            value_display: '471.69 g/mol',
            limit: '<= 500 g/mol',
            passed: true,
          },
          { key: 'clogp', label: 'cLogP', value_display: '6.19', limit: '<= 5', passed: false },
        ],
      },
    ],
    unavailable: [
      {
        key: 'binding_affinity',
        label: 'Binding affinity',
        available: false,
        reason: 'Not available without a target structure and a docking or free-energy pipeline.',
        requires: 'A target structure and a docking or free-energy calculation.',
      },
    ],
    basis: 'RDKit 2D descriptors computed from the submitted structure; no model inference.',
    caveat: 'Computed descriptors from the 2D structure (RDKit). Deterministic calculations.',
    ...overrides,
  };
}

export function admetEstimate(overrides: Partial<AdmetEstimate> = {}): AdmetEstimate {
  return {
    key: 'gi_absorption',
    label: 'GI absorption',
    available: true,
    outcome: 'favourable',
    verdict: 'Inside the Egan well-absorbed region (predicted)',
    scope: 'Classification of passive absorption only.',
    model_basis: "Egan's physicochemical delineation of passive human intestinal absorption.",
    citation: 'Egan, Merz & Baldwin, J. Med. Chem. 43 (2000) 3867-3877',
    inputs: [
      { label: 'TPSA', value_display: '43.7 A^2', threshold: '<= 131.6 A^2', within: true },
    ],
    reason: '',
    requires: '',
    predicted: true,
    ...overrides,
  };
}

export function admetProfile(overrides: Partial<AdmetProfile> = {}): AdmetProfile {
  return {
    canonical_smiles: 'CC(C)(C)c1ccc(C(O)CCCN2CCC(C(O)(c3ccccc3)c3ccccc3)CC2)cc1',
    molecular_formula: 'C32H41NO2',
    estimates: [
      admetEstimate(),
      admetEstimate({
        key: 'herg',
        label: 'hERG liability',
        outcome: 'unfavourable',
        verdict: 'Matches the basic-amine/lipophilic-aromatic hERG pharmacophore (predicted risk)',
        scope: 'A feature-count flag, not an IC50, a percentage block or a probability.',
        model_basis: 'Published hERG pharmacophore features counted on the structure.',
        inputs: [
          {
            label: 'Basic (protonatable) nitrogen',
            value_display: 'present',
            threshold: 'absent',
            within: false,
          },
        ],
      }),
      admetEstimate({
        key: 'plasma_protein_binding',
        label: 'Plasma protein binding',
        available: false,
        outcome: 'unavailable',
        verdict: '',
        scope: '',
        model_basis: 'No estimate is produced. Published PPB models are regressions on measured fu.',
        citation: '',
        inputs: [],
        reason: 'Unavailable. Fraction bound cannot be derived from 2D descriptors.',
        requires: 'A validated QSAR trained on measured fu, or an equilibrium-dialysis measurement.',
        predicted: false,
      }),
    ],
    alerts: [
      {
        key: 'basic_amine_aromatic',
        label: 'Basic amine with lipophilic aromatic character',
        concern: 'hERG pharmacophore features associated with cardiac liability.',
        citation: 'Cavalli et al., J. Med. Chem. 45 (2002) 3844-3853',
        matched: true,
      },
      {
        key: 'furan',
        label: 'Furan',
        concern: 'Bioactivation to reactive epoxides.',
        citation: 'Hollenberg et al., Chem. Res. Toxicol. 21 (2008) 189-205',
        matched: false,
      },
    ],
    caveat:
      'Predicted ADMET classifications from published physicochemical rules applied to computed descriptors — not measured, not fitted to this compound, and not a probability.',
    alert_caveat:
      'Structural alerts are substructure matches to groups reported in the literature as liability motifs; no match is not evidence of safety.',
    ...overrides,
  };
}

export function suggestionSet(overrides: Partial<SuggestionSet> = {}): SuggestionSet {
  return {
    canonical_smiles: 'CC(C)(C)c1ccc(C(O)CCCN2CCC(C(O)(c3ccccc3)c3ccccc3)CC2)cc1',
    source: 'llm',
    model: 'claude-sonnet-4-5',
    generator: 'Claude, prompted for qualitative medicinal-chemistry heuristics only',
    suggestions: [
      {
        title: 'Replace the tert-butyl group with a carboxylic acid',
        site: 'para position of the phenyl ring',
        transformation: 'tert-butyl -> carboxylate',
        rationale: 'Lowers lipophilicity and adds a charge that disfavours hERG binding.',
        expected_effect: 'Lower cLogP; reduced likelihood of the hERG pharmacophore match.',
        risk: 'May reduce permeability and target engagement.',
      },
    ],
    caveat:
      'Unvalidated heuristic suggestions, not predictions of activity or a synthesis route. Requires medicinal-chemist review.',
    validated: false,
    ...overrides,
  };
}

export function patentLandscape(overrides: Partial<PatentLandscape> = {}): PatentLandscape {
  return {
    source: 'USPTO Open Data Portal — Patent Search (patent applications)',
    source_available: true,
    source_status: '',
    query: {
      query_used: 'C32H41NO2 AND antihistamine',
      derived_from: 'structure_formula_and_keywords',
      terms: ['C32H41NO2', 'antihistamine'],
      derivation:
        'A structure was submitted, but the upstream index holds text rather than chemical structures. The search ran on the molecular formula RDKit computed from the structure (C32H41NO2) AND the keywords antihistamine — not on the structure itself.',
      field_scope:
        'Free-form text search across the indexed USPTO application fields (title, abstract and bibliographic metadata). Full claim text is not searched.',
      structure: {
        input_smiles: 'CC(C)(C)c1ccc(cc1)C(O)CCCN1CCC(CC1)C(O)(c1ccccc1)c1ccccc1',
        canonical_smiles: 'CC(C)(C)c1ccc(C(O)CCCN2CCC(C(O)(c3ccccc3)c3ccccc3)CC2)cc1',
        molecular_formula: 'C32H41NO2',
        inchikey: 'GUGOEEXESWIERI-UHFFFAOYSA-N',
        searched_by_structure: false,
        note: 'The upstream API indexes text, not chemical structures, so the structure itself was never searched.',
      },
    },
    sort: 'relevance',
    page_size: 25,
    offset: 0,
    returned: 1,
    total_found: 3,
    hits: [
      {
        application_number: '10123456',
        patent_number: '6242460',
        publication_number: '',
        title: 'Piperidine derivatives useful as antihistamines',
        abstract: '',
        filing_date: '1999-04-15',
        grant_date: '2001-06-05',
        publication_date: '',
        status: 'Patented Case',
        applicants: ['Example Pharma Inc.'],
        inventors: [],
        cpc_classifications: ['C07D211/22'],
        url: 'https://ppubs.uspto.gov/dirsearch-public/patents/html/fullText?patentNumber=6242460',
      },
    ],
    no_match_statement: '',
    caveat:
      'Keyword-based prior-art results from a text search of USPTO patent application titles, abstracts and bibliographic metadata. This is not a structural similarity search, not a novelty assessment and not a freedom-to-operate analysis.',
    unavailable: [
      {
        key: 'structural_similarity_search',
        label: 'Structural similarity / substructure prior-art search',
        available: false,
        reason: 'The integrated source is a keyword index over patent text and metadata.',
        requires: 'A structure-searchable patent chemistry database plus a licence for it.',
      },
      {
        key: 'novelty_score',
        label: 'Novelty score',
        available: false,
        reason: 'Novelty is a legal determination over the whole body of prior art.',
        requires: 'Claim-level analysis by a registered patent practitioner.',
      },
    ],
    ...overrides,
  };
}
