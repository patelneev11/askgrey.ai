import { Meter } from '@/components/Meter';
import { PageCanvas } from '@/components/PageCanvas';
import { StatusPill } from '@/components/StatusPill';

import styles from './WorkspacePage.module.css';

const MEMBERS = [
  {
    name: 'Neev Patel',
    email: 'patel.neev11@gmail.com',
    role: 'Owner',
    active: 'now',
  },
  {
    name: 'Dana Okoye',
    email: 'd.okoye@askgrey.ai',
    role: 'Scientist',
    active: '2 hours ago',
  },
  {
    name: 'Marc Rehnquist',
    email: 'm.rehnquist@askgrey.ai',
    role: 'Regulatory',
    active: 'yesterday',
  },
  {
    name: 'Priya Raman',
    email: 'p.raman@askgrey.ai',
    role: 'Reviewer',
    active: '4 days ago',
  },
];

const INTEGRATIONS = [
  {
    name: 'Benchling ELN',
    detail: 'Protocol export, entity sync',
    state: 'connected' as const,
  },
  {
    name: 'SharePoint',
    detail: 'Submission document vault',
    state: 'connected' as const,
  },
  {
    name: 'IDBS E-WorkBook',
    detail: 'Not configured',
    state: 'pending' as const,
  },
];

export function WorkspacePage() {
  return (
    <PageCanvas
      title="Grey Therapeutics"
      description="Workspace identity, seats and the connected systems your agents can read from and write to."
      actions={<StatusPill tone="validated">SOC 2 controls active</StatusPill>}
    >
      <section className={styles.identity}>
        <span className={styles.monogram} aria-hidden="true">
          GT
        </span>
        <dl className={styles.facts}>
          <div>
            <dt>Plan</dt>
            <dd>Research — annual</dd>
          </div>
          <div>
            <dt>Data residency</dt>
            <dd>US-East</dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>Feb 2, 2026</dd>
          </div>
        </dl>
        <div className={styles.seats}>
          <Meter label="Seats used" value="4 of 10" fraction={0.4} tone="pipeline" />
        </div>
      </section>

      <section>
        <h2 className={styles.sectionTitle}>Members</h2>
        <table className={styles.members}>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Role</th>
              <th scope="col">Last active</th>
            </tr>
          </thead>
          <tbody>
            {MEMBERS.map((member) => (
              <tr key={member.email}>
                <th scope="row">
                  <span className={styles.memberName}>{member.name}</span>
                  <span className={styles.memberEmail}>{member.email}</span>
                </th>
                <td>
                  <span className={styles.role}>{member.role}</span>
                </td>
                <td className={styles.muted}>{member.active}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className={styles.sectionTitle}>Connected systems</h2>
        <ul className={styles.integrations}>
          {INTEGRATIONS.map((integration) => (
            <li key={integration.name} className={styles.integration}>
              <div>
                <span className={styles.integrationName}>{integration.name}</span>
                <span className={styles.integrationDetail}>{integration.detail}</span>
              </div>
              <StatusPill tone={integration.state === 'connected' ? 'validated' : 'idle'}>
                {integration.state === 'connected' ? 'Connected' : 'Not connected'}
              </StatusPill>
            </li>
          ))}
        </ul>
      </section>
    </PageCanvas>
  );
}
