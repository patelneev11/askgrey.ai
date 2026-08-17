# Regulatory reference sources

Every structural assumption made by `backend/app/services/regulatory/**` traces to a document
listed here. Nothing in that package is allowed to encode a section number, heading, or
jurisdiction requirement that is not written down in this file with a URL, because regulatory
structure changes and a value that came out of a model's memory cannot be audited later.

All sources below were **fetched and read directly** while writing this document. Where only the
landing page was reachable rather than the underlying PDF, that is stated on the entry.

**Retrieved: 2026-08-16** (UTC). See [Update process](#update-process-known-limitation) — this
file and `guidelines/reference/*.json` go stale on their own and nothing in the product currently
notices when they do.

## CTD structure (common to FDA / EMA / PMDA)

| What | Source | Version / date on the document |
| --- | --- | --- |
| Overall CTD organisation, five modules | ICH M4(R4), <https://database.ich.org/sites/default/files/M4_R4__Guideline.pdf> | Step 4, 15 June 2016 |
| **Module 3 (Quality)** section tree — `3.2.S`, `3.2.P`, `3.2.A`, `3.2.R`, `3.3` | ICH M4Q(R1), <https://database.ich.org/sites/default/files/M4Q_R1_Guideline.pdf> | Step 4, 12 September 2002 |
| **Module 4 (Nonclinical)** section tree — `4.2.1`–`4.2.3`, `4.3` | ICH M4S(R2), <https://database.ich.org/sites/default/files/M4S_R2_Guideline.pdf> | Step 4, 20 December 2002 |
| Module 2.6 nonclinical written-summary headings (`2.6.2`–`2.6.7`) | ICH M4S(R2), same document | as above |
| Heading granularity / what is one document in an eCTD | Granularity Document Annex to M4, FDA reprint, <https://www.govinfo.gov/content/pkg/GOVPUB-HE20_4000-PURL-LPS113972/pdf/GOVPUB-HE20_4000-PURL-LPS113972.pdf> | October 2005 |

The Module 3 and Module 4 headings encoded in
`backend/app/services/regulatory/ind/reference/ctd_structure.json` were transcribed from the
tables of contents of M4Q(R1) and section 4.2 of M4S(R2) respectively, not from memory.

Note that ICH M4Q/M4S describe a **marketing application**. An IND is an earlier, deliberately
thinner submission: FDA's own content requirement is 21 CFR 312.23, and the CTD tree is the
*organising format* an IND is placed into, not a checklist of things an IND must contain. The
compiler therefore drafts CTD-shaped sections but never treats a missing section as an error.

## United States — FDA

| What | Source | Version / date |
| --- | --- | --- |
| IND content and format, including `(a)(7)` CMC and `(a)(8)` pharmacology/toxicology | 21 CFR 312.23, <https://www.ecfr.gov/current/title-21/section-312.23> | eCFR current as of 2026-04-09; no substantive change since 2017-01-03 |
| eCTD is the required submission format for commercial INDs; eCTD v4.0 accepted for new INDs from 16 September 2024 | <https://www.fda.gov/drugs/electronic-regulatory-submission-and-review/electronic-common-technical-document-ectd> | read 2026-08-16 |

Relevant text of 21 CFR 312.23(a)(8): an *integrated summary* of the toxicological effects of the
drug in animals and in vitro is required, together with the identification and qualifications of
the individuals who evaluated the results and concluded it is reasonably safe to begin the
proposed investigations, and a statement of where the studies were conducted and where the
records are available for inspection. Those last two are people-and-place facts that no model can
supply, which is why the drafters emit them as gaps rather than prose.

## European Union — EMA / EU Clinical Trials Regulation

| What | Source | Version / date |
| --- | --- | --- |
| IMPD contents; quality data in Module 3 form (¶40), non-clinical pharmacology and toxicology data in Module 4 form (¶41–43), GLP statement (¶44), test-material representativeness (¶45) | Regulation (EU) No 536/2014, Annex I, <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32014R0536> | OJ L 158, 27.5.2014 |
| Chemical/pharmaceutical quality documentation expected in an IMPD | EMA/CHMP/QWP/545525/2017 Rev. 2, <https://www.ema.europa.eu/en/requirements-chemical-pharmaceutical-quality-documentation-concerning-investigational-medicinal-products-clinical-trials-scientific-guideline> | Rev. 2, legal effective date 31 January 2022 (confirmed the current effective version on 2026-08-16) |

EU-specific asks that FDA does not state in the same terms, and which the guideline checker looks
for: an explicit **critical analysis** including justification for omitted data (Annex I ¶43) — a
factual summary is explicitly not sufficient — a **GLP status statement** (¶44), and confirmation
that the **test material's impurity profile is representative** of clinical material (¶45).

## Japan — PMDA

| What | Source | Version / date |
| --- | --- | --- |
| Nonclinical safety points to consider for an initial clinical trial notification (CTN) | <https://www.pmda.go.jp/files/000274660.pdf> | 25 March 2025, Center for Product Evaluation |
| eCTD v4.0 implementation in Japan | <https://www.pmda.go.jp/files/000274433.pdf> | Implementation Guide in Japan v1.6.0 |
| CTD ("notification 899") and electronic study data requirements, English index | <https://www.pmda.go.jp/english/review-services/reviews/0002.html> | read 2026-08-16 |

PMDA-specific asks encoded in the reference data, all from the 25 March 2025 document: safety
concerns predicted from nonclinical studies — including the **NOAEL-to-clinical-dose margin** —
must be communicated to participants; an initial **phototoxicity** assessment per ICH S10 must be
discussed and is "often missing"; **contraception** requirements must be specified where
embryo-fetal toxicity is seen or reproductive toxicity studies are not yet done; and the position
on **lactating women** must be stated.

## Update process (known limitation)

This is a dated snapshot, not a feed. Nothing in this repo watches these URLs, so:

- The reference data can silently describe last year's expectations. Every report the guideline
  checker returns therefore carries the reference version and its `retrieved` date, and the UI
  shows that date, so a reviewer can see how old the comparison is.
- ICH M4Q/M4S have been stable for two decades; the FDA/EMA/PMDA documents above are not, and the
  PMDA points-to-consider document in particular is revised roughly annually.
- Re-verifying means re-reading the primary documents above and bumping `version` and `retrieved`
  in `backend/app/services/regulatory/guidelines/reference/*.json`. The tests fixture their own
  dataset, so refreshing the shipped data does not break them.

Treat everything downstream of this file as a drafting aid for a qualified regulatory affairs
professional, never as a determination of what a submission requires.
