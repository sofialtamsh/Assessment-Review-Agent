# Assessment Review Pipeline

A production-grade, **multi-agent assessment question review pipeline** with a web
dashboard, built for NxtWave's Data Science & ML program. It ingests a mastersheet,
a question set, and session content (PPT/PDF), runs a **7-phase LangGraph review**,
and recommends **APPROVE / REVISE / DELETE** per question — with a human always in the
loop for deletes and regenerations.

- **Quality-first, cost-controlled.** Mechanical checks run in pure Python (no LLM);
  cheap checks route to **Haiku**, semantic-heavy checks + Judge to **Sonnet** (via
  OpenRouter). Questions are batched per call, embeddings are cached, and every run has
  a **token budget with a hard stop** and an end-of-run **cost report**.
- **Runs for $0 with no API key.** A built-in **mock provider** returns deterministic,
  defect-catching findings so the whole pipeline + dashboard demo offline. Flip one
  config flag to use real Claude models.
- **Human-in-the-loop.** Nothing is auto-deleted or auto-replaced. Every verdict, edit,
  approval, and regeneration is written to an **audit log**. Regenerated/edited questions
  are re-reviewed before they can enter an approved set.

---

## The 7 phases

| Phase | Agent | Model | What it checks |
|------|-------|-------|----------------|
| 1 | Deterministic pre-checks | none (Python) | schema validity (missing/invalid keys, multi-with-one-key, T/F with >2 options), answer-key balance, difficulty distribution, exact + fuzzy duplicates |
| 2 | Language & Logic | Haiku | grammar/clarity, answerability, key↔explanation consistency, option quality (giveaways, length leaks) |
| 3 | Ambiguity & Overlap | Sonnet + embeddings | semantic duplicates within the set, cross-set overlap with the in-class quiz, defensible-option ambiguity |
| 4 | Scope & Source (RAG) | Sonnet + embeddings | is the question answerable from what was taught? verbatim lifts of worked examples |
| 5 | Pedagogy | Sonnet | Bloom's classification, subtopic coverage gaps / over-testing, scenario-vs-recall ratio, code-in-concept-question smell |
| 6 | Judge / Aggregator | Sonnet | merges all findings → one verdict + reason + consolidated fixes |
| 7 | Fixer (on demand) | Sonnet | regenerates a flagged question grounded only in session content, then re-runs phases 2–4 on it |

Phases 3–4 use a **candidate-then-confirm** design: real embeddings/retrieval generate
candidates deterministically, and the model confirms — so the offline mock still catches
the seeded defects, and swapping in a real model only improves judgement.

---

## Repository layout

```
backend/            FastAPI + LangGraph pipeline
  app/
    ingestion/      mastersheet / questions / content (pptx,pdf) normalizers
    graph/          LangGraph state + build + 7 phase nodes
    llm/            provider contract, mock provider, OpenRouter provider, budget runner
    embeddings.py   pluggable embeddings (local sentence-transformers | voyage) + cache
    schemas.py      normalized Question, Finding, Judgment, SetReport, Cost, Budget
    main.py         REST + SSE endpoints
  prompts/          one tunable prompt per agent
  config.yaml       model routing, batch size, token budget, thresholds
  tests/            pytest suite over the seeded sample set (mock provider)
frontend/           Next.js (App Router) + Tailwind dashboard
sample_data/        mastersheet + 15-question assignment (4 seeded defects) + quiz + PPT
```

---

## Quick start (offline, $0)

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate       macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

# (optional) regenerate the sample PPT
python ../sample_data/make_ppt.py

uvicorn app.main:app --reload --port 8000
```

The default `config.yaml` uses `llm.provider: mock`, so **no API key is needed**.
Open http://localhost:8000/docs for the API.

Run the tests:

```bash
pytest -q          # 16 tests, all offline
```

### 2. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local     # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                          # http://localhost:3000
```

### 3. Demo the pipeline

1. On **Upload & Run**, drop the four files from `sample_data/`:
   `mastersheet.csv`, `assignment_session_ds_07.csv`, `in_class_quiz_ds_07.csv`,
   `session_ds_07.pptx` (pick session `ds_07` for the content), then **Ingest files**.
2. Select session **ds_07**, set = **MCQ assignment**, click **Run review** and watch
   the Phase 1 → 7 checklist tick through live.
3. On the **Dashboard** you'll see the seeded defects caught:
   - **q06** (Ridge regression) → out of scope → **DELETE**
   - **q05** (copies the PPT worked example) → verbatim lift
   - **q02/q03** → semantic duplicate + cross-set overlap with the quiz
   - **q07** → option ambiguity; **q11/q12** → schema issues; key-balance skew
4. Open any question to see every agent's finding with evidence, then
   **Approve / Edit / Delete / Regenerate** (regeneration shows the grounded
   replacement side-by-side and re-reviews it before you apply).
5. **Export approved CSV** and the **Markdown report** from the dashboard header.

---

## Reviewing your curriculum straight from the mastersheet (recommended)

