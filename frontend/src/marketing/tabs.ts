import assistantClip from './clips/assistant.mp4';
import auditClip from './clips/audit.mp4';
import grantsClip from './clips/grants.mp4';
import literatureClip from './clips/literature.mp4';
import protocolClip from './clips/protocol.mp4';
import regulatoryClip from './clips/regulatory.mp4';
import screeningClip from './clips/screening.mp4';
import settingsClip from './clips/settings.mp4';
import workspaceClip from './clips/workspace.mp4';
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

/** One beat of the tab's actual workflow: what you hand it, what it does, what comes back. */
export interface TabStep {
  title: string;
  detail: string;
}

/** Something the tab leaves behind — a saved record, a file, a trail entry. */
export interface TabOutput {
  label: string;
  detail: string;
}

/** The tab's own screen recording: one unedited take of the feature it is about. */
export interface TabClip {
  src: string;
  /** The moment the take is built around, read before the video plays. */
  moment: string;
  label: string;
}

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
  clip: TabClip;
  /** What a run actually consists of, in order. */
  steps: TabStep[];
  outputs: TabOutput[];
  /** What the tab will not do, in its own words rather than in a footnote. */
  limits: string[];
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
 * Every screenshot and every clip is the running product, captured against public databases and
 * the repository's own fixture papers — no invented findings, no customer data. The homepage
 * carries `title`/`summary`/`points`; `steps`, `outputs` and `limits` exist for the tab's own
 * page, which has to answer "how does this actually run" rather than repeat the index.
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
    clip: {
      src: literatureClip,
      moment: 'Two trial PDFs in, three named columns out, then one cell opens its page.',
      label:
        'Screen recording: two trial PDFs are uploaded, an extraction goal names three columns, and a cited value opens the passage it was read from.',
    },
    steps: [
      {
        title: 'Add the papers',
        detail:
          'Upload PDFs or paste a PMC or publisher link. Links are fetched server-side against an allow-list and a size cap; the file is checked for a real PDF header before anything parses it. Each paper is parsed page by page, so a page number is a fact about the document rather than an estimate.',
      },
      {
        title: 'Name the columns in plain English',
        detail:
          '"sample size, dosing regimen, primary efficacy endpoint" becomes three columns. There is no fixed schema to fit, so a pharmacology comparison and a tox summary are the same feature with a different goal.',
      },
      {
        title: 'Read values that carry their source',
        detail:
          'Each extracted value is matched back against the parsed text. An exact hit is tagged with its page; a paraphrase is tagged close wording; a value found nowhere in the document is marked as having no source rather than being presented as a finding.',
      },
      {
        title: 'Verify in one click',
        detail:
          'Click any value and the pane beside the table opens that page with the sentence it came from. Checking a number is a click, not a search through a PDF you have already read twice.',
      },
    ],
    outputs: [
      {
        label: 'A saved table',
        detail:
          'The grid, its sources and its citations belong to your workspace and reopen after a reload, on another machine, for the colleagues who share it.',
      },
      {
        label: 'Excel with a sources sheet',
        detail:
          'An .xlsx whose cited values link to a second sheet of quotes and page numbers, so a reviewer can follow any figure back without the app.',
      },
      {
        label: 'CSV for a pipeline',
        detail: 'One row per paper, your columns as headers, citations preserved as a column.',
      },
    ],
    limits: [
      'Extraction is a language model reading parsed text: confirm each value against its passage before it leaves your desk.',
      'A scanned PDF with no text layer cannot be parsed — the paper is listed with that reason instead of being quietly dropped.',
      'Text from the documents you add is sent to Anthropic to build the columns, so do not add material you may not share with a processor.',
    ],
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
    clip: {
      src: screeningClip,
      moment: 'A withdrawn drug is profiled and its hERG and CYP flags are already at the top.',
      label:
        'Screen recording: a SMILES string is profiled and the review-first digest leads with fired liabilities, borderline calls and ungrounded properties.',
    },
    steps: [
      {
        title: 'Give it a structure',
        detail:
          'SMILES is parsed with RDKit. Molecular weight, logP, TPSA, donors and acceptors, rotatable bonds and Fsp3 are computed from the structure — arithmetic, not prediction — so those numbers are reproducible outside the product.',
      },
      {
        title: 'Published rule sets run first',
        detail:
          'Lipinski, Veber, Egan and structural-alert sets are evaluated before anything is estimated, and every result names the rule it came from instead of arriving as an opinion.',
      },
      {
        title: 'Review first',
        detail:
          'The digest opens the profile: liabilities that fired, classifications sitting on a threshold, rule-set violations, then the properties this product will not estimate — with a count, each row anchoring to its evidence below.',
      },
      {
        title: 'Then the detail, worst-first',
        detail:
          'ADMET and toxicity cards are ordered by concern, so hERG or CYP trouble is above the fold and a clean property is where you have to scroll. Each card says whether it came from a rule, a substructure match or a QSAR classification.',
      },
    ],
    outputs: [
      {
        label: 'A profile saved as produced',
        detail:
          'Saving keeps the result with its caveats and its ungrounded properties intact, so reopening it later does not quietly re-run anything.',
      },
      {
        label: 'A prior-art search on the same structure',
        detail:
          'Keyword patent search sits beside the profile, so a liability and whether the chemistry is already claimed are one screen apart.',
      },
      {
        label: 'An honest unavailable list',
        detail:
          'Binding affinity without a target, plasma protein binding and per-isoform CYP inhibition are reported as unavailable rather than invented.',
      },
    ],
    limits: [
      'Every ADMET, liability and toxicity value is a computational prediction, not a measurement — confirm experimentally before it moves a series.',
      'A rule-set violation is what a published threshold says about the structure, not a safety determination.',
      'A property we cannot ground is shown as unavailable; that is a gap in the method, not a clean result.',
    ],
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
    clip: {
      src: protocolClip,
      moment: 'A one-line goal becomes materials, numbered steps and the controls to run.',
      label:
        'Screen recording: a Western blot goal is drafted into materials and numbered steps, with its controls and master-mix arithmetic beside it.',
    },
    steps: [
      {
        title: 'Describe the experiment',
        detail:
          'A goal and a sample type are enough: "Western blot for phospho-ERK1/2 in treated HEK293 lysate". The draft comes back as structure — materials with amounts, numbered steps with times and temperatures — rather than as a wall of prose to reformat.',
      },
      {
        title: 'Read the controls it argues for',
        detail:
          'Controls are drafted with the method and each one says what it rules out, so the review question becomes "is this the right control" rather than "did it remember a control".',
      },
      {
        title: 'Check the arithmetic in the open',
        detail:
          'The master-mix calculator shows per-reaction volume, reaction count, excess factor and the resulting totals, so you can verify the multiplication instead of trusting it.',
      },
      {
        title: 'Save a version, then another',
        detail:
          'Each saved draft is kept exactly as produced. Changing the goal and redrafting adds a version rather than overwriting the one your bench notes already refer to.',
      },
    ],
    outputs: [
      {
        label: 'A notebook bundle any ELN can take',
        detail:
          'A manifest, the protocol as Markdown and its materials as CSV — importable into Benchling, LabArchives or a shared drive without this product in the loop.',
      },
      {
        label: 'A master-mix table',
        detail: 'Per-reaction and total volumes with the excess factor stated, ready to print.',
      },
      {
        label: 'Version history',
        detail: 'Every draft that was saved, with its goal and its timestamp, in the workspace.',
      },
    ],
    limits: [
      'A draft is a starting point for a trained scientist, not a validated procedure — you own the review before anyone runs it.',
      'Concentrations and incubation times follow common practice for the method and still have to be fitted to your reagents and instruments.',
      'The export is vendor-neutral by design: there is no live ELN account connection, so nothing is written into your notebook behind your back.',
    ],
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
    clip: {
      src: regulatoryClip,
      moment: 'A 28-day tox record is drafted, then every number in the prose is audited back.',
      label:
        'Screen recording: a preclinical study record is entered, drafted into a narrative, and each number in that narrative is matched against the record.',
    },
    steps: [
      {
        title: 'Enter the study record',
        detail:
          'Study identifier, test article, species and strain, route, duration, the doses you ran and what was found. The record is the authority for everything downstream; nothing is inferred from the literature.',
      },
      {
        title: 'Draft the narrative',
        detail:
          'The draft reads as a tox narrative — design, exposure, findings, NOAEL where the record supports one — in the register a reviewer expects rather than as a summary of your table.',
      },
      {
        title: 'Audit the numbers, without a model',
        detail:
          'Every number in the prose is compared by exact decimal match against the record. Doses are not rounded or unit-converted, and a figure the record does not contain is reported as unmatched instead of surviving into a submission.',
      },
      {
        title: 'See what the record does not cover',
        detail:
          'Unsupported claims and missing endpoints are listed as stated gaps — "no-observed-adverse-effect level: not established" stays visible rather than being written around.',
      },
    ],
    outputs: [
      {
        label: 'A preclinical narrative',
        detail: 'Draft prose for the study you entered, with its numeric audit attached.',
      },
      {
        label: 'An IND module section',
        detail:
          'A section drafted into the structure the module expects, from the same record and the same checks.',
      },
      {
        label: 'A guideline map',
        detail:
          'Which requirement each statement answers, and which requirements nothing in the record answers yet.',
      },
    ],
    limits: [
      'This is drafting support, not regulatory advice, and nothing here has been reviewed by an agency.',
      'The audit proves a number matches your record; whether the record is right is a question for your study director.',
      'Guideline coverage is a checklist of the requirements the product knows, not a claim that a submission is complete.',
    ],
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
    clip: {
      src: grantsClip,
      moment: 'A topic search returns live opportunities with their agencies and closing dates.',
      label:
        'Screen recording: a keyword and agency search returns live grants.gov and SBIR opportunities with deadlines, eligibility and budget beneath.',
    },
    steps: [
      {
        title: 'Search the agencies, not a copy of them',
        detail:
          'Keyword, agency, program and focus query the grants.gov and SBIR.gov feeds directly, with closing dates as published. If a feed is down the page says which one, rather than returning a shorter list that looks complete.',
      },
      {
        title: 'Check eligibility against rules you can see',
        detail:
          'Small-business ownership, employee count, PI primary-employment and prior-award rules are evaluated as a checklist with the thresholds on screen and editable — because your situation, not the code, decides which ones bind.',
      },
      {
        title: 'Shape the budget',
        detail:
          'R&D costs become an SF-424 (R&R) budget: personnel, fringe, equipment, subawards and indirect costs, with the federal rates you set rather than ones baked in.',
      },
      {
        title: 'Hear the objections early',
        detail:
          'A mock review board critiques significance, innovation and approach and names the weaknesses a study section would raise, so the first hostile read of your aims is not the real one.',
      },
    ],
    outputs: [
      {
        label: 'A shortlist with deadlines',
        detail: 'Opportunities, their agency, their program and when they close.',
      },
      {
        label: 'An SF-424 (R&R) budget',
        detail: 'Line items with your rates, totalled, ready to transcribe into the form.',
      },
      {
        label: 'A written critique',
        detail: 'Scored strengths and weaknesses per criterion, with what would answer each one.',
      },
    ],
    limits: [
      'The mock review board is a rehearsal, not a study section, and its scores predict nothing about an award.',
      'Eligibility output is a checklist against rules as entered — confirm against the solicitation and your authorised organisational representative.',
      'Opportunity data is whatever the agency feeds publish at the moment you search.',
    ],
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
    clip: {
      src: assistantClip,
      moment: 'A research question runs its tools; an off-topic one is refused before any of them.',
      label:
        'Screen recording: the assistant answers a research question with its tool trace visible, then refuses an off-topic request before calling a model.',
    },
    steps: [
      {
        title: 'The question is judged before it is answered',
        detail:
          'A deterministic gate reads what the message asks for — not whether it contains a research word — and off-topic or dangerous requests are refused before any model call, at no cost. Repeated attempts cool down rather than fail open.',
      },
      {
        title: 'It works through typed tools only',
        detail:
          'Sixteen read-only tools over PubMed, PMC, PubChem, ClinicalTrials.gov, patents and your own saved work. There is no free-form fetch and no write path, so the worst case is a search you did not want.',
      },
      {
        title: 'You watch it work',
        detail:
          'Live status says what it is doing — searching PubMed, reading a stored paper — and every tool call stays on screen with its result and a link to the source, so an answer can be traced back rather than believed.',
      },
      {
        title: 'Keep typing while it answers',
        detail:
          'A follow-up typed mid-answer is queued with its own @-references and runs when the turn finishes. A PDF you attach is uploaded, encrypted and referenced by id — its bytes are never handed to the model provider.',
      },
    ],
    outputs: [
      {
        label: 'An answer with its trace',
        detail: 'The tool calls that produced it, their results and the sources they came from.',
      },
      {
        label: 'A thread that persists',
        detail: 'Threads belong to your account, reopen after a reload and can be deleted outright.',
      },
      {
        label: 'A refusal on the record',
        detail:
          'Refusals are written to the audit trail with their reason, so scope is auditable rather than anecdotal.',
      },
    ],
    limits: [
      'The assistant is deliberately narrow: anything outside biomedical R&D is refused, including questions it could answer.',
      'Answers are assembled from tool results by a language model and still need the same scepticism as any draft.',
      'A per-account rate limit and a daily call and cost budget cap what one user can spend.',
    ],
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
    clip: {
      src: workspaceClip,
      moment: 'Saved work, members and their roles in the one place that scopes them.',
      label:
        'Screen recording: the workspace view showing saved work, its data sources, members with their roles and the invitation controls.',
    },
    steps: [
      {
        title: 'Work is saved to a workspace, not a laptop',
        detail:
          'Literature tables, screens, protocol drafts and regulatory records belong to a workspace, so the person who joins next month opens the same evidence rather than asking for a forwarded export.',
      },
      {
        title: 'Invite by role',
        detail:
          'Owner, admin, member and viewer. A viewer reads; a member contributes; an admin manages people. Roles are checked on the server for every request, so a hidden button is not the control.',
      },
      {
        title: 'Invitations are single-use and seated',
        detail:
          'An invitation is one token, one acceptance, with an expiry and a seat limit per workspace — and it is mailed when SES is configured or copied as a link when it is not.',
      },
      {
        title: 'Private stays private',
        detail:
          'Your own saved work is not visible to the workspace unless it was created there, and a non-member gets the same answer for a workspace that exists as for one that does not.',
      },
    ],
    outputs: [
      {
        label: 'One place the team reads from',
        detail: 'Saved tables, drafts and sources, scoped to the workspace that owns them.',
      },
      {
        label: 'A membership list that means something',
        detail: 'Who is in, at what role, with removal and leave both available and audited.',
      },
      {
        label: 'Shared documents',
        detail: 'A paper uploaded inside a workspace is readable by its members, still encrypted at rest.',
      },
    ],
    limits: [
      'Roles govern access inside the product; they are not a substitute for your own data-governance policy.',
      'Invitation mail needs an SES sender configured — without one, you copy the link yourself.',
      'Removing a member ends their access to the workspace; exports they already downloaded are outside the product.',
    ],
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
    clip: {
      src: auditClip,
      moment: 'The trail of a real session, filtered down to the model calls it made.',
      label:
        'Screen recording: the audit trail filtered by event type, showing document, model-call and tool events from a real session.',
    },
    steps: [
      {
        title: 'Events are written as they happen',
        detail:
          'Documents stored, read and deleted; model calls with their token counts and cost; tools invoked; exports produced; invitations sent; requests refused; failures. The trail is append-only, so it records the session rather than summarising it afterwards.',
      },
      {
        title: 'Filter to the question you have',
        detail:
          'Filter by event type to answer a specific question — what left for the model, who read that paper, what was refused — instead of reading a timeline end to end.',
      },
      {
        title: 'Names are fingerprinted, not copied',
        detail:
          'A document\u2019s filename is recorded as a fingerprint, so the trail can prove the same file was involved twice without carrying a possibly sensitive name in a log.',
      },
      {
        title: 'The unflattering entries stay',
        detail:
          'Refusals, rate-limit hits and errors are recorded beside the successes. A trail that only holds good news cannot answer anything.',
      },
    ],
    outputs: [
      {
        label: 'An answer to "what was sent?"',
        detail: 'Model calls with the tool that triggered them, their tokens and their cost.',
      },
      {
        label: 'A document history',
        detail: 'When a paper was stored, read, shared and deleted, by fingerprint.',
      },
      {
        label: 'Evidence of the guardrails',
        detail: 'Refusals with their reason, so scope enforcement is checkable after the fact.',
      },
    ],
    limits: [
      'The trail covers actions inside this product, not what happens to a file after you export it.',
      'Entries are written for your account and workspace; it is not an organisation-wide SIEM feed.',
      'Fingerprinted names are deliberately not reversible — the trail proves identity, not readability.',
    ],
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
    clip: {
      src: settingsClip,
      moment: 'Session, model, spend, encryption and retention — as the server reports them.',
      label:
        'Screen recording: the settings view reading session, model-routing, budget, encryption and retention values from the running deployment.',
    },
    steps: [
      {
        title: 'Read the configuration, not a promise',
        detail:
          'Access and refresh lifetimes, which model is routed to, the daily call and cost budget, how documents are encrypted and how long they are kept are all reported by the server that is serving you.',
      },
      {
        title: 'The model key is never yours to hold',
        detail:
          'The Anthropic key lives server-side in a secrets manager. No user buys one, pastes one or can read one from the browser, so there is no key in a settings field to leak.',
      },
      {
        title: 'Documents are sealed per document',
        detail:
          'Stored papers are encrypted with a data key minted per document by KMS, with the ciphertext in S3 when a bucket is configured — and this page says which of those is actually true here.',
      },
      {
        title: 'End the sessions you cannot see',
        detail:
          'Refresh sessions are server-side records, so signing out everywhere actually revokes them rather than clearing one browser.',
      },
    ],
    outputs: [
      {
        label: 'A spend ceiling',
        detail: 'A daily call and cost budget per account, with the current configuration shown.',
      },
      {
        label: 'A data-handling statement you can check',
        detail: 'Encryption, storage location and retention as configured, not as aspiration.',
      },
      {
        label: 'Session control',
        detail: 'Sign out everywhere, and restart the guided tour, from the account itself.',
      },
    ],
    limits: [
      'Rate limits are enforced per server process today: scaling to several replicas needs a shared store or a WAF rule to be strict.',
      'Protected-health-information use would require a business associate agreement with Anthropic; the product does not assume one.',
      'No third-party penetration test has been performed, and the page does not pretend otherwise.',
    ],
  },
];
