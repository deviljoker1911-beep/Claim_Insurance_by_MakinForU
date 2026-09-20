# ClaimAI

**Check a hospital claim file before it goes to the insurer.**

A claim is rejected for dull reasons. The operative note is missing. The bill adds up wrong. The
patient's name is spelled two ways across four documents. Nobody finds out for three weeks.

ClaimAI reads the documents first. It says what is in the file, what is missing, what disagrees
with what, and how ready the file is to be submitted — and every single thing it says points back
to the page it was read from.

> **A working prototype, not a production insurance platform.** It runs on synthetic data and is
> not ready to hold real patient records. AI-generated validation assistance; final claim
> submission always requires authorised human review. See
> [What this is, and what it is not](#what-this-is-and-what-it-is-not) before you believe any of
> the above — that section is the honest one.

Built by **MakinForU**.

---

## Contents

- [What it does](#what-it-does)
- [Try it in five minutes](#try-it-in-five-minutes)
- [The demo, step by step](#the-demo-step-by-step)
- [How it works](#how-it-works)
  - [Reading the documents](#reading-the-documents)
  - [One file, many documents](#one-file-many-documents)
  - [The canonical claim](#the-canonical-claim)
  - [Validation and findings](#validation-and-findings)
  - [The procedure checklist](#the-procedure-checklist)
  - [Questions and re-analysis](#questions-and-re-analysis)
  - [Readiness and human review](#readiness-and-human-review)
  - [The report](#the-report)
  - [The assistant](#the-assistant)
- [Hosting it](#hosting-it)
  - [The access gate](#the-access-gate)
  - [Deploying to a subdomain](#deploying-to-a-subdomain)
- [Commands](#commands)
- [API](#api)
- [Project structure](#project-structure)
- [Principles](#principles)
- [What this is, and what it is not](#what-this-is-and-what-it-is-not)
- [License](#license)

---

## What it does

```
Upload → read each page → group into documents → classify → extract values
       → build one structured claim → cross-check the documents against each other
       → detect the procedure → apply its document checklist
       → ask the operator about the gaps → take the answers → do it all again
       → readiness score → a person approves → report
```

The whole pipeline runs on the machine it is installed on. The OCR models ship inside the Python
package. Nothing calls out to the internet, and no API key is needed for any part of the demo.

---

## Try it in five minutes

**You need:** Python 3.12 with [uv](https://docs.astral.sh/uv/), Node.js 20.19+ (22+ preferred),
GNU make, and PostgreSQL 16 — either your own, or `make db-docker` to run one in Docker.

```bash
git clone https://github.com/deviljoker1911-beep/Claim_Insurance_by_MakinForU.git
cd Claim_Insurance_by_MakinForU
make setup
make dev
```

Open **http://127.0.0.1:5173**.

`make setup` writes `.env`, installs both sides, and creates the database. It points at the Docker
database on port 5433; edit `DATABASE_URL` in `.env` for a local server, or use
`sqlite:///./storage/claimai.db` to skip PostgreSQL entirely.

---

## The demo, step by step

The whole thing takes about two minutes and needs no files of your own.

1. **New Claim → Fill demo claim details → Create claim & continue.** The claim is numbered
   `CLM-2026-00123`.
2. **Add demo document pack.** Sixteen synthetic documents are attached — admission form,
   consultation note, discharge summary, prescriptions, lab reports, four bills, a consent form.
3. **Start Analysis.** Each file moves through real stages: rendering, OCR, quality check,
   classification, extraction, evidence. The type each document was read as appears with its
   confidence as it finishes.
4. **Claim overview.** One structured claim built from all sixteen: patient, admission, diagnosis,
   procedure, doctors, bills, investigations. Every value has a **Source** chip — click it and the
   page it was read from opens, with the region highlighted.
5. **Readiness: 44%.** Eleven findings. The operative note and the anaesthesia record are missing,
   a bill line does not add up, one bill number is used twice, a name differs on one document, a
   consent signature area is blank.
6. **Answer the two questions.** The claim asks for the two missing documents. Say you have them
   and upload them (`demo_data/later`). Each upload is read immediately, and only resolves the
   request if it classifies as the document that was actually asked for.
7. **Readiness: 56%, then 68%.** The missing-document findings close themselves. The checks that
   were waiting on those documents can now run.
8. **Work the findings.** Acknowledge or resolve each one. The score moves with every decision.
9. **Readiness: 100% — Ready for human review.** The **Approve claim** button becomes available.
   It was disabled until now, and nothing in the system can press it.
10. **Approve.** The claim records who approved it, when, and at what score.
11. **Report.** The same report as a page, a PDF and an Excel workbook. If you then upload another
    document, the approval is marked **superseded** — it was given to a claim that has since
    changed.

The synthetic claim and its deliberately seeded problems are described in
[`demo_data/README.md`](demo_data/README.md).

---

## How it works

### Reading the documents

Each file is rendered at 150 dpi. If it has a text layer, that is used. If it does not, it goes
through RapidOCR locally. Every page is measured for sharpness, skew and resolution, and every
extracted value records which engine read it and how confident it was. A value read below 80%
confidence is still listed as a source but takes no part in choosing the final answer.

Pages are also checked for text covered by opaque paint, and for signature areas with no ink in
them. Both are reported as measurements with the region to look at — never as a verdict.

**Uploaded originals are never modified.** Each one is written once, made read-only (0444), and
re-checked against its SHA-256 after writing.

### One file, many documents

Real claims arrive as one PDF for the whole claim, not one PDF per document. Read as a single
document, a 23-page packet becomes whatever its first page looks like, and everything genuinely
inside it gets reported as missing.

So the file is divided before anything else reads it. Pages are grouped into the documents they
belong to, using page numbering ("page 2 of 3"), document identifiers printed on them, headings,
and what each page reads as. Every page gets a role — *starts a document*, *continues one*, or
*ambiguous* — and a reason for it, so the grouping can be reviewed rather than trusted.

Each document then keeps the pages it came from. A value read from page 7 of a bundle says page 7
of that bundle, and clicking it opens that page.

Where there is no evidence either way, the page is marked ambiguous and kept with the one before
it, and the document says so. Guessing silently would be worse.

### The canonical claim

Sixteen documents disagree. The admission form and the discharge summary give different dates; the
pharmacy bill spells the patient's name differently. The canonical claim picks one value per field
by weighing the documents that state it — a discharge summary outranks a pharmacy bill on a
diagnosis — and keeps every competing value visible underneath with its source.

Nothing is invented. A field no document states is *not documented*, not blank and not guessed.

### Validation and findings

Nineteen rules produce twenty checks. They are deterministic: the same documents always produce
the same findings. Each one says what was compared, what it found, and what a person should do —
with the arithmetic shown where there is arithmetic:

> Hospital bill line 1 (Room Rent — Twin Sharing, 12-01-2026 to 16-01-2026) bills 4 × 4,500.00 as
> 20,000.00; 4 × 4,500.00 is 18,000.00, a difference of 2,000.00.
> **Do:** Ask the hospital billing desk to correct the bill or explain the difference.

Findings are *critical*, *review*, *warning* or *info*, and a person can mark one reviewed,
acknowledge it, resolve it, reopen it, or exclude a document as a duplicate. Every check that ran
is listed too — including the ones that passed and the ones still waiting on a document — so an
empty findings list can be told apart from a check that never ran.

**No finding ever says fraud, forgery or fake.** The vocabulary is *review required*,
*verification required*, *inconsistency*, *duplicate*, *missing*, *not corroborated*, *potential
alteration*. Tests enforce this.

### The procedure checklist

The procedure is detected from the documents that name it, not from a dropdown. Thirteen
requirements apply to a laparoscopic cholecystectomy; each one is *found*, *missing*, *review
required* or *not applicable*, with the documents that satisfy it and what to do if none do.

### Questions and re-analysis

For each gap the claim asks one question, in plain language, naming the document type it expects.
The operator answers **Yes, I have it** (and uploads), **Not available** or **Not applicable** —
the last two need a reason, which is recorded.

An uploaded answer is read immediately and only resolves the request if it classifies as the type
that was asked for. Upload a lab report where an operative note was asked for and the system says
so, and the request stays open.

Every pass records what changed against the pass before it: documents added, findings opened and
closed, checklist requirements satisfied, values that moved, questions answered.

### Readiness and human review

Readiness measures **documentation completeness** — not the probability that the insurer will pay.

It starts at 100 and deducts for what is outstanding, and the panel shows every deduction with
what it is for, ending in the score. A claim nobody has read scores 0 and says so, rather than
scoring 100 because nothing is outstanding yet.

**Approval is a human action.** The button is disabled until the documentation is ready, it refuses
a claim that is not, and nothing in the pipeline can approve anything. If the claim changes after
approval — one more document, one more finding — the approval is marked **superseded**, because it
was given to a claim that no longer exists.

### The report

One report, rendered three ways: a standalone HTML page, a page-numbered PDF, and an Excel workbook
with a sheet per section. All three are generated from the same assembly, so they cannot disagree.

It keeps four kinds of statement apart: what the documents say, what the rules found, what is still
outstanding, and what a person decided. The audit trail is included whole.

### The assistant

By default it is **not a language model**. It answers from the claim's own state, and every answer
carries its sources.

Configure a provider and a key and a real model answers instead — from the same grounded context,
behind the same guard: citations are resolved against this claim, and any sentence claiming
approval, readiness for submission, medical necessity or a diagnosis is removed before serving.
The guard is a backstop, not a proof.

---

## Hosting it

### The access gate

A public deployment can ask every visitor for an email address before anything else answers.

It is deliberately not a login. Anyone may come in — they give an address, receive a six-digit
code, and type it back. The point is that a public URL with an open upload endpoint has a name
attached to every session, and that the people who came to look can be counted and contacted.

- The code is stored only as a hash, expires in ten minutes, and is worth five attempts.
- One address may ask for five codes an hour; one caller may ask for twenty. Without those limits
  the endpoint is a way to send mail in someone else's name.
- The session is a signed cookie. A browser can read its own session but cannot write one.
- **It guards the API, not the page.** Skipping the screen gets you nothing, because every
  endpoint refuses without a session.
- With no mail server configured, the code is written to the application log and the screen says
  so. The gate still works; it does not pretend a message was sent.

Read the captured list with the admin token:

```bash
curl -H "X-Admin-Token: $ACCESS_ADMIN_TOKEN" https://claimai.makinforu.com/api/access/visitors
```

Every address that asked is there, whether or not they finished — someone who asked and never came
back is still a lead. **A demo reset clears the claims and keeps the people.** With no
`ACCESS_ADMIN_TOKEN` set, that endpoint is not served at all.

The gate is **off by default**, so local development, the test suite and an offline demo never see
it.

### Deploying to a subdomain

One container serves the API and the built web app on a single port. Alongside it: PostgreSQL, and
Caddy to get the TLS certificate.

**What the server needs.** 2 vCPU and 4 GB RAM is comfortable; OCR is the only demanding part and
it runs one document at a time. The image is about 1.9 GB — the OCR runtime and its models are
most of it — so allow 15 GB of disk for the image, the database and the uploads together.

**Before you start**, point an `A` record for your subdomain at the server. Caddy asks Let's
Encrypt for the certificate on the first request, and that depends on the name already resolving.

```bash
# on the server
git clone https://github.com/deviljoker1911-beep/Claim_Insurance_by_MakinForU.git
cd Claim_Insurance_by_MakinForU

cp deploy/env.example .env.prod
# fill it in — see below. It will not start without the secrets.

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

What `.env.prod` needs:

| Variable | What it is |
|----------|------------|
| `CLAIMAI_DOMAIN` | The hostname you are serving, e.g. `claimai.makinforu.com`. Its DNS must already point here. |
| `POSTGRES_PASSWORD` | The database password. Used by the database and the app. |
| `ACCESS_SESSION_SECRET` | Signs the session cookie. `openssl rand -hex 32`. Changing it signs everyone out, which is the only way to revoke a session. |
| `ACCESS_ADMIN_TOKEN` | Reads the visitor list. Leave empty and that endpoint is not served. |
| `SMTP_*` | Where access codes are sent from. Leave `SMTP_HOST` empty and codes go to the container log instead. |
| `DEMO_PACING_MS` | Slows the visible stages so an audience can follow them. `0` runs at full speed. |

Then:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f app
curl https://claimai.makinforu.com/api/health
```

**The storage volume holds the uploaded originals.** They are not rebuilt from anything, so a lost
volume is lost documents. Back up `claimai-storage` and `claimai-pgdata` together, or neither is
much use.

To update:

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

---

## Commands

| Command | What it does |
|---------|--------------|
| `make setup` | First run: `.env`, dependencies, database |
| `make dev` | API on `:8010` and web app on `:5173` |
| `make backend` / `make frontend` | One side only |
| `make demo` | Build the web app and serve everything from the API on `:8010` |
| `make test` | Backend tests, frontend lint, production build |
| `make smoke` | End-to-end test against the running API and its real database |
| `make reset` | Reset the demo workspace (next claim: `CLM-2026-00123`) |
| `make demo-data` / `make demo-check` | Regenerate the synthetic documents / verify them byte for byte |
| `make db` / `make db-docker` | Create the database / run PostgreSQL 16 in Docker |
| `make clean` | Remove build output and caches |

---

## API

Full interactive documentation at `/api/docs`.

**Claims and documents**

| Endpoint | Description |
|----------|-------------|
| `GET, HEAD /api/health` | API, database, processing engines and AI provider status |
| `GET, POST /api/claims` | List / create a claim |
| `GET /api/claims/{id}` · `/audit` | A claim with its documents · its audit trail |
| `POST /api/claims/{id}/documents` | Multipart upload of PDF / PNG / JPG. All files are stored or none are. |
| `GET, POST /api/claims/{id}/demo-documents?set=` | Attach a synthetic set through the same pipeline |
| `GET /api/documents/{id}` · `/file` · `/analysis` · `/fields` · `/pages` · `/pages/{n}/image` | Metadata · the unmodified original · everything found in it · values with evidence · pages · a rendered page |

**Analysis and validation**

| Endpoint | Description |
|----------|-------------|
| `POST /api/claims/{id}/analyze` | Queue the claim's unprocessed documents (202) |
| `GET /api/claims/{id}/processing` | Live state: per-document stage, progress, worker queue |
| `GET /api/claims/{id}/state` | The canonical claim: every value with its sources and competing values |
| `GET /api/claims/{id}/findings` · `/checks` · `/checklist` | Findings with evidence · every check that ran · the procedure checklist |
| `POST /api/claims/{id}/validate` | Run the rules again |
| `POST /api/findings/{id}/action` | `review`, `resolve`, `acknowledge`, `reopen`, `exclude_duplicate` |

**Questions, readiness and review**

| Endpoint | Description |
|----------|-------------|
| `GET /api/claims/{id}/questions` | What the claim is asking for, and where each request stands |
| `POST /api/questions/{id}/answer` · `/documents` | `yes_have_it` / `not_available` / `not_applicable` · upload the document that answers it |
| `GET /api/claims/{id}/changes` | What each pass changed |
| `GET /api/claims/{id}/readiness` | The score, each deduction, what is blocking, the workflow steps |
| `POST /api/claims/{id}/review/approve` | A person approves. Refused unless the documentation is ready. |
| `POST /api/claims/{id}/assistant` · `GET /api/assistant/provider` | Ask about this claim · which provider answers |

**Reports, workspace and access**

| Endpoint | Description |
|----------|-------------|
| `GET /api/claims/{id}/report` · `.html` · `.pdf` · `.xlsx` | The report as data, a page, a PDF, a workbook |
| `GET /api/dashboard` · `/api/audit` | The workspace at a glance · workspace-wide audit events |
| `POST /api/demo/reset` | Body `{"confirm": true}`. Delete all claims and originals, restart numbering. Settings and visitors are kept. |
| `GET /api/access/session` · `POST /api/access/request` · `/verify` · `/signout` | The gate |
| `GET /api/access/visitors` | Everyone who asked for access. Needs `X-Admin-Token`. |

---

## Project structure

```
.
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── main.py          app factory, routers, access gate, optional SPA hosting
│   │   ├── access/          the email gate: codes, sessions, delivery
│   │   ├── api/             routes
│   │   ├── services/        claims, intake, analysis, canonical, validation, questions,
│   │   │                    re-analysis, review, dashboard, segmentation, workspace
│   │   ├── processing/      text layer, rendering, OCR, quality, signatures, pipeline
│   │   ├── segmentation/    one file read as the documents it holds
│   │   ├── analysis/        classification, normalisation, field and bill extraction
│   │   ├── canonical/       weighted value selection and the claim builder
│   │   ├── validation/      rule registry, duplicate detection, checks, engine
│   │   ├── checklist/       procedure checklist engine
│   │   ├── readiness/       scoring and the workflow steps
│   │   ├── reports/         one assembly, rendered as HTML, PDF and a workbook
│   │   ├── assistant/       claim context, providers, intents, answer guard
│   │   └── demo_gen/        deterministic synthetic document generator
│   ├── config/              document types, quality, canonical, rules, checklists, readiness,
│   │                        segmentation — the behaviour lives in YAML, not in code
│   └── tests/               869 tests over the real pipeline
├── demo_data/               synthetic documents, OCR fixtures, manifest
├── frontend/src/            React app: pages, components, API client and hooks
├── deploy/                  Caddyfile and the production env template
├── Dockerfile               one container: API + built web app
├── docker-compose.prod.yml  app, database and TLS proxy
└── docker-compose.yml       PostgreSQL for local development
```

---

## Principles

- **Deterministic work is done by deterministic code.** Nothing in the pipeline calls a language
  model — not classification, not extraction, not the rules, not readiness.
- **Every result says how it was produced**: a PDF text layer, an OCR engine by name, a labelled
  fixture. The application never claims an engine ran when it did not.
- **Original documents are never modified.**
- **Every value and every finding keeps its source** — document, page, region — and never invents
  one. Where several documents agree, all of them stay listed.
- **Nothing is called fraud, forgery or fake.**
- **Readiness measures documentation completeness**, not the likelihood of payment.
- **Approval is a human action**, and stops standing when the claim changes underneath it.
- **The demo runs offline**, with no API key and no network.

---

## What this is, and what it is not

The claims above are worth only as much as the evidence behind them. This section is where each
one actually stands.

**Deterministic, and tested as such.** Classification, extraction, the canonical claim, the 19
rules and their 20 checks, the checklist, the questions, readiness and the report contain no model
and no randomness. The same stored claim produces the same conclusions every time. The full demo
journey has been run five times from a clean workspace and came out identical on all seventeen
aspects checked — documents, findings, checklist, questions, readiness, approvals and all three
report formats.

**Measured, not deterministic.** Page quality and signature detection are measurements of a
rendered page: resolution, sharpness, skew, ink above a signature rule. A signature area reported
as blank means no ink was found where a signature belongs, and the region is shown so a person can
look for themselves.

**OCR is the least certain step.** Pages without a text layer go through RapidOCR locally. Values
read below 80% confidence are listed but do not choose the answer. The demo documents mostly carry
a text layer, so a demo run exercises OCR only on the scanned ones.

**Claim bundles.** On the synthetic demo this is exact: eighteen documents merged into one file
come back as the same eighteen, on the right pages, and the claim means the same as when they are
uploaded separately. Against a labelled packet it recovers 8 of 10 documents exactly and cuts no
document in half. On real hospital packets every document gets a type and the bills are read, but
confidence is often low — a scanned pathology report carries its hospital's letterhead where its
heading should be — and a run of pharmacy bills is grouped by the numbers printed on them, which
is right only as far as those numbers were read correctly.

**The access gate is identification, not authorisation.** It records who is looking. It is not a
login, there are no roles or permissions, there is no tenancy, and everyone who gets in sees the
same single workspace and each other's claims. An address is only as real as the inbox behind it.
The operator on the audit trail is still a configured name, not the visitor.

**What a prototype still excludes.** No authorisation, no tenancy, no encryption at rest, no PII
redaction, no retention policy, no rate limiting outside the access gate. **Nothing here is ready
to hold real patient data**, and a pilot on real claims needs those parts built first.

**Demo data.** Everything in `demo_data/` is synthetic, generated by `backend/app/demo_gen`, and
its problems are seeded deliberately. No real patient record is in this repository. Two genuine
hospital claim packets were read during development to find out how the system behaves on real
paperwork, and deleted afterwards; nothing from them is here.

**What has been verified.** The test suite runs the real pipeline over the real synthetic
documents — no mocks of OCR, extraction or rule evaluation. Beyond it: the server has been killed
mid-analysis and the claim recovered to the same state as an uninterrupted run; eight simultaneous
approvals produced one approval; hostile filenames, oversized and malformed uploads, and documents
containing instructions aimed at the AI were all refused or carried as data.

**What has not.** Load testing beyond a single operator. A security review by anyone other than
its author. And any measurement of classification or extraction accuracy against human-labelled
ground truth — **the accuracy of this pipeline on real hospital documents is unmeasured.**

---

## License

No license has been selected. All rights reserved by the repository owner.
