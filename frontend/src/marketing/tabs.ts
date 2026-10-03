import assistantShot from './screens/assistant.webp';
import auditShot from './screens/audit.webp';
import grantsShot from './screens/grants.webp';
import literatureShot from './screens/literature.webp';
import protocolShot from './screens/protocol.webp';
import regulatoryShot from './screens/regulatory.webp';
import screeningShot from './screens/screening.webp';
import settingsShot from './screens/settings.webp';
import workspaceShot from './screens/workspace.webp';

export type TabGroup = 'Research' | 'Platform';

export interface ProductTab {
  id: string;
  name: string;
  group: TabGroup;
  /** The one-line claim the screenshot below it has to support. */
  title: string;
  /** Short enough to be a meta description on the tab's own page. */
  summary: string;
  body: string;
  points: string[];
  shot: string;
  alt: string;
}

/** The navigation subdivisions: the five tabs that do research, then the four that run it. */
export const TAB_GROUPS: { name: TabGroup; blurb: string }[] = [
  { name: 'Research', blurb: 'The work itself — evidence in, cited output out.' },
  { name: 'Platform', blurb: 'What the work runs on: one assistant, one team, one trail.' },
];

/** The marketing route that belongs to a tab. */
export function tabPath(tab: Pick<ProductTab, 'id'>): string {
  return `/product/${tab.id}`;
}

export function tabsInGroup(group: TabGroup): ProductTab[] {
  return PRODUCT_TABS.filter((tab) => tab.group === group);
}

/**
 * One entry per destination in the product's navigation, in navigation order.
 *
 * Every screenshot is the running product, captured against public databases and the
 * repository's own fixture papers — no invented findings, no customer data.
 */
