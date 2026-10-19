# Architecture — Autonomous QA Testing Agent

## Design goals

1. **Deterministic first.** Everything works without an LLM. The LLM is an
   optional assistant, never the source of truth for whether a test passed.
2. **Separation of concerns.** Exploration, generation, validation, execution,
   analysis, reporting, and persistence live in separate modules.
3. **Safe by default.** Targets are restricted to localhost and explicitly
   configured hosts; private IP ranges and cloud metadata endpoints are blocked;
   navigation is confined to the authorized origin.
4. **Evidence-based.** A failure is never called an application bug without
   execution evidence; timeouts are not automatically labeled as defects.

## Pipeline

```
User input
  → FastAPI (versioned REST API)
  → URL validation & safety checks (core/security.py)
  → Browser Explorer (services/browser_explorer.py, Playwright)
  → Test Scenario Generator (services/scenario_generator.py)
  → Test Plan Validator (services/plan_validator.py)
  → Playwright Test Executor (services/test_executor.py)
  → Failure Analyzer (services/failure_analyzer.py)
  → Bug Report Generator (services/bug_reporter.py)
  → SQLite persistence (repositories/) + Dashboard (app/static/)
```

### Browser Explorer

Launches Playwright Chromium, crawls the target origin within `MAX_CRAWL_PAGES`
and `MAX_CRAWL_DEPTH`, and records per page: title, final URL, screenshot,
visible interactive elements (links, buttons, textboxes, selects, checkboxes,
radios, `[data-testid]`), ARIA roles / accessible names / labels /
placeholders, console errors, and failed network requests. It follows `<a>`
links and GET `<form>` actions only; it never submits forms during exploration.

### Test Scenario Generator

Two modes:

* **Deterministic** — predefined templates (registration, login, search, room
  selection, booking, input validation) resolved against discovered elements.
  Targets use stable locators: `data-testid` > ARIA role+name > label >
  placeholder > text. An explicit `index` supports identical elements (e.g.
  "Select room" × 3).
* **LLM-assisted** — asks the configured LLM for additional cases grounded in
  the *sanitized* discovered UI. Output is validated with Pydantic; invalid
  cases are skipped; total failure falls back to deterministic mode.

### Test Plan Validator

Rejects unknown action types, missing values/targets, and malformed steps;
warns about targets not found on any explored page. Rejected cases are never
executed.

### Test Executor

A fixed action registry (`ACTION_REGISTRY`) dispatches 13 actions:
`navigate`, `click`, `fill`, `select_option`, `check`, `uncheck`,
`assert_visible`, `assert_text`, `assert_url`, `assert_enabled`,
`assert_disabled`, `assert_count`, `assert_attribute`.

Every action validates arguments, resolves the target via stable strategies
(`data-testid` first, then `get_by_role` with exact-name disambiguation),
uses bounded timeouts, records per-step results, and captures a screenshot on
failure. Every `navigate` re-validates the URL and refuses cross-origin
navigation. **No** `page.evaluate`, arbitrary JavaScript, shell execution, or
LLM-generated code is ever run.

Each test case runs in its own browser context for state isolation.

### Failure Analyzer

Deterministic classification into categories:
`application_assertion_failure`, `element_not_found`, `element_ambiguous`,
`navigation_failure`, `application_http_error`, `javascript_console_error`,
`failed_network_request`, `timeout`, `test_setup_failure`,
`browser_infrastructure_failure`, `inconclusive`.

Key judgments:
* A timeout with JS errors on the page → likely application defect.
* A timeout with failed network requests → likely infrastructure/network.
* A plain timeout → inconclusive; retry with a longer timeout.
* `element_not_found` after earlier steps passed → likely UI regression;
  otherwise likely a stale selector (test issue, not a defect).

The LLM may rephrase observed/probable-cause text but cannot change the
category, confidence, or invent facts.

### Bug Reporter

Creates a report only when a failure has evidence and is classified as a
probable application defect. Severity is deterministic (auth flows → critical,
booking → high, search/validation → medium, selector/setup issues → low); an
LLM may recommend but the rules decide. Reports include reproduction steps,
expected vs. actual result, evidence (screenshot, console, network, logs),
probable cause, confidence score, and limitations. Duplicate failures across
reruns are deduplicated by `category:slug(title)` and attached to the existing
report; rerun history is preserved.

### Persistence

Single SQLite file (`data/qa_agent.db` by default, WAL mode). Tables: runs,
discovered_pages, discovered_elements, test_cases, test_results, step_results,
bug_reports, rerun_history, artifacts. Repository layer hides SQL; the API and
pipeline share it. Restarting the backend preserves history.

### Dashboard

One-page HTML/JS at `/dashboard`: start a run (URL + goal), poll status,
summary counts, test list with latest results, step-by-step evidence with
screenshots, bug-report detail with severity/priority, and per-test rerun.

## Security controls

* Only `http`/`https` schemes; host allow-list (loopback always allowed).
* DNS resolution + IP-range blocking (RFC1918, link-local, IPv6 ULA, cloud
  metadata `169.254.169.254`).
* Same-origin enforcement on every navigation.
* Page content sanitized before any LLM prompt; secrets stripped from test
  data in reports.
* Artifact retrieval path-traversal guarded.
* Browser/backend bound to `127.0.0.1` by default.

## What is intentionally NOT in the MVP

Distributed job queue (Celery/RQ), PostgreSQL/Redis, Kubernetes/microservices,
CAPTCHA bypass, access-control evasion, testing of unauthorized targets,
LLM-generated code execution.
