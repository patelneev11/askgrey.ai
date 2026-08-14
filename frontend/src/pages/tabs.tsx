import { TabPlaceholder } from './TabPlaceholder';

export function LiteraturePage() {
  return (
    <TabPlaceholder
      title="Literature"
      paneKey="literature"
      rightTitle="Source reader"
      summary="Federated search across PubMed, PubChem and ClinicalTrials.gov, with agent-built review tables whose cells link back to the exact source passage."
    />
  );
}

export function ScreeningPage() {
  return (
    <TabPlaceholder
      title="Screening"
      paneKey="screening"
      rightTitle="Compound profile"
      summary="Structure-activity and ADMET profiling for lead compounds, with toxicity flags and patent landscape checks."
    />
  );
}

export function ProtocolPage() {
  return (
    <TabPlaceholder
      title="Protocol Creation"
      paneKey="protocol"
      rightTitle="Protocol draft"
      summary="Context-aware laboratory protocol drafting with in-line reagent calculations, control validation and ELN export."
    />
  );
}

export function RegulatoryPage() {
  return (
    <TabPlaceholder
      title="Regulatory"
      paneKey="regulatory"
      rightTitle="Submission draft"
      summary="IND module drafting from raw study data, with discrepancy auditing and FDA / EMA / PMDA guideline alignment."
    />
  );
}

export function GrantsPage() {
  return (
    <TabPlaceholder
      title="Grants"
      paneKey="grants"
      rightTitle="Proposal draft"
      summary="SBIR / STTR opportunity matching, budget structuring and a multi-agent mock review board that scores drafts before submission."
    />
  );
}

export function WorkspacePage() {
  return (
    <TabPlaceholder
      title="Workspace Profile"
      paneKey="workspace"
      rightTitle="Members"
      summary="Workspace identity, seat management and the collaborative vault synced with corporate ELN and document systems."
    />
  );
}

export function AuditPage() {
  return (
    <TabPlaceholder
      title="Audit Trails"
      paneKey="audit"
      rightTitle="Event log"
      summary="End-to-end audit tracking of every agent run, document access and export across research teams."
    />
  );
}

export function SettingsPage() {
  return (
    <TabPlaceholder
      title="Settings"
      paneKey="settings"
      rightTitle="Configuration"
      summary="Workspace configuration: SSO provider, data residency, model routing and integration credentials."
    />
  );
}
