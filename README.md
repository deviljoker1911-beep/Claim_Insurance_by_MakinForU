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
| 2 | Claim creation and multi-document upload | ⏳ Next |
| 3 | OCR, document classification, data extraction | ⏳ |
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
| Document processing *(from phase 3)* | PyMuPDF, RapidOCR (PaddleOCR models on ONNX Runtime), OpenCV; optional Docling and native PaddleOCR adapters |
| AI *(from phase 7)* | Pluggable provider interface: offline deterministic demo engine (default), Anthropic Claude, OpenAI-compatible APIs |
| Storage | Local filesystem; original uploads are never modified |

## Quick start

**Prerequisites**
- Python 3.12 with [uv](https://docs.astral.sh/uv/)
- Node.js 20.19+ (22+ recommended)
- GNU make
- PostgreSQL 16, either a local server or Docker via `make db-docker`

```bash
git clone https://github.com/deviljoker1911-beep/Claim_Insurance_by_Makinforyou.git
cd Claim_Insurance_by_Makinforyou
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
| `make db` | Create the database named in `DATABASE_URL` if missing |
| `make db-docker` | Start PostgreSQL 16 in Docker (port 5433) |
| `make clean` | Remove build output and caches |

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | API, database, document-processing engines and AI provider status |
| `/api/docs` | Interactive OpenAPI documentation |

In development, the Vite dev server forwards `/api` to `http://127.0.0.1:8010`. Set `CLAIMAI_API_URL` to point it elsewhere.

## Project structure

```
.
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── main.py          app factory, routers, optional SPA hosting
│   │   ├── config.py        settings (.env)
│   │   ├── db.py            engine, sessions, health probe
│   │   ├── models.py        ORM models
│   │   ├── schemas.py       API schemas
│   │   └── api/             route modules (health, …)
│   ├── scripts/ensure_db.py creates the PostgreSQL database
│   └── tests/               pytest suite (isolated SQLite)
├── frontend/                React web app
│   └── src/
│       ├── app/             router, layout, error boundary
│       ├── components/      layout and UI primitives
│       ├── lib/             API client, hooks, types
│       └── pages/           Dashboard, My Claims, New Claim, Reports, Settings
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