export const PRODUCT_TABS: ProductTab[] = [
  {
    id: 'literature',
    name: 'Literature',
    group: 'Research',
    summary:
      'Extract the values you name from papers you upload or find on PubMed, each cell linked to the page it was read from.',
    title: 'A table of extracted values, each one opening the sentence it came from.',
    body: 'Say what you need pulled out — sample size, dosing regimen, endpoint — and upload the papers or point at PubMed. The columns are built from your goal, not from a fixed schema, and no cell is filled in from the model\u2019s memory.',
    points: [
      'Every value carries its paper and page, and clicking it opens that passage.',
      'A value the paper does not state is left empty rather than guessed.',
      'Export to Excel or CSV with a linked sources sheet.',
    ],
    shot: literatureShot,
    alt: 'The Literature tab: an extraction table built from two uploaded papers, each value tagged with the page it was read from.',
  },
  {
    id: 'screening',
    name: 'Screening',
    group: 'Research',
    summary:
      'Profile a compound from SMILES: descriptors, rule-set checks and ADMET estimates, led by a digest of what needs reviewing.',
    title: 'The compound opens with what needs reviewing, not with what is fine.',
    body: 'Paste SMILES and get deterministic descriptors, rule-set checks and QSAR-based ADMET estimates. The profile leads with a review digest: fired liabilities first, then borderline calls, then rule violations, then the properties we cannot ground at all.',
    points: [
      'Each digest row links down to the evidence behind it.',
      'ADMET cards sort worst-first, so nothing important sits below the fold.',
      'Estimates are labelled as estimates. This is not a safety assessment.',
    ],
    shot: screeningShot,
    alt: 'The Screening tab: a review-first digest above descriptor and ADMET cards for a profiled compound.',
  },
  {
    id: 'protocol',
    name: 'Protocol',
    group: 'Research',
    summary:
      'Draft a protocol with materials, controls, master-mix arithmetic and version history, exportable as a notebook bundle.',
    title: 'A first-draft protocol with materials, controls and the arithmetic done.',
    body: 'Describe the experiment and get a structured draft: materials, step-by-step method, controls to include, and a master-mix calculator that shows its working. Drafts are versioned, so you can see what changed between runs.',
    points: [
      'Controls and caveats are drafted with the method, not bolted on.',
      'Version history keeps every saved draft exactly as produced.',
      'Export a vendor-neutral notebook bundle any ELN can import.',
    ],
    shot: protocolShot,
    alt: 'The Protocol tab: a drafted Western blot protocol with a materials list and numbered steps.',
  },
  {
    id: 'regulatory',
    name: 'Regulatory',
    group: 'Research',
    summary:
      'Draft preclinical narratives and IND sections whose every number is checked back against the study record you entered.',
    title: 'Every number in the draft is checked back against your study table.',
    body: 'Enter the study record and get a preclinical narrative or IND module section. Each number in the prose is matched by exact decimal comparison against the record you submitted — no language model is involved in that check — and anything the record does not cover is listed as a stated gap.',
    points: [
      'Doses appear exactly as entered: never rounded, never converted.',
      'Gaps are named in the draft instead of being written around.',
      'A guideline check says which requirement each statement answers.',
    ],
    shot: regulatoryShot,
    alt: 'The Regulatory tab: a drafted preclinical narrative beside its numeric audit, showing matched numbers and stated gaps.',
  },
  {
    id: 'grants',
    name: 'Grants',
    group: 'Research',
    summary:
      'Search live grants.gov and SBIR opportunities, check eligibility, build an SF-424 budget and run a mock review board.',
    title: 'Funding you are actually eligible for, with the budget already shaped.',
    body: 'Search live grants.gov and SBIR opportunities by topic, agency and focus, then check eligibility against federal rules you can edit, build an SF-424 (R&R) budget from R&D costs, and run a mock review-board critique before you submit.',
    points: [
      'Opportunities come from the agencies\u2019 own feeds, with deadlines shown.',
      'When a source is unavailable, the page says so rather than showing less.',
      'Eligibility thresholds are visible and editable, not hidden in code.',
    ],
    shot: grantsShot,
    alt: 'The Grants tab: funding opportunities returned from grants.gov with deadlines and agency filters.',
  },
  {
    id: 'assistant',
    name: 'Assistant',
    group: 'Platform',
    summary:
      'One chat across every tab, limited to sixteen typed read-only tools, with off-topic and dangerous requests refused before any model call.',
    title: 'A chat that can only reach the sixteen read-only tools it is allowed.',
    body: 'Ask across every tab in one place. The assistant shows what it is doing as it works, takes a follow-up question while it is still answering, and reads a PDF you attach by reference — the bytes never leave for the model provider.',
    points: [
      'Off-topic questions are refused before any model call, at no cost.',
      'Each tool call is shown with its result and a link to the source.',
      'Dangerous requests are refused deterministically, not by persuasion.',
    ],
    shot: assistantShot,
    alt: 'The Assistant tab: an answer assembled from a clinical-trials tool call, with the tool trace shown above it.',
  },
  {
    id: 'workspace',
    name: 'Workspace',
    group: 'Platform',
    summary:
      'Share saved literature, protocols and drafts through workspaces with seats, server-enforced roles and single-use invitations.',
    title: 'Shared work with seats, roles and single-use invitations.',
    body: 'Saved literature, protocols, screens and drafts belong to a workspace rather than to one laptop. Invite colleagues, give them a role, and keep private work private — a member only reads what the workspace holds.',
    points: [
      'Owner, admin, member and viewer roles are enforced server-side.',
      'Invitations are single-use, with seat limits per workspace.',
      'Papers uploaded inside a workspace are readable by its members.',
    ],
    shot: workspaceShot,
    alt: 'The Workspace tab: a shared workspace with its members, roles and invitation controls.',
  },
  {
    id: 'audit',
    name: 'Audit',
    group: 'Platform',
    summary:
      'An append-only trail of documents stored, model calls made, tools invoked, exports produced and requests refused.',
    title: 'An append-only record of what was asked, called, read and refused.',
    body: 'Every document stored, model call made, tool invoked, invitation sent and export produced is written to a trail you can read and filter — including the outcomes you would rather not advertise, like refusals and failures.',
    points: [
      'Document names are fingerprinted rather than stored in the trail.',
      'Refusals and errors are recorded alongside successes.',
      'Filter by event type to answer "what did it send to the model?".',
    ],
    shot: auditShot,
    alt: 'The Audit tab: a filtered timeline of assistant questions, tool calls and document events.',
  },
  {
    id: 'settings',
    name: 'Settings',
    group: 'Platform',
    summary:
      'What this deployment is actually configured to do — sessions, model routing, spend caps, encryption and retention — read from the server.',
    title: 'What this deployment is configured to do, read from the running server.',
    body: 'Sign-in and session lifetimes, which model is called and what it may spend, how stored papers are encrypted and how long anything is kept — reported from the server itself rather than from a page of hard-coded reassurance.',
    points: [
      'A daily call and cost budget caps what one account can spend.',
      'Encryption and retention state are shown as configured, not as intended.',
      'No model API key of your own to buy, rotate or expose.',
    ],
    shot: settingsShot,
    alt: 'The Settings tab: authentication, model routing and data-handling values read from the running deployment.',
  },
];
