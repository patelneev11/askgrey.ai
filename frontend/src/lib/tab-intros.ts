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
 * What each destination is for and what to do first there, shown once per tab. Sample surfaces
 * say so here rather than letting a new user assume the numbers came from their data.
 */
export const TAB_INTROS: TabIntro[] = [
  {
    id: 'literature',
    path: '/literature',
    title: 'Literature turns a pile of papers into a cited table',
    body: [
      'Add PDFs or PMC links, describe what to pull out of them, and each phrase in that goal becomes a column. Click any value to open the passage it came from; exports keep the citations attached.',
      'This is the one tab wired end-to-end to live services rather than sample records.',
    ],
    caveat:
      'Text from the documents you add is sent to Anthropic (Claude) to generate the columns. Do not add material you are not permitted to share with a third-party processor.',
  },
  {
    id: 'screening',
    path: '/screening',
    title: 'Screening profiles candidate compounds',
    body: [
      'Pick a compound from the queue on the left and its predicted profile — binding, ADMET and liability flags — opens on the right.',
      'The compounds here are sample records; loading your own series is not wired up yet.',
    ],
    caveat:
      'Affinity, ADMET and toxicity figures are computational approximations (RDKit/LLM), not validated assay results. Confirm experimentally before making series decisions.',
  },
  {
    id: 'protocol',
    path: '/protocol',
    title: 'Protocol drafts an experimental method',
    body: [
      'The outline on the left is the shape of the experiment; each step opens its full method, reagents and timings on the right.',
      'The protocol here is a sample draft, not generated from your workspace.',
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
    title: 'Grants scores open federal calls against your focus',
    body: [
      "Opportunities are ranked by how well their topic text matches the workspace's research focus, with deadline and funding ceiling on each card, then critiqued by a mock review board.",
      'The grants.gov and SBIR/STTR backend is built, but this page still shows sample opportunities — treat the fit scores and deadlines as illustrative.',
    ],
  },
  {
    id: 'workspace',
    path: '/workspace',
    title: 'Workspace holds your org, seats and connected systems',
    body: [
      'Members, roles and the ELN and storage integrations your agents can read from are listed here.',
      'Everything on this page is a sample record and read-only: inviting members and connecting systems is not implemented yet.',
    ],
  },
  {
    id: 'audit',
    path: '/audit',
    title: 'Audit records what the agents did',
    body: [
      'Agent runs, document reads and exports land here with the model and inputs that produced them, filterable by kind.',
      'The timeline shown is sample data; your own activity is not recorded here yet.',
    ],
  },
  {
    id: 'settings',
    path: '/settings',
    title: 'Settings will hold workspace-wide configuration',
    body: [
      'Model routing, retention and integration credentials are configured here for everyone in the workspace.',
      'These values are a sample of the settings model and every control is read-only — apart from replaying the first-run tour, which works.',
    ],
  },
];
