import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '@/lib/api';

import styles from './TermsPage.module.css';

/**
 * The terms of agreement, and the single place the product's scientific limits are stated in
 * full.
 *
 * Those limits used to be repeated as a warning band on top of every tab. Saying them once, here,
 * where acceptance is recorded against the account, is what makes them mean something — the tabs
 * keep one quiet line of text beside the output it actually qualifies.
 *
 * Reachable without a session: it has to be readable before you agree to it.
 */
export function TermsPage() {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    api
      .terms()
      .then((info) => setVersion(info.version))
      .catch(() => setVersion(null));
  }, []);

  return (
    <div className={styles.screen}>
      <article className={styles.sheet}>
        <header className={styles.header}>
          <h1 className={styles.heading}>Terms of Agreement</h1>
          {version && <p className={styles.version}>Version {version}</p>}
        </header>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>1. What askgrey is</h2>
          <p>
            askgrey is research software for biomedical R&amp;D. It searches public sources, reads
            documents you give it, drafts text and computes predictions, so that a qualified
            researcher can work faster. It is a drafting and retrieval tool, and every output is a
            starting point for your own judgement.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>
            2. Not a medical device, and not for clinical use
          </h2>
          <p>
            askgrey is not a medical device and is not cleared, approved or certified by any
            regulator. Nothing it produces may be used to diagnose, treat, prevent or mitigate
            disease in any person, or to make a clinical decision about a patient.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>3. Extracted values are unvalidated</h2>
          <p>
            Values shown in extraction tables are extracted by a language model reading the paper
            you uploaded. They are unvalidated: open the cited passage and confirm it against the
            source before relying on a number. A value with no citation has not been checked against
            any passage at all.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>4. Predictions are not measurements</h2>
          <p>
            ADMET, liability and toxicity values are computational predictions — approximations from
            published physicochemical rules, structural heuristics and models — not validated assay
            results. Rule flags are matches to motifs reported in the literature: their presence is
            not evidence that a compound has a liability, and their absence is not evidence of
            safety. Expert review and experimental confirmation are required before any compound or
            series decision.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>
            5. Drafts are not regulatory, legal or financial advice
          </h2>
          <p>
            Protocol, regulatory and grant text is agent-drafted and requires review by a qualified
            researcher, your regulatory affairs function, and — for eligibility, patents or freedom
            to operate — a qualified attorney. Eligibility checks are informational and are not a
            legal determination. Patent results are keyword matches in public patent text: not a
            structural similarity search, not a novelty assessment and not freedom to operate.
            Budget figures are planning estimates computed from federal rules that are revised
            annually and vary by agency — the salary cap, indirect base and fee ceiling — so check
            them against the solicitation and with your finance office before you submit, and treat
            eligibility verdicts as the encoded SBA baselines rather than an agency&apos;s own
            supplements.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>6. Scores, rankings and assistant answers</h2>
          <p>
            Mock review scores and critiques are written by a language model role-playing reviewer
            personas. They are not calibrated against real NIH or SBIR reviewer scores and carry no
            predictive value for a funding decision. Opportunity match percentages are a ranking of
            keyword and semantic overlap with what you typed, not a probability of award. Assistant
            answers are model output, including where the assistant has called a tool: check the
            cited record before you act on one. The assistant reads and drafts only — it cannot
            save, edit or delete your work, and it cannot file anything in an external lab notebook.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>7. What you may send us</h2>
          <p>
            You may not upload protected health information, personal data about identifiable
            patients or subjects, or anything you are not permitted to disclose. Content you submit
            for drafting, extraction or assistant answers is processed by a third-party model
            provider, so treat it as leaving your systems. You are responsible for holding whatever
            rights you need in the documents you upload.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>8. Your account</h2>
          <p>
            Keep your credentials to yourself, and use a password only you know. Work saved inside a
            shared workspace is readable by that workspace&apos;s members; that is the point of it,
            so add only people who should see it. Security-relevant actions on your account are
            recorded in an audit trail.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>9. Availability and third-party sources</h2>
          <p>
            askgrey depends on public sources — PubMed, PubChem, ClinicalTrials.gov, USPTO,
            grants.gov, SBIR — and on a model provider. Those services change, rate-limit and go
            down, and results depend on what they publish. The software is provided as-is, without
            warranty of accuracy, completeness or fitness for a particular purpose, and our
            liability is limited to the fullest extent the law allows.
          </p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionHeading}>10. Changes to these terms</h2>
          <p>
            These terms carry a version. Registration records which version you accepted and when.
            If the terms change materially, the new version is published here.
          </p>
        </section>

        <Link className={styles.back} to="/login">
          Back to sign in
        </Link>
      </article>
    </div>
  );
}
