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
Document upload → OCR → Classification → Extraction → Claim structuring
→ Cross-document validation → Procedure detection → Procedure checklist
→ Missing-document detection → AI questions → Operator upload / confirmation
→ Re-analysis → Claim documentation readiness report → Human final review
```

## Build status

| Phase | Scope | Status |
|------:|-------|--------|
| 1 | Application running: API health, app shell, tooling | ✅ Done |
| 2 | Claim creation, multi-document upload, deterministic demo data | ✅ Done |
| 3 | OCR, document classification, data extraction | ⏳ Next |
| 4 | Canonical claim model | ⏳ |
| 5 | Cross-document deterministic validation | ⏳ |
| 6 | Procedure detection and procedure checklist engine | ⏳ |
| 7 | Interactive questions, upload and incremental re-analysis | ⏳ |
| 8 | Readiness engine and dashboard | ⏳ |
| 9 | Final report (PDF / Excel) and audit trail | ⏳ |
| 10 | UI polish and demo experience | ⏳ |

## Tech stack

| Layer | Technology |
|-------|------------|
| Web app | React 19, TypeScript, Vite 8, Tailwind CSS 4, React Router 8, TanStack Query, lucide icons |
| API | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 |
| Database | PostgreSQL 16 (SQLite fallback for zero-setup runs) |
| Documents | PyMuPDF (PDF validation and page counts); from phase 3: RapidOCR (PaddleOCR models on ONNX Runtime), OpenCV, optional Docling and native PaddleOCR adapters |
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
4. Each file is listed with its size, page count, upload state, processing state and document ID. **Start Analysis** arrives in phase 3.

The synthetic claim and its deliberately seeded issues are described in [`demo_data/README.md`](demo_data/README.md).

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
│   │   ├── api/             routes: health, claims, documents, demo, audit
│   │   ├── services/        claims, numbering, intake, demo packs, workspace reset
│   │   ├── processing/      PyMuPDF access (serialised)
│   │   └── demo_gen/        deterministic synthetic document generator
│   ├── scripts/             ensure_db.py, smoke_test.py
│   └── tests/               pytest suite (isolated SQLite)
├── demo_data/               generated synthetic claim documents and manifest
├── frontend/                React web app
│   └── src/
│       ├── app/             router, layout, error boundary
│       ├── components/      layout, UI primitives, claims, upload
│       ├── lib/             API client, hooks, types, formatting
│       └── pages/           Dashboard, My Claims, New Claim, claim intake, Reports, Settings
├── docker-compose.yml       optional PostgreSQL
├── Makefile
└── .env.example
```

## Product principles

- Deterministic rules handle deterministic validation. An LLM is used only where semantic interpretation helps.
- Original uploaded documents are never modified.
- Every finding keeps its source document and page reference whenever possible, and never invents one.
- AI-generated analysis is clearly distinguished from source evidence.
- Nothing is labelled as fraud. Items are marked *Review Required*, or *Potential alteration detected — human verification required*.
- The claim readiness score measures documentation completeness, not the probability that the insurer will accept the claim.
- Final submission always requires authorised human review.

## License

No license has been selected yet. All rights reserved by the repository owner.
