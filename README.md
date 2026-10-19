# Autonomous QA Testing Agent

An AI-assisted autonomous QA testing system. Give it a target URL and a
natural-language testing goal; it explores the application with Playwright,
generates structured test cases, executes them, classifies failures, captures
evidence, and produces reproducible bug reports — all persisted in SQLite.

Built as a portfolio-quality MVP for QA Engineer / SDET / QA Automation
interviews. Runs fully deterministically with no LLM API key required.

## Tech stack (MVP)

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 |
| API | FastAPI + Pydantic v2 |
| Browser automation | Playwright (Chromium) |
| Test runner | pytest |
| Database | SQLite (single file, repository layer) |
| LLM | Optional (OpenAI-compatible / Groq / Ollama); disabled by default |
| Frontend | Single-page HTML/JS dashboard |
| Packaging | pyproject.toml, optional Dockerfile |

## Project structure

```
autonomous-qa-agent/
  app/                FastAPI application
    main.py           App factory, routes, health, dashboard
    api/routes/       runs, tests, bugs, artifacts endpoints
    core/             config, security (SSRF/scope), logging
    schemas/          Pydantic request/response schemas
    services/         explorer, generator, validator, executor,
                      analyzer, bug reporter, pipeline, LLM provider
    repositories/     SQLite repository layer
    static/           Dashboard HTML/CSS/JS
  demo-app/           Local hotel-booking demo target with injectable defects
  artifacts/          Screenshots and execution evidence (runtime)
  data/               SQLite database (runtime)
  tests/              unit / integration / security (pytest)
  docs/               ARCHITECTURE.md, INTERVIEW_GUIDE.md
```

## Prerequisites

* Python 3.12+ (3.12.1 tested)
* PowerShell or any shell
* Playwright browsers (installed below)

No PostgreSQL, Redis, or message broker is used — the MVP keeps everything in
one SQLite file and one background execution loop, per the design goals.

## 1. Install and run locally

From the project root:

```powershell
# Create and activate a virtual environment (recommended)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
python -m pip install --upgrade pip
python -m pip install -e .

# Install the Playwright Chromium browser
python -m playwright install chromium
```

### Start the demo application (target under test)

```powershell
python demo-app/server.py 3000
# Serves http://localhost:3000
```

Open `http://localhost:3000` in a browser to see the demo shop: home, register,
sign in, search, results, booking, confirmation. The `/config` page lets you
toggle five injectable defects.

### Start the agent backend

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

* Health: http://127.0.0.1:8000/health
* API docs: http://127.0.0.1:8000/docs
* Dashboard: http://127.0.0.1:8000/dashboard

## 2. Run an end-to-end test (PowerShell)

Create a run against the demo with the default goal:

```powershell
$body = '{"target_url":"http://localhost:3000","goal":"Verify that a user can register, log in, search for a hotel, select a room, and complete the booking form. Check input validation and error handling."}'
$run = curl.exe -sS -X POST http://127.0.0.1:8000/api/v1/runs -H "Content-Type: application/json" -d $body
$run | ConvertFrom-Json | Select-Object id, status
```

Poll until completion:

```powershell
$id = (curl.exe -sS $body | ... ) # see below
for ($i = 0; $i -lt 60; $i++) {
  $r = curl.exe -sS http://127.0.0.1:8000/api/v1/runs/<RUN_ID>
  if ($r -match '"status":"(completed|failed)"') { break }
  Start-Sleep -Seconds 2
}
```

Inspect results and bugs:

```powershell
curl.exe -sS http://127.0.0.1:8000/api/v1/runs/<RUN_ID>/tests | ConvertFrom-Json
curl.exe -sS http://127.0.0.1:8000/api/v1/runs/<RUN_ID>/bugs | ConvertFrom-Json
```

## 3. Demonstrate a detected defect + regression

The demo app (`demo-app/server.py`) exposes a defect control endpoint:

