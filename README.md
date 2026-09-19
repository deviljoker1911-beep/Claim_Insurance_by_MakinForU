# ClaimAI — AI-Powered Claim Pre-Submission Validation

**Find missing documents. Detect inconsistencies. Validate before submission.**

ClaimAI is a working prototype for hospital claims desks. It checks a health-insurance claim file *before* it goes to the insurer or TPA:

1. Reads the uploaded hospital documents.
2. Builds a structured claim from them.
3. Cross-checks the documents against each other.
4. Applies a document checklist for the procedure performed.
5. Asks the operator targeted questions about gaps.
6. Produces a readiness report where every finding points back to its evidence.

> **Prototype / pilot, not a production insurance platform.**
> Uses **synthetic demo data only**; no real patient records.
> AI-generated validation assistance. Final claim submission requires authorised human review.

## Workflow

```
Document upload → OCR → Bundle segmentation → Classification → Extraction
→ Claim structuring → Cross-document validation → Procedure detection
→ Procedure checklist → Missing-document detection → AI questions
→ Operator upload / confirmation → Re-analysis
→ Claim documentation readiness report → Human final review
```

## Build status

| Phase | Scope | Status |
|------:|-------|--------|
| 1 | Application running: API health, app shell, tooling | ✅ Done |
| 2 | Claim creation, multi-document upload, deterministic demo data | ✅ Done |
| 3 | Document intelligence: OCR, classification, extraction, evidence | ✅ Done |
| 4 | Canonical claim model and evidence viewer | ✅ Done |
| 5 | Cross-document validation and findings | ✅ Done |
| 6 | Procedure detection and procedure checklist engine | ✅ Done |
| 7 | Interactive questions, grounded assistant and incremental re-analysis | ✅ Done |
| 8 | Readiness, dashboard and human approval | ✅ Done |
| 9 | Final report (HTML / PDF / Excel) and audit trail | ✅ Done |
| 10 | Hardening: concurrency, recovery, determinism, report integrity | ✅ Done |
| 11 | Claim bundles: one uploaded file read as the documents it holds | ✅ Done |

## Tech stack

| Layer | Technology |
|-------|------------|
| Web app | React 19, TypeScript, Vite 8, Tailwind CSS 4, React Router 8, TanStack Query, lucide icons |
| API | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 |
| Database | PostgreSQL 16 (SQLite fallback for zero-setup runs) |
| Documents | PyMuPDF (text layer, page rendering), RapidOCR (PP-OCR models on ONNX Runtime, bundled and offline), OpenCV and NumPy (page quality); optional Docling and native PaddleOCR adapters behind the same interface |
| Demo data | ReportLab and Pillow, generated deterministically |
| AI *(from phase 7)* | Pluggable provider interface: offline deterministic demo engine (default), Anthropic Claude, OpenAI-compatible APIs |
| Storage | Local filesystem; original uploads are never modified |

## Quick start