The system **generates nothing** — it pulls everything from the links already in your
mastersheet. **Upload the sheet as `.xlsx`** (Excel keeps the hyperlinks; CSV drops
them), then just pick a unit:

1. **Upload & Run → "Ingest mastersheet"** with your `.xlsx`. The backend reads each
   row's hyperlinks and groups rows by unit (Session + Tutorial + MCQ Practice).
2. Pick a **unit** from the dropdown and a **review set** (MCQ assignment or in-class quiz).
3. Click **"Fetch & Review"**. In one call the backend:
   - fetches the **session slides** (Google Slides published page → slide text),
   - fetches + parses the **MCQ assignment** (Google Doc → `export?format=txt` → MCQs),
   - fetches the **tutorial doc** and extracts the 5 in-class MCQs at its end (for
     cross-set overlap),
   - runs the full 7-phase review.

No repeated uploads, no separate question-set file. It works because the docs are shared
"anyone with link", which Google exports publicly.

How the columns map: **Unit** → the unit, **Topic** → module, **What to Cover** →
taught subtopics, **PPT** (hyperlink) → the Slides/Doc to fetch, **Embedded links** →
published slides.

API equivalents:
```
POST /upload/mastersheet            # .xlsx -> returns {mode:"units", units:[...]}
GET  /units                          # units + which sets/content are available
POST /units/{unit_id}/prepare_and_run   {"set":"mcq_assignment"|"in_class_quiz"}
```

**Accuracy note:** run these with `llm.provider: openrouter` (real Claude). The offline
`mock` provider is only for plumbing/tests — its scope check is a crude lexical heuristic
and will over-flag "out of scope" on real content; the real model reads the actual slide
text and judges correctly.

### Manual upload (fallback)
The **Advanced** section on Upload & Run still accepts your own question-set file
(CSV/XLSX/JSON) + content file (.pptx/.pdf/.md) for a one-off review. The `make_ppt.py`
script only builds the throwaway demo PPT for the offline sample — never used for real data.

## Using real Claude models (OpenRouter)

Edit `backend/config.yaml`:

```yaml
llm:
  provider: openrouter        # was: mock
```

Set your key and run:

```bash
export OPENROUTER_API_KEY=sk-or-...    # Windows: setx OPENROUTER_API_KEY sk-or-...
uvicorn app.main:app --reload --port 8000
```

Model routing lives in `config.yaml` (`models:`) — cheap phases → `anthropic/claude-haiku-4.5`,
semantic phases + Judge/Fixer → `anthropic/claude-sonnet-4.5`. Adjust per phase without
touching code. The cost panel shows per-phase tokens and $ using the `pricing:` table;
set `budget.token_limit` to enforce a per-run hard stop.

### Better semantic embeddings (optional)

The default embeddings backend is `local`, which uses `sentence-transformers` if installed
and otherwise falls back to a deterministic lexical hashing embedding (keeps the demo
offline). For stronger paraphrase detection:

```bash
pip install sentence-transformers      # enables all-MiniLM-L6-v2 locally
```

Or switch `embeddings.backend: voyage` in `config.yaml` and set `VOYAGE_API_KEY`.

---

## Environment variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `OPENROUTER_API_KEY` | backend | Claude access via OpenRouter (only when `provider: openrouter`) |
| `VOYAGE_API_KEY` | backend | only when `embeddings.backend: voyage` |
| `LLM_PROVIDER` | backend | force `mock` / `openrouter` regardless of config.yaml |
| `ARP_DB_PATH` | backend | override the SQLite path (tests use this) |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | URL of the backend API |

---

## Deploying

### Frontend → Vercel

1. Push the repo to GitHub. In Vercel, **New Project → import the repo** and set the
   **Root Directory** to `frontend/`.
2. Add the environment variable **`NEXT_PUBLIC_API_BASE_URL`** = your deployed backend URL
   (e.g. `https://assessment-api.onrender.com`).
3. Deploy. Vercel auto-detects Next.js (build `next build`, output handled automatically).

### Backend → Railway / Render / any VM

The backend is a standard ASGI app. Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Install `backend/requirements.txt`, set `OPENROUTER_API_KEY` (for real runs). SQLite lives
in `backend/review.db`; mount a volume if you want it to persist across deploys. CORS is
open by default — restrict `allow_origins` in `app/main.py` for production.

---

## Design notes

- **Ingestion** normalizes CSV/XLSX/JSON question sets and PPT/PDF content into one internal
  `Question` / `Chunk` schema (`app/schemas.py`), so every downstream phase is format-agnostic.
- **Every agent emits structured `Finding`s** (`question_id, check_name, verdict, evidence,
  suggested_fix, …`) — never free prose — which the Judge and report consume uniformly.
- **LangGraph** appends findings across phases via a reducer; a failed or budget-stopped phase
  records an error and is skipped, so deterministic results already gathered survive and the
  run stays usable (`app/graph/build.py`, `app/jobs.py`).
- **Cost control**: batching (`llm.batch_size`), embedding cache (SQLite), per-run token budget
  with a hard stop checked before each call, and a per-phase cost report.
- **Prompts** live in `backend/prompts/*.md` — tune agent behavior without touching code.
