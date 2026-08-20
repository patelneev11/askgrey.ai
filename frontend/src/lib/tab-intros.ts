export interface TabIntro {
  /** Stable id: acknowledgement is stored under it, so renaming resets the notice. */
  id: string;
  path: string;
  title: string;
  body: string[];
  /**
   * The reliability caveat for this surface, where one applies. Its presence turns the notice
   * into something the user accepts rather than closes.
   */
  caveat?: string;
}

/**
 * What each destination is for and what to do first there, shown once per tab. A surface whose
 * numbers are approximations, or whose scope is narrower than its name suggests, says so here
 * rather than letting a new user assume otherwise.
 */
export const TAB_INTROS: TabIntro[] = [
  {
    id: 'assistant',
    path: '/assistant',
    title: 'The assistant runs the other tabs for you',
    body: [
      'Ask a research question in one place and it calls the same services the tabs do — PubMed, PubChem, ClinicalTrials.gov, descriptors and ADMET, patent and grant search, eligibility, budgets and drafting — and shows every call it made with its sources.',
      'Press Reference to point it at work you already saved: your Literature workspace, a saved screening or grants result, a saved protocol. It can read and draft, but it cannot save, edit or delete anything, and it cannot file work in an external lab notebook.',
    ],
    caveat:
      'Answers are model-generated and require expert review. Predictions are not measurements, and nothing the assistant says is legal, regulatory or clinical advice.',
  },
  {
    id: 'literature',
    path: '/literature',
    title: 'Literature turns a pile of papers into a cited table',
    body: [
      'Add PDFs or PMC links, describe what to pull out of them, and each phrase in that goal becomes a column. Click any value to open the passage it came from; exports keep the citations attached.',
      'Wired end-to-end to live services: PubMed and PMC for the papers, Anthropic for the columns.',
    ],
    caveat:
      'Text from the documents you add is sent to Anthropic (Claude) to generate the columns. Do not add material you are not permitted to share with a third-party processor.',
  },
  {
    id: 'screening',
    path: '/screening',
    title: 'Screening profiles candidate compounds',
    body: [
      'Enter a SMILES string on the left and the profile opens on the right: RDKit descriptors, drug-likeness rule sets, liability flags and ADMET classifications, each labelled with the published rule it came from.',
      'Properties that cannot be grounded — binding affinity without a target structure, plasma protein binding, per-isoform CYP inhibition — are reported as unavailable rather than estimated.',
    ],
    caveat:
      'ADMET, liability and toxicity values are computational approximations (RDKit/LLM), not validated assay results. Confirm experimentally before making series decisions.',
  },
  {
    id: 'protocol',
    path: '/protocol',
    title: 'Protocol drafts an experimental method',
    body: [
      'The outline on the left is the shape of the experiment; each step opens its full method, reagents and timings on the right.',
      'The draft is generated from the goal you describe, and the master mix calculator does exact arithmetic on the volumes you enter. Nothing here is pre-filled sample text.',
      'Saved protocols and their version history persist to your account, so a draft is still there after a reload.',
    ],
    caveat:
      'Agent-drafted content requires qualified researcher review before anyone runs it at the bench.',
  },
  {
    id: 'regulatory',
    path: '/regulatory',
    title: 'Regulatory drafts sections and checks its own numbers',
    body: [
      'Three drafting aids share the tab: a preclinical narrative whose every number is re-checked against the study record you entered, IND module 3/4 sections drafted against a dated CTD heading tree, and a keyword-signal comparison of a draft section against FDA, EMA and PMDA expectations.',
      'These run against live services on the data you enter. Nothing is pre-filled, and a section with nothing to say comes back empty with the gap stated rather than filled.',
    ],
    caveat:
      'Agent-drafted content. Requires qualified regulatory affairs review before any regulatory use. Nothing here is a regulatory opinion or a filing-ready document.',
  },
  {
    id: 'grants',
    path: '/grants',
    title: 'Grants finds open federal calls and costs a proposal',
    body: [
      'Search grants.gov and SBIR.gov by keyword, agency, set-aside or deadline; add a research focus and the topics are ranked against it. Eligibility and the budget are computed from editable rule files, not guessed.',
      'Opportunities, deadlines and funding ceilings come from the providers live — a provider that is unreachable says so instead of being filled in.',
    ],
    caveat:
      "Fit percentages come from a language model reading each opportunity's topic text, and the eligibility and budget results are an aid to review, not a legal or financial determination. Check the solicitation before relying on any of it.",
  },
  {
    id: 'workspace',
    path: '/workspace',
    title: 'Workspace counts what this account holds',
    body: [
      'Your stored papers and their retention window, the work you have saved from each tab, your audit activity and which data sources this deployment can reach — all counted from your own records.',
      'An account is the only unit that exists today: shared workspaces, seats, per-member roles and third-party integrations are not built, so the page says so rather than showing them.',
    ],
  },
  {
    id: 'audit',
    path: '/audit',
    title: 'Audit records what the agents did',
    body: [
      'Your sign-ins, document reads, model calls and exports land here with the provenance that produced them, filterable by kind.',
      'Only this workspace’s own events are recorded, kept for a configured window, and never the document text itself.',
    ],
  },
  {
    id: 'settings',
    path: '/settings',
    title: 'Settings reports how this deployment is configured',
    body: [
      'The model in use, how long a sign-in lasts, how stored papers are encrypted, how long they and the audit log are kept, and every sign-in this account currently holds.',
      'These are the running deployment’s own values, not editable from the app. Signing out everywhere and replaying the first-run tour are the two actions here.',
    ],
  },
];
