import { Link } from 'react-router-dom';

import { productUrl } from '@/lib/hosts';

import styles from './marketing.module.css';

/**
 * How the product handles data, written for the person at a biotech who has to sign off on it.
 *
 * Everything here describes behaviour that exists in the product today, and the gaps are named
 * as gaps — an unverifiable security claim on a public page is worse than no page.
 */
export function SecurityPage() {
  return (
    <article className={styles.prose}>
      <h1 className={styles.sectionTitle}>Security and data handling</h1>
      <p className={styles.sectionLead}>
        What happens to your documents and your questions, and which assurances we are not in a
        position to give yet.
      </p>

      <h2>Documents</h2>
      <ul>
        <li>
          Uploaded papers are encrypted per document with a data key minted by AWS KMS, and the
          ciphertext is stored in an S3 bucket in the deployment&apos;s own account.
        </li>
        <li>
          Each account has a retention window; stored papers are deleted when it elapses, and can be
          deleted on request at any time.
        </li>
        <li>
          The audit trail records a fingerprint of a document&apos;s name rather than the name
          itself, so the log does not leak what you are reading.
        </li>
      </ul>

      <h2>What the model provider receives</h2>
      <ul>
        <li>
          Text needed to answer the question. Raw upload bytes and filesystem paths are never sent:
          attachments are referenced by id and read server-side.
        </li>
        <li>
          The assistant&apos;s tools are read-only. It can query sources and read your saved work; it
          cannot write, delete or send anything.
        </li>
        <li>
          Requests are classified before a model is called. Off-topic, dangerous and
          prompt-extraction attempts are refused at no cost, with the rule recorded in the audit
          trail.
        </li>
      </ul>

      <h2>Accounts and access</h2>
      <ul>
        <li>
          Sessions use short-lived access tokens with a rotating refresh session in an HttpOnly,
          Secure cookie; sign-in attempts are rate limited.
        </li>
        <li>
          Shared work lives in workspaces with owner, admin, member and viewer roles, seat limits,
          and single-use invitations.
        </li>
        <li>
          Per-account rate limits and a daily model call and spend budget bound what one user can
          consume.
        </li>
      </ul>

      <h2>What we do not claim</h2>
      <ul>
        <li>
          <strong>No third-party penetration test.</strong> The security work above is implemented
          and reviewed internally; it has not been audited by an outside firm.
        </li>
        <li>
          <strong>No PHI.</strong> Do not upload patient data. That needs a business associate
          agreement with our model provider, which we do not have.
        </li>
        <li>
          <strong>No SOC 2 or ISO 27001 report.</strong> We have not been through either audit.
        </li>
        <li>
          <strong>No live ELN connection.</strong> Protocols leave as a notebook bundle you import
          yourself.
        </li>
      </ul>

      <p>
        The full legal position, including the scientific limits of extracted values and
        predictions, is in the <Link to="/terms">terms of agreement</Link>.
      </p>

      <p>
        <a className={[styles.cta, styles.ctaPrimary].join(' ')} href={productUrl('/login')}>
          Open the workspace
        </a>
      </p>
    </article>
  );
}
