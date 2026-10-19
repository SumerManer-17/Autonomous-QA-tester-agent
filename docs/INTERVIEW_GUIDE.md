# Interview Guide — Autonomous QA Testing Agent

Use this to explain and defend the project in QA Engineer, SDET, and QA
Automation interviews. It covers the story, key technical decisions, trade-offs,
limitations, and likely questions with answers.

## The elevator pitch

> "It's an autonomous QA agent: you point it at a web application and describe
> what to test in plain English. It explores the UI with Playwright, generates
> structured test cases, executes them with real assertions (not just clicks),
> classifies failures, captures screenshots and logs, and writes reproducible
> bug reports — all with a deterministic fallback when no LLM is configured."

## Project story (what to say in 2 minutes)

1. **Problem** — Writing and maintaining Selenium/Playwright tests is slow;
   assertions are often shallow ("click worked" ≠ "feature works"); triaging
   failures takes time.
2. **Solution** — An agent that closes the loop: exploration → test generation
   → execution → failure analysis → bug report → rerun after fix.
3. **Scope** — MVP built with FastAPI + Playwright + pytest + Pydantic +
   SQLite. Deliberately no message broker, no PostgreSQL, no microservices.
4. **Demo** — A local hotel-booking app with five toggleable injected defects;
   the agent detects them, files critical/high bug reports with evidence, and
   verifies the fix via rerun.

## Module map (where each responsibility lives)

| Responsibility | Module |
|----------------|--------|
| API + dashboard | `app/main.py`, `app/api/routes/`, `app/static/` |
| URL safety / SSRF controls | `app/core/security.py` |
| Browser exploration | `app/services/browser_explorer.py` |
| Test generation (deterministic + LLM) | `app/services/scenario_generator.py` |
| Plan validation | `app/services/plan_validator.py` |
| Test execution (action registry) | `app/services/test_executor.py` |
| Failure classification | `app/services/failure_analyzer.py` |
| Bug reports + severity + dedup | `app/services/bug_reporter.py` |
| Run orchestration | `app/services/run_pipeline.py` |
| SQLite repository layer | `app/repositories/` |
| Optional LLM provider | `app/services/llm_provider.py` |

## Key technical decisions to defend

### 1. Playwright over Selenium
Playwright bundles browser automation, screenshots, network interception,
console events, browser contexts, and traces in one framework — exactly what
this agent needs. Auto-waiting reduces flaky selectors; browser contexts give
per-test state isolation without full browser restarts.

### 2. Deterministic execution first, LLM optional
The LLM never decides pass/fail and never generates code. All test cases —
LLM-assisted or not — are validated with Pydantic against a limited action
vocabulary and executed by a fixed action registry. If the LLM is unavailable
or returns invalid JSON, deterministic templates take over. This is important
to state explicitly: **LLMs hallucinate selectors; this design never lets a
hallucinated selector reach the browser.**

### 3. Assertions, not just actions
`assert_visible`, `assert_text`, `assert_url`, `assert_count`, etc. are
first-class actions. A successful click is not treated as proof that a feature
works. This is the answer to "how do you know the test actually verified
something?"

### 4. Failure classification separates defect types
Not every failure is a product bug. Timeouts are split into network-related,
JS-error-related, and plain; `element_not_found` is weighed against whether
earlier steps on the same page passed. This prevents labeling every timeout as
an application bug — a common trap in automated triage.

### 5. SQLite, not a distributed stack
One file, WAL mode, repository layer. The MVP genuinely doesn't need a message
broker; background execution is handled by FastAPI background tasks. Complexity
is added only when required — a defensible YAGNI call.

### 6. Stable locators, no absolute XPath
Elements are resolved by `data-testid`, then ARIA role + accessible name,
then label/placeholder/text. An explicit `index` handles repeated elements
("Select room" appears three times). Absolute XPath is avoided because it breaks
on the slightest DOM change.

### 7. Safety / SSRF controls
Targets default to localhost and configured hosts. Private IP ranges, link-local
addresses, and cloud metadata endpoints are blocked; every navigation is
re-validated and must stay same-origin. Credentials are never sent to the LLM.
This matters if an interviewer asks "what happens if I point this at my
company's production or at an AWS metadata endpoint?"

## Sample Q&A

### Q: How is this different from record-and-playback?
A: Record-and-playback replays clicks and asserts little. This agent generates
test cases from a natural-language goal *and* discovered UI, asserts expected
outcomes, classifies failures, writes bug reports, and supports reruns after
fixes — with deterministic templates so behavior doesn't depend on an LLM's
mood.

### Q: How do you handle a test that clicks "Submit" and the click succeeds but nothing happens?
A: The executor would continue to the next assertion step (e.g. `assert_visible`
on the confirmation element). That assertion fails, the failure is classified
as `application_assertion_failure` with high confidence, and a bug report is
generated with the screenshot showing no confirmation — exactly the "Submit
appears to work but fails to show confirmation" injected defect in the demo.

### Q: How do you know a timeout is a product bug and not a slow CI runner?
A: It isn't automatically labeled one. The analyzer checks surrounding
evidence: failed network requests → infrastructure/network; JavaScript errors
on the page → likely application defect; neither → `inconclusive` with a
recommendation to retry with a longer timeout and capture a trace.

### Q: What if the LLM generates a selector that doesn't exist?
A: It never reaches the browser unchecked. The plan validator compares generated
targets against discovered elements and warns or rejects; the executor fails
clearly with `element_not_found` / `element_ambiguous` rather than silently
clicking the wrong thing. Deterministic templates cover the core flows without
any LLM involvement.

### Q: Can I point this at any website?
A: No — by design. Defaults allow only localhost and configured hosts; private
ranges, link-local, and metadata endpoints are blocked. External testing
requires explicit authorization via `QA_ALLOWED_HOSTS`. The tool must not be
used for access-control evasion or unauthorized testing.

### Q: What are the limitations?
A: (1) Synchronous per-run execution with a background task — no distributed
job queue yet. (2) LLM mode is optional; arbitrary natural-language goals
aren't perfectly supported — unsupported workflows are explicitly reported.
(3) UI flows are covered by deterministic templates for the demo app; new
applications may need template additions. (4) No CAPTCHA handling, no
authentication against real systems with secrets.

### Q: How would you scale this?
A: Replace the background task with a lightweight job queue (Redis/RQ or
Celery), move SQLite to PostgreSQL if concurrency demands it, add browser
pools/grid for parallel execution, add a secrets policy for external targets,
and add authentication to the API. Only when the MVP genuinely requires it.

## Demo cheat sheet (live)

```powershell
# 1. Start demo (defects off)
python demo-app/server.py 3000

# 2. Start agent
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Run
curl.exe -sS -X POST http://127.0.0.1:8000/api/v1/runs -H "Content-Type: application/json" -d '{"target_url":"http://localhost:3000","goal":"Verify that a user can register, log in, search for a hotel, select a room, and complete the booking form. Check input validation and error handling."}'

# 4. Poll GET /api/v1/runs/<id> until completed
# 5. GET /api/v1/runs/<id>/bugs  → see the critical bug report
# 6. Toggle a defect: POST http://localhost:3000/__demo/defects
# 7. POST /api/v1/tests/<test_id>/rerun → verify the fix
```

## Technology summary for résumé talk

Python 3.12, FastAPI, Pydantic v2, Playwright (Chromium), pytest, SQLite,
REST API design, SSRF/safe-by-default design, deterministic + LLM-optional
test generation, evidence-based bug reporting, Docker-ready.
