# What leaves the deployment, and to whom

Written for #20 (M4 in the security review). It states what is actually true today; where a
control does not exist yet it says so rather than describing an intention.

## The one outbound processor

Anthropic is the only vendor that receives customer content. Everything else the app calls —
NCBI Entrez, PubChem, ClinicalTrials.gov, grants.gov, SBIR.gov — receives only a query string
the user typed, never document text.

| Path | What is sent to Anthropic |
| --- | --- |
| `POST /api/pdf-extraction/upload` | Text extracted from the uploaded PDF, truncated to `pdf_extraction_context_chars` (40 000), plus the extraction goal |
| `POST /api/pdf-extraction/url` | The same, for the fetched document |
| `GET /api/pubmed/search` | The natural-language query only |
| `POST /api/grants/match` | The research-focus description and the public grant synopses |

PDFs are parsed locally with pdfplumber; the file bytes themselves never leave the process.
Only the extracted text does — which for a proprietary manuscript is the same disclosure in
practice, hence the notice on the Literature tab above the upload control.

## Retention

Anthropic's commercial terms state that API inputs and outputs are not used to train models,
and that inputs are retained for up to 30 days for trust-and-safety purposes (longer only
where legally required). Zero-retention processing is available but must be requested from
Anthropic for the account — **it has not been requested for this deployment**, so the 30-day
window applies today. Anyone signing a customer DPA that promises otherwise needs to arrange
zero-retention first.

## Controls that exist

- **Disclosure at the point of upload** — Literature tab, next to the file picker.
- **Audit record per outbound document** — `document.sent_to_llm` on the `askgrey.audit`
  logger, carrying actor, client address, source name, byte count, vendor and model. The text,
  the goal and the extracted values are deliberately not logged.
- **No-LLM degradation** — with `ANTHROPIC_API_KEY` unset, PubMed search falls back to the
  rule-based translator and nothing is sent anywhere. PDF extraction and grant matching have
  no non-LLM equivalent and return 503 instead of silently doing something weaker.
- **Spend ceiling** — per-account rate limit and daily call budget in `app/core/ratelimit.py`.

## Controls that do not exist yet

- No per-workspace opt-out toggle; the choice is deployment-wide via the API key.
- No redaction pass before text is sent.
- Audit records go to the application log, not to a queryable store — the Audit Trails tab
  still renders sample data (#23 covers wiring it to real events).