**Prerequisites**
- Python 3.12 with [uv](https://docs.astral.sh/uv/)
- Node.js 20.19+ (22+ recommended)
- GNU make
- PostgreSQL 16, either a local server or Docker via `make db-docker`

```bash
git clone https://github.com/deviljoker1911-beep/Claim_Insurance_by_MakinForU.git
cd Claim_Insurance_by_MakinForU
make setup    # creates .env, installs backend + frontend dependencies, creates the database
make dev      # API on http://127.0.0.1:8010, web app on http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173**.

Analysis runs entirely on this machine: the OCR models ship inside the `rapidocr` package, and no API key is needed for any part of the demo.

`make setup` copies `.env.example` to `.env`, which points at the Docker database (`make db-docker`, port 5433). To use a local PostgreSQL server instead, edit `DATABASE_URL` in `.env`, for example:

```bash
DATABASE_URL=postgresql+psycopg://<your-user>@127.0.0.1:5432/claimai
```

To run without PostgreSQL, use `DATABASE_URL=sqlite:///./storage/claimai.db`.

## Commands

| Command | What it does |
|---------|--------------|
| `make setup` | First-time setup: `.env`, dependencies, database |
| `make dev` | Run API (`:8010`) and web app (`:5173`) together |
| `make backend` / `make frontend` | Run one side only |
| `make demo` | Build the web app and serve everything from the API on `http://127.0.0.1:8010` |
| `make test` | Backend tests, frontend lint and production build |
| `make reset` | Reset the demo workspace through the running API (next claim: `CLM-2026-00123`) |
| `make smoke` | End-to-end smoke test against the running API and its real database (resets the workspace) |
| `make demo-data` / `make demo-check` | Regenerate the synthetic documents / verify them byte for byte |
| `make db` | Create the database named in `DATABASE_URL` if missing |
| `make db-docker` | Start PostgreSQL 16 in Docker (port 5433) |
| `make clean` | Remove build output and caches |

## Demo walkthrough (so far)

1. `make reset`, or use **Settings → Reset demo workspace**.
2. **New Claim → Fill demo claim details → Create claim & continue.** The claim becomes `CLM-2026-00123`.
3. **Add demo document pack** attaches the 16 synthetic documents. You can also drag the files from [`demo_data/initial`](demo_data/initial) into the upload area or browse for them.
4. **Start Analysis.** The documents are processed one at a time; the timeline shows the stage each one is on (Rendering → OCR → Quality check → Classification → Extraction → Evidence).
5. Each row then shows what was read: the document type with its confidence, the quality signals, and whether any text in the file is covered by opaque paint.
6. **Claim overview** (`/claims/<id>`) shows the findings, the checks that produced them, and the canonical claim: patient, admission, diagnosis, procedure, doctors, bills and the document inventory. Every value carries a **Source** chip — open it to see the document, the page, the highlighted region it was read from, the extraction method and the confidence.
7. Work through the findings: **Mark reviewed**, **Acknowledge**, **Resolve**, **Reopen**, or **Exclude duplicate** for a document that was uploaded twice. Add the two later documents (`demo_data/later`) and run the analysis again: the missing-document findings close themselves and the checks that were waiting can run.

The synthetic claim and its deliberately seeded issues are described in [`demo_data/README.md`](demo_data/README.md).

### What analysis produces

| Step | What happens |
|------|--------------|
| Rendering | The PDF text layer is read (visible text only) and every page is rendered to a PNG for review. Originals are never modified. |
| OCR | Pages with no usable text layer go through RapidOCR, which runs locally from models bundled in the package — no API key, no network. Where the OCR extras are absent, the demo falls back to labelled `demo_fixture` text shipped with the synthetic documents. |
| Quality check | Effective resolution, edge sharpness, skew, blank and cropped-page checks, measured from the page itself — never from its filename. |
| Classification | 20 document types, decided from the document's own headings and vocabulary. A scan called `scan_0042.pdf` is recognised as an operative note from its content. |
| Extraction | Patient identity, admission and discharge dates, clinical details and billing tables (line items, quantities, rates, totals), with Indian digit grouping and day-first dates. |
| Evidence | Every value keeps its document, page, page-relative box, snippet, method and confidence. A value that cannot be located says so rather than pointing at a page. |

Text that a document hides behind opaque paint is detected, reported separately as a signal that needs human verification, and excluded from every extracted value.

### Claim bundles

A claim rarely arrives as one file per document. It arrives as one PDF per claim, holding the
cashless request, the case papers, the bills, the reports and the discharge summary one after
another. Read as a single document, a packet like that becomes whatever its first page looks
like — and every document actually inside it is then reported as missing.

So a file is read once and then divided into the documents it holds. Each page is classified on
its own by the engine that classifies documents, against the same
[`document_types.yaml`](backend/config/document_types.yaml); nothing new decides what a page is.
[`backend/config/segmentation.yaml`](backend/config/segmentation.yaml) says only where one document
ends and the next begins, and it is deliberately reluctant to say so:

| Signal | What it means |
|--------|---------------|
| "Page 2 of 5" on the page | The page is inside a document already open, whatever else it looks like |
| "Page 1 of 5" on the page | The document before it has ended |
| The page's heading names a type | A document is announcing itself, and a different type ends the one before it |
| The same bill or report number | A page repeating its document's heading *and* its number is that document's next page |
| A different bill or report number | Two documents of one type — two lab reports, not one of twice the length |
| Nothing above holds | The page continues the document it is inside |

A page that is unsure of itself never ends a document: an uncertain page is a worse reason to cut a
document in half than the continuity of the one it is inside. Pages that name nothing at all become
one document of no known type, which a reviewer can see rather than a confident wrong answer.

The pages keep the numbers they have in the uploaded file. A value read from page 7 of a bundle
says page 7 of that bundle, the page image behind it is that page, and the report keeps the file
and the documents found inside it apart:

```
Uploaded file:   ClaimBundle.pdf — 23 pages
Documents found: Admission record — page 2      Hospital bill — page 15
                 Discharge summary — pages 6-8  Operative note — pages 20-21   …
```

Nothing after this step knows that a bundle was involved. Validation, the checklist, the questions,
readiness and the report all see documents, as they always have — which is the point: the inventory
was wrong, not the engines reading it. The test that holds this is the one that matters most: the
same eighteen documents uploaded separately, and merged into a single file, leave the claim with
the same documented facts, findings, checklist, questions, readiness and review.

### The canonical claim

The extracted values are assembled into one structured claim: patient, admission, diagnosis,
procedures, doctors, investigations, documents, bills, findings, the procedure checklist, the
questions it raised, the answers recorded against them, the readiness of the documentation and
the human review.

Where several documents carry the same value they are compared in a normalised form (names
without honorifics, dates as calendar dates, identifiers without punctuation, amounts
numerically) and each document contributes a weight: the insurance card, the admission record
and the discharge summary count ×3, every other document ×1. A value read by OCR below 80%
confidence is listed as a source but does not take part in the selection.

Nothing is hidden by that choice. Every supporting document stays listed with its page and
region, and when documents carry materially different values the canonical claim reports
*multiple source values detected* with the competing values and their own sources — a
statement of provenance, not a verdict. Judging those differences is phase 5.

The snapshot is rebuilt from the stored documents whenever it is read, so it is a deterministic
function of the analysis: two builds of the same state produce the same document, hash included.

### Validation and findings

19 rules in [`backend/config/rules.yaml`](backend/config/rules.yaml) compare the documents with
each other and with the claim form. Each rule owns its wording and states what evidence it must
carry; 20 checks supply the facts and record whether they passed, raised a finding, are waiting
for a document that has not arrived, or did not apply.

| Severity | Rules |
|----------|-------|
| Critical | missing required document, potential alteration (text covered by opaque paint) |
| Review | patient name, UHID and claim-form mismatches, admission and discharge dates, impossible date sequence, diagnosis and procedure inconsistency, surgeon or anaesthetist mismatch, duplicate bill number, bill arithmetic, missing signature, implant not corroborated |
| Warning | duplicate document, duplicate page, low-quality page |
| Note | spelling variant of a name or identifier |

A finding is identified by its rule and a stable subject, so running validation again updates
the finding that already exists rather than adding another. A person moves it on — reviewed,
acknowledged, resolved, reopened — and that decision is never overwritten by a later run. When
the documents change so a rule no longer fires, its finding closes itself; if the rule fires
again, the same finding comes back as reopened. Excluding a duplicate copy keeps the document in
the record but stops it supplying values to the canonical claim.

Nothing is called fraud, forgery or fake — in the rules, in the interface or in the code. A
finding says what differs, points at the page, and says what to do about it; the decision stays
with the person reading it.

### Procedure detection and the checklist

The procedure is read from the documents, not from the claim form: "Laparoscopic
Cholecystectomy", "Lap Chole" and "Lap. Cholecystectomy" are one operation, and the claim's
procedure is the one its documents agree on. Prototype checklists exist for laparoscopic
cholecystectomy, total knee replacement and cataract surgery; a claim for anything else says so
and names the ones that have a checklist rather than guessing.

[`backend/config/checklists.yaml`](backend/config/checklists.yaml) holds the requirements — what
each is, which document types satisfy it, how much a missing one matters and what to do about
it. A procedure lists the requirements it needs and may override any of them: a knee replacement
always expects an implant invoice, where a cholecystectomy expects one only when an implant was
billed, and a cataract claim expects the anaesthesia chart only where the records show more than
local or topical anaesthesia.

| Status | Meaning |
|--------|---------|
| Found | a document of an accepted type is in the claim |
| Missing | no document of an accepted type is in the claim |
| Review required | such a document is there and an open finding is about it |
| Not applicable | the requirement's condition does not hold for this claim |

Requirements are matched against the document type recognised from the content, so a file named
`Operative_Note.pdf` that is not one satisfies nothing, and a copy excluded as a duplicate
satisfies nothing either. The checklist reports; it raises no findings of its own, and lists the
findings the rules raised against the requirement they belong to. A requirement is satisfied by
a document as a whole, so it cites the document and no page — page-level evidence belongs to the
values read from it.

### Questions, uploads and re-analysis

Where the checklist says a required document is missing, the claim asks for it. One question
per requirement, worded from that requirement's own template and given a reason taken from the
claim: *"The documents record an operation, and the surgeon's note of it is not among them."*
Nothing is invented, and nothing is asked about a requirement the claim already meets.

| Answer | What happens |
|--------|--------------|
| Yes, I have it | The question stays open and asks for the document; it closes only when the claim holds one of the expected type |
| Not available | A reason is required, and the question is recorded as documented unavailable |
| Not applicable | A reason is required, and the question is recorded as not applicable |

A document uploaded from a question keeps the question on its record, so the audit trail runs
from the request to the document that answered it. A document that classifies as something
else does not resolve the request: the question stays open and reports what was read instead —
*"Document type does not satisfy this request."* — with the type the classifier gave it.

Processing a new document re-runs what already exists: the canonical claim, the rules, the
checklist and the questions, in that order. The difference between the claim as it was and as
it is now is recorded as one pass, compared **state to state** rather than by reading text, and
a pass only ever describes a settled claim:

```
scan_0042.pdf added and read as operative note
Billed implant is not corroborated by an operative document: open → closed automatically
Operative note is missing: open → closed automatically
Operative note: missing → found
Operative note question: answered → resolved
```

The finding lifecycle is the one from phase 5 — answering a question never closes a finding;
the rules do that when they stop raising it.

### The assistant

The assistant answers about one claim from that claim: its documents, findings, checklist,
questions and last re-analysis. With no API key configured it answers through a deterministic
demo provider that writes from the claim itself — it is not a language model and is not
presented as one. Configure `LLM_PROVIDER` with a key and the same grounded context goes to
Anthropic or to an OpenAI-compatible endpoint instead; a provider without its key never
answers, the demo provider does and says so.

Every answer passes the same guard whichever provider wrote it: citations are resolved against
this claim and dropped when they point at nothing, and a sentence that claims something the
system may not conclude — approval, readiness for submission, medical necessity, a diagnosis,
or any accusation — is removed before the answer is served. What survives is shown with its
sources as chips a reviewer can open.

### Readiness and human review

Documentation readiness is a count, not a prediction: it says how much of the paperwork is
still outstanding, and every point can be read back as the item that cost it. A claim starts at
100 and each outstanding item deducts from it, to a floor of 0
([`backend/config/readiness.yaml`](backend/config/readiness.yaml)):

| Outstanding item | Deduction |
|------------------|-----------|
| Required document missing, request unanswered | −12 |
| Required document documented as unavailable | −6 |
| Requirement needing a look with no finding to explain it | −4 |
| Open critical finding | −8 |
| Open review finding | −5 |
| Open warning finding | −2 |
| Open informational note | 0 |

**An issue is charged once.** A missing document is charged as a missing document; the
missing-document finding the rules raise about it is not charged again, and neither is a rule
that could only be satisfied by the document that is absent — the implant invoice cannot be
corroborated while the operative note is missing, so that consequence is not a second charge.
A question adds nothing of its own: it is how a requirement is answered, and the requirement is
what is charged. A requirement recorded as not applicable costs nothing at all.

| Status | When |
|--------|------|
| Incomplete | A required document is missing and the request for it has not been answered — or nothing has been read yet, or documents of the claim are still being read |
| Needs attention | A finding is open for review, or a requirement needs a person to look at it |
| Ready for human review | Nothing is outstanding in the documentation |

Reaching 100% is not approval. Approval is a person's action: `Approve claim` is offered only
once the documentation is ready for review, refused while anything is outstanding, refused a
second time, and recorded with who approved it and when. Nothing else in the system — not the
rules, the checklist, the questions or the assistant — can approve a claim. The score is
unchanged by approval: it describes the paperwork, and the decision is recorded beside it.

A claim is not ready for review while any of its documents is still being read: what has been
read so far is part of the claim, not the claim, so the score it adds up to is not the score it
will settle at. Two approvals arriving at the same moment produce one approval and one refusal —
the claim is held while the decision is taken, so the audit trail counts what people actually
did.

The demo claim walks the whole path: **44% incomplete** with the operative note and the
anaesthesia record missing, **56%** once the operative note arrives, **68% needs attention**
once the anaesthesia record does, and **100% ready for human review** once the seven findings
have been dealt with.

### The report

One report per claim, assembled once and rendered three ways: a standalone HTML page, a
multi-page PDF and a workbook. They read the same because they are the same payload —
`GET /api/claims/{id}/report` — built from the canonical claim, the findings, the checks, the
checklist, the questions, the readiness and the audit trail. No format carries business logic
of its own; nothing is recalculated for a renderer.

The report keeps four kinds of statement apart, and says so on its own first page:

| | |
|---|---|
| **Documented facts** | What the uploaded documents say, with the document and page each value was read from |
| **System findings** | What the deterministic rules concluded, with their evidence and severity |
| **Unresolved items** | What the claim is still waiting for |
| **Human decisions** | What a person recorded: a finding dealt with, a question answered, an approval |

Every page of the PDF carries the claim number, the page number and the line that a person
makes the final decision; a demo claim carries the notice that its documents are synthetic. The
workbook has a sheet per section — claim summary, readiness, documented facts, findings,
checks, checklist, questions, human decisions, unresolved, documents, bills and the audit
trail — and is written as Office Open XML directly, so the prototype gains no dependency.

Two reports of the same unchanged claim carry the same `content_sha256`: the content is a
function of the claim and nothing else. The files themselves are not byte-identical, because each
one records the moment it was generated — so compare the digest, not the bytes.

An approval is reported as the claim holds it: a claim whose approval was superseded is
reported as superseded, never as currently approved. Exporting a PDF or a workbook is recorded
in the audit trail; reading the report is not.

## API

| Endpoint | Description |
|----------|-------------|
| `GET, HEAD /api/health` | API, database, document-processing engines and AI provider status (`degraded` / 503 until the database is ready) |
| `GET, POST /api/claims` | List claims / create a claim (numbered `CLM-2026-#####`) |
| `GET /api/claims/{id}` | Claim with its documents |
| `GET /api/claims/{id}/audit` | Audit trail of a claim |
| `POST /api/claims/{id}/documents` | Multipart upload of one or more PDF / PNG / JPG files. All files are stored or none are; each is stored read-only with its SHA-256. |
| `POST, GET /api/claims/{id}/demo-documents?set=initial\|operative_note\|anaesthesia_record` | Attach a synthetic document set through the same upload pipeline. Files already attached are skipped. |
| `GET /api/documents/{id}` · `GET /api/documents/{id}/file` | Document metadata · the unmodified original |
| `POST /api/claims/{id}/analyze` | Queue the claim's unprocessed documents (202, returns immediately; one worker processes them in order) |
| `GET /api/claims/{id}/processing` | Live analysis state: per-document stage, progress, type, signals and worker queue |
| `GET /api/documents/{id}/analysis` | Everything found in one document: classification, quality, signatures, covered text, pages, fields, bill |
| `GET /api/documents/{id}/fields[?group=]` | Extracted values with their evidence (page, box, snippet, method, confidence) |
| `GET /api/documents/{id}/pages` · `GET /api/documents/{id}/pages/{n}` | Page list · one page with its text and quality |
| `GET /api/documents/{id}/pages/{n}/image` | Rendered page image (PNG, 150 dpi) |
| `GET /api/documents/{id}/processing` | Processing state of one document |
| `GET /api/claims/{id}/state` | The canonical claim: every section, every value with its sources, weights and competing values |
| `GET /api/claims/{id}/findings[?status=&severity=]` | Findings with their evidence, status and the actions that apply |
| `GET /api/claims/{id}/checks` | Every check that ran: passed, finding raised, waiting or not applicable |
| `GET /api/claims/{id}/checklist` | The detected procedure and its checklist: each requirement found, missing, review required or not applicable, with the documents that satisfy it |
| `GET /api/claims/{id}/questions` | What the claim is asking the operator for, and where each request stands |
| `POST /api/questions/{id}/answer` | `yes_have_it`, `not_available` or `not_applicable`; the last two require a reason |
| `POST /api/questions/{id}/documents` | Upload the document that answers a question. It is queued for processing straight away and resolves the question only if it classifies as the expected type. |
| `GET /api/claims/{id}/changes` | What each pass of analysis changed, as a comparison of two structured states |
| `POST /api/claims/{id}/assistant` | Ask about this claim. The answer carries its sources and the provider that wrote it. |
| `GET /api/assistant/provider` | Which provider answers, and whether a key is configured for it |
| `GET /api/claims/{id}/readiness` | The readiness score, what each deduction is for, what is blocking it, and the seven workflow steps |
| `POST /api/claims/{id}/review/approve` | A person approves the claim. Refused unless the documentation is ready for review, and refused a second time. |
| `GET /api/dashboard` | The workspace: totals, average readiness, every claim with its score, and recent activity |
| `GET /api/claims/{id}/report` | The report as data: the claim, its documented facts, the findings, what is outstanding, the human decisions and the audit trail |
| `GET /api/claims/{id}/report.html` | The same report as a standalone page (own styles, no scripts) |
| `GET /api/claims/{id}/report.pdf` | The same report as a multi-page PDF, page-numbered and downloadable |
| `GET /api/claims/{id}/report.xlsx` | The same report as a workbook, one sheet per section |
| `POST /api/claims/{id}/validate` | Run the rules again over the documents as they stand |
| `POST /api/findings/{id}/action` | `review`, `resolve`, `acknowledge`, `reopen` or `exclude_duplicate` |
| `POST /api/demo/reset` | Body `{"confirm": true}` (JSON only, so other web pages cannot trigger it). Delete all claims and originals, recreate and verify the demo data, restart numbering. Application settings are kept; in-flight requests finish first. |
| `GET /api/demo/profile` · `GET /api/demo/files` | Demo claim details · list and download the demo files |
| `GET /api/audit` | Workspace-wide audit events |
| `/api/docs` | Interactive OpenAPI documentation |

Uploaded originals are written once to `backend/storage/claims/<claim>/originals/` under a name derived from the document ID. They are made read-only (0444) and re-checked against their SHA-256 after writing.

In development, the Vite dev server forwards `/api` to `http://127.0.0.1:8010`. Set `CLAIMAI_API_URL` to point it elsewhere.

## Project structure

```
.
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── main.py          app factory, routers, optional SPA hosting
│   │   ├── config.py        settings (.env)
│   │   ├── db.py            engine, sessions, health probe
│   │   ├── models.py        claims, documents, audit events, claim counters
│   │   ├── schemas.py       API schemas
│   │   ├── storage.py       write-once original storage (SHA-256, read-only)
│   │   ├── audit.py         audit trail helper
│   │   ├── worker.py        single-threaded processing queue (FIFO, restart-safe)
│   │   ├── api/             routes: health, claims, documents, analysis, validation, checklist, questions, assistant, readiness, dashboard, reports, demo, audit
│   │   ├── services/        claims, numbering, intake, demo packs, analysis, canonical, validation, questions, re-analysis, assistant, review, dashboard, workspace reset
│   │   ├── processing/      text layer and covered text, rendering, OCR, quality, signatures, pipeline
│   │   ├── analysis/        classification, value normalisation, field and bill extraction
│   │   ├── canonical/       canonical claim: field map, weighted value selection, builder
│   │   ├── validation/      rule registry, duplicate detection, the checks and the engine
│   │   ├── checklist/       procedure checklist engine
│   │   ├── readiness/       readiness scoring and the workflow steps
│   │   ├── reports/         the report: one assembly, rendered as HTML, PDF and a workbook
│   │   ├── questions/       what the claim asks the operator for
│   │   ├── reanalysis/      the change model: two states compared
│   │   ├── assistant/       claim context, providers, intents and the answer guard
│   │   └── demo_gen/        deterministic synthetic document generator
│   ├── config/              document_types.yaml, quality.yaml, canonical.yaml, rules.yaml, checklists.yaml, readiness.yaml
│   ├── scripts/             ensure_db.py, smoke_test.py
│   └── tests/               pytest suite (isolated SQLite)
├── demo_data/               generated synthetic claim documents, OCR fixtures and manifest
├── frontend/                React web app
│   └── src/
│       ├── app/             router, layout, error boundary
│       ├── components/      layout, UI primitives, claims, upload, analysis, canonical, findings, checklist, questions, changes, assistant, readiness, reports
│       ├── lib/             API client, hooks, types, formatting
│       └── pages/           Dashboard, My Claims, New Claim, claim overview, claim intake, Reports, Settings
├── docker-compose.yml       optional PostgreSQL
├── Makefile
└── .env.example
```

## Product principles

- Deterministic rules handle deterministic validation. An LLM is used only where semantic interpretation helps. Nothing in the pipeline calls a language model.
- Every result says how it was produced: a PDF text layer, an OCR engine by name, or a labelled demo fixture. The application never claims an engine ran when it did not.
- Original uploaded documents are never modified.
- Every value and every finding keeps its source document and page reference whenever possible, and never invents one. Where several documents agree, all of them stay listed.
- AI-generated analysis is clearly distinguished from source evidence.
- Nothing is labelled as fraud, forgery or a fake. Findings are *review required*, *verification required*, *inconsistency*, *duplicate*, *missing* or *not corroborated*, and the rules are tested to keep it that way.
- Every finding is attributable: a deterministic rule, or a measurement made while reading the document. Nothing in the validation engine calls a language model.
- The claim readiness score measures documentation completeness, not the probability that the insurer will accept the claim.
- Final submission always requires authorised human review.

## What this is, and what it is not

The claims above are worth only as much as the evidence behind them, so here is where each part
stands. A buyer or a reviewer should read this before the feature list.

**Deterministic, and tested as such.** Classification, extraction, the canonical claim, the 19
rules and their 20 checks, the procedure checklist, the questions, the readiness score and the
report contain no model and no randomness. The same stored claim produces the same conclusions
every time, and the test suite asserts the numbers rather than that the code runs.

**Measured, not deterministic.** Page quality and signature detection are measurements of a
rendered page: resolution, sharpness, skew, ink above a signature rule. They are reported as
measurements with the page and region they came from. A signature area reported as blank means no
ink was found where a signature belongs — the region is shown so a person can look at it.

**OCR.** Pages with no text layer go through RapidOCR locally. OCR is the least certain step in
the pipeline: a value read below 80% confidence is listed as a source but takes no part in
choosing the canonical value, and every value keeps the engine that read it. The demo documents
carry a text layer, so a demo run exercises OCR on the scanned ones only.

**The assistant.** By default it is not a language model: it composes answers from the claim's own
state. Configure a provider and a key and a real model answers instead, from the same grounded
context, behind the same guard — citations resolved against this claim, and any sentence claiming
approval, readiness for submission, medical necessity or a diagnosis removed before serving. The
guard is a backstop, not a proof: a model given a document that contains instructions may repeat
its text as document content, which is what it is.

**Demo data.** Everything shipped in `demo_data/` is synthetic, generated by
`backend/app/demo_gen`, and its issues are seeded deliberately. No real patient record is used
anywhere in this repository, and the app is not intended to be pointed at one in this state.

**Prototype, and what that excludes.** There is no authentication, no authorisation, no tenancy,
no encryption at rest, no rate limiting, no PII redaction and no retention policy. The operator is
a name in configuration, not an account: `approved_by` records that name, so the audit trail
attributes a decision to a configured operator rather than to an authenticated user. Nothing here
is ready to hold real patient data, and a pilot on real claims needs those parts built first.

**Claim bundles.** A file is divided into the documents it holds before anything else reads it.
On the synthetic demo this is exact: eighteen documents merged into one file come back as the same
eighteen, on the right pages, and the claim means the same as it does when they are uploaded
separately. On real claim packets it is good but not exact — the paperwork is found, the bills are
read and the pre-authorisation forms are recognised, while some pages of a long packet are grouped
more finely than a person would group them, and some are left unclassified rather than guessed at.
Where the system is unsure it says so instead of choosing.

**What has been verified, and how.** Backend tests run the real pipeline over the real synthetic
documents — no mocks of OCR, extraction or rule evaluation. Beyond the suite: the demo path was
run three times from a clean workspace and reached the same conclusions each time; the server was
killed mid-analysis and the claim recovered to the same state as an uninterrupted run; eight
approvals sent at once produced one approval; hostile filenames, oversized and malformed uploads,
and documents containing instructions aimed at the AI were all refused or carried as data. Two
genuine hospital claim packets were read during development to find out how the system behaves on
real paperwork, and deleted afterwards; nothing from them is in this repository. What has **not**
been done: load testing beyond a single operator, a security review by anyone else, and any
measurement of classification or extraction accuracy against human-labelled ground truth — the
accuracy of this pipeline on real hospital documents is still unmeasured.

## License

No license has been selected yet. All rights reserved by the repository owner.
