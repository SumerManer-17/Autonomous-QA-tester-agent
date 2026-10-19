"""SQLite persistence layer.

All tables live in a single SQLite file. Connections are opened per operation
with `check_same_thread=False` guarded by a lock so background test runs and
API requests can share the database safely.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Optional

from app.core.config import settings

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    target_url TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    llm_mode TEXT NOT NULL DEFAULT 'disabled',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS discovered_pages (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    depth INTEGER DEFAULT 0,
    screenshot_path TEXT,
    console_errors TEXT,
    network_errors TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS discovered_elements (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL,
    role TEXT,
    name TEXT,
    label TEXT,
    placeholder TEXT,
    test_id TEXT,
    url TEXT,
    selector TEXT,
    FOREIGN KEY (page_id) REFERENCES discovered_pages (id)
);

CREATE TABLE IF NOT EXISTS test_cases (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT,
    generation_mode TEXT NOT NULL,
    priority TEXT,
    risk_level TEXT,
    preconditions TEXT,
    steps TEXT,
    target_elements TEXT,
    test_data TEXT,
    expected_outcome TEXT,
    required_assertions TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS test_results (
    id TEXT PRIMARY KEY,
    test_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    failure_category TEXT,
    confidence TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    screenshot_path TEXT,
    console_errors TEXT,
    network_errors TEXT,
    logs TEXT,
    FOREIGN KEY (test_id) REFERENCES test_cases (id),
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS step_results (
    id TEXT PRIMARY KEY,
    test_result_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    action TEXT,
    target TEXT,
    status TEXT,
    error TEXT,
    duration_ms INTEGER,
    screenshot_path TEXT,
    FOREIGN KEY (test_result_id) REFERENCES test_results (id)
);

CREATE TABLE IF NOT EXISTS bug_reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT,
    priority TEXT,
    environment TEXT,
    browser TEXT,
    browser_version TEXT,
    target_url TEXT,
    reproduction_steps TEXT,
    preconditions TEXT,
    test_data TEXT,
    expected_result TEXT,
    actual_result TEXT,
    failure_category TEXT,
    timestamp TEXT NOT NULL,
    screenshot_path TEXT,
    console_errors TEXT,
    network_requests TEXT,
    execution_logs TEXT,
    probable_cause TEXT,
    confidence TEXT,
    limitations TEXT,
    dedup_key TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (id),
    FOREIGN KEY (test_id) REFERENCES test_cases (id)
);

CREATE TABLE IF NOT EXISTS rerun_history (
    id TEXT PRIMARY KEY,
    original_test_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    test_result_id TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    reason TEXT,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    path TEXT NOT NULL,
    url TEXT NOT NULL,
    size_bytes INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_test_cases_run ON test_cases(run_id);
CREATE INDEX IF NOT EXISTS idx_test_results_test ON test_results(test_id);
CREATE INDEX IF NOT EXISTS idx_test_results_run ON test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_bugs_run ON bug_reports(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
"""


_lock = threading.Lock()


def _connect(database_url: Optional[str] = None) -> sqlite3.Connection:
    url = database_url or settings.DATABASE_URL
    os.makedirs(os.path.dirname(os.path.abspath(url)), exist_ok=True)
    conn = sqlite3.connect(url, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(database_url: Optional[str] = None) -> None:
    """Create all tables if they do not exist. Safe to call on every start."""
    conn = _connect(database_url)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def execute(query: str, parameters=(), database_url: Optional[str] = None) -> sqlite3.Cursor:
    with _lock:
        conn = _connect(database_url)
        try:
            cur = conn.execute(query, parameters)
            conn.commit()
            return cur
        finally:
            conn.close()


def query_all(query: str, parameters=(), database_url: Optional[str] = None) -> list[sqlite3.Row]:
    with _lock:
        conn = _connect(database_url)
        try:
            cur = conn.execute(query, parameters)
            return cur.fetchall()
        finally:
            conn.close()


def query_one(query: str, parameters=(), database_url: Optional[str] = None) -> sqlite3.Row | None:
    with _lock:
        conn = _connect(database_url)
        try:
            cur = conn.execute(query, parameters)
            return cur.fetchone()
        finally:
            conn.close()