```powershell
# Enable the "registration accepts invalid email" defect
curl.exe -sS -X POST http://localhost:3000/__demo/defects -H "Content-Type: application/json" -d '{"defects":["invalid_email_accepted"]}'

# Run the agent again → the "Reject invalid registration email" test fails
# and a CRITICAL bug report is auto-generated with screenshot + console evidence.

# Disable the defect (the fix)
curl.exe -sS -X POST http://localhost:3000/__demo/defects -H "Content-Type: application/json" -d '{"defects":[]}'

# Rerun the failed test via the API → it now passes
curl.exe -sS -X POST http://127.0.0.1:8000/api/v1/tests/<TEST_ID>/rerun -H "Content-Type: application/json" -d '{}'
```

Five defects can be toggled individually:
1. Registration accepts an invalid email
2. Login shows an incorrect error message
3. Search ignores the selected price filter
4. Booking accepts a check-out date before check-in
5. Submit works but shows no confirmation

## 4. Run the test suite

```powershell
# All tests (unit + integration + security); no LLM key needed
python -m pytest tests

# By category
python -m pytest tests/unit
python -m pytest tests/integration
python -m pytest tests/security

# With a report
python -m pytest tests --html=report.html --self-contained-html
```

Integration tests spawn the demo server and drive a real Playwright browser.
Security tests assert that unauthorized URLs (private IP ranges, cloud metadata,
other schemes) are rejected before any browser starts.

## 5. Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Purpose |
|----------|---------|
| `QA_HOST`, `QA_PORT` | API bind address |
| `QA_DATABASE_URL` | SQLite file path (default `data/qa_agent.db`) |
| `QA_ARTIFACTS_DIR` | Screenshot/evidence directory |
| `QA_MAX_CRAWL_PAGES`, `QA_MAX_CRAWL_DEPTH` | Exploration bounds |
| `QA_ACTION_TIMEOUT_MS`, `QA_NAVIGATION_TIMEOUT_MS` | Playwright timeouts |
| `QA_BROWSER`, `QA_HEADLESS` | Playwright browser / headless mode |
| `QA_LLM_MODE` | `disabled` (default), `openai`, `groq`, `ollama` |
| `QA_LLM_API_KEY`, `QA_LLM_BASE_URL`, `QA_LLM_MODEL` | LLM connection |
| `QA_ALLOWED_HOSTS` | Targets the agent may test (loopback allowed by default) |

## 6. Docker (optional, after local verification)

```powershell
docker build -t autonomous-qa-agent .
docker run -p 8000:8000 autonomous-qa-agent
```

See the `Dockerfile` at the project root. Docker is intentionally kept out of
the MVP runtime path; it is packaged separately.

## 7. Architecture in one paragraph

`FastAPI` accepts a URL + goal → `BrowserExplorer` (Playwright) crawls the
authorized origin, collecting pages, interactive elements (ARIA roles, labels,
test IDs), console errors and failed network requests → `ScenarioGenerator`
produces deterministic test cases from templates (optionally augmented by an
LLM) → `PlanValidator` reviews them against discovered elements →
`TestExecutor` runs a fixed action vocabulary (navigate, click, fill,
assertions, …) with bounded timeouts, real assertions, and evidence capture
→ `FailureAnalyzer` classifies failures deterministically (application defect
vs. infrastructure) → `BugReporter` emits evidence-based bug reports with
deterministic severity → everything is persisted in SQLite and exposed through
the versioned REST API and dashboard.

## 8. Key limitations (honest, interview-friendly)

* Test execution is synchronous per run with a background task; no distributed
  job queue (by design for the MVP).
* LLM-assisted mode is optional; deterministic templates cover the demo
  workflows. Arbitrary natural-language goals are not perfectly supported —
  unsupported workflows are reported as such.
* Targets are restricted to localhost and explicitly configured hosts by
  default; never run against unauthorized applications.
* No CAPTCHA bypass, no access-control evasion, no arbitrary code execution
  (never evals LLM- or page-generated code).

## License

MIT — see `app/main.py` contact/license metadata. Demo app data is synthetic
and browser-local only.