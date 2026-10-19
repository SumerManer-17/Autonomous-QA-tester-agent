/* Autonomous QA Testing Agent - dashboard UI */
(function () {
  "use strict";

  const BASE = "";
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const urlInput = $("#target-url");
  const goalInput = $("#testing-goal");
  const startBtn = $("#start-run");
  const runView = $("#run-view");
  const statusText = $("#run-status");
  const summaryBox = $("#summary");
  const testsBody = $("#tests-body");
  const bugsBody = $("#bugs-body");
  const testDetail = $("#test-detail");
  const bugDetail = $("#bug-detail");

  let currentRunId = null;
  let pollTimer = null;

  function escapeHtml(unsafe) {
    if (!unsafe) return "";
    return String(unsafe)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function badgeFor(status) {
    const cls = (status || "pending").toLowerCase();
    return `<span class="badge ${cls}">${escapeHtml(status || "pending")}</span>`;
  }

  function setStatus(text, kind) {
    statusText.textContent = text;
    statusText.className = "status-" + (kind || "info");
  }

  function show(section) {
    $$(".panel").forEach((el) => el.classList.add("hidden"));
    section.classList.remove("hidden");
  }

  function api(path) {
    return `/api/v1${path}`;
  }

  async function fetchJson(path, options = {}) {
    const res = await fetch(api(path), {
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(`${res.status} ${detail}`);
    }
    return res.json();
  }

  // ------------------------------------------------------------------ //
  // START RUN
  // ------------------------------------------------------------------ //
  async function startRun() {
    const targetUrl = urlInput.value.trim();
    const goal = goalInput.value.trim();
    if (!targetUrl || !goal) {
      alert("Please enter both a target URL and a testing goal.");
      return;
    }

    startBtn.disabled = true;
    startBtn.innerHTML = '<span class="spinner"></span>Starting run...';
    try {
      const run = await fetchJson("/runs", {
        method: "POST",
        body: JSON.stringify({ target_url: targetUrl, goal, llm_mode: "disabled" }),
      });
      currentRunId = run.id;
      show(runView);
      summaryBox.innerHTML = "";
      testsBody.innerHTML = '<tr><td colspan="4">Run started &mdash; exploring and generating tests...</td></tr>';
      bugsBody.innerHTML = "";
      testDetail.classList.add("hidden");
      bugDetail.classList.add("hidden");
      setStatus("Run " + currentRunId + " started", "info");
      pollRun();
    } catch (err) {
      alert("Failed to start run: " + err.message);
      startBtn.disabled = false;
      startBtn.textContent = "Start test run";
    }
  }

  // ------------------------------------------------------------------ #
  # POLL RUN
  // ------------------------------------------------------------------ #
  async function pollRun() {
    if (!currentRunId) return;
    try {
      const run = await fetchJson(`/runs/${currentRunId}`);
      setStatus("Status: " + run.status, run.status === "completed" ? "success" : "info");

      if (run.status === "pending" || run.status === "running") {
        pollTimer = setTimeout(pollRun, 2000);
        return;
      }

      // Completed / failed
      clearTimeout(pollTimer);
      pollTimer = null;
      startBtn.disabled = false;
      startBtn.textContent = "Start test run";

      const summary = run.summary || {};
      summaryBox.innerHTML = `
        <div class="stat"><div class="value pass">${summary.passed ?? 0}</div><div class="label">Passed</div></div>
        <div class="stat"><div class="value fail">${summary.failed ?? 0}</div><div class="label">Failed</div></div>
        <div class="stat"><div class="value">${summary.skipped ?? 0}</div><div class="label">Skipped</div></div>
        <div class="stat"><div class="value">${summary.inconclusive ?? 0}</div><div class="label">Inconclusive</div></div>
        <div class="stat"><div class="value">${summary.total ?? 0}</div><div class="label">Total</div></div>
      `;
      await loadTests(currentRunId);
      await loadBugs(currentRunId);
    } catch (err) {
      setStatus("Error polling run: " + err.message, "danger");
    }
  }

  async function loadTests(runId) {
    const tests = await fetchJson(`/runs/${runId}/tests`);
    testsBody.innerHTML = "";
    if (!tests.length) {
      testsBody.innerHTML = '<tr><td colspan="4">No test cases.</td></tr>';
      return;
    }
    for (const t of tests) {
      const result = t.latest_result || {};
      const status = result.status || "not executed";
      const cat = result.failure_category ? ` <span class="note">(${result.failure_category.replace(/_/g, " ")})</span>` : "";
      const row = document.createElement("tr");
      row.innerHTML = `
        <td><strong>${escapeHtml(t.title)}</strong>${cat}</td>
        <td>${badgeFor(status)}</td>
        <td class="note">${escapeHtml(result.error_message || "&mdash;")}</td>
        <td>
          <button class="small secondary" onclick="app.viewTest('${t.id}')">Detail</button>
          ${status === "failed" ? `<button class="small danger" onclick="app.rerunTest('${t.id}')">Rerun</button>` : ""}
        </td>
      `;
      testsBody.appendChild(row);
    }
  }

  async function loadBugs(runId) {
    const bugs = await fetchJson(`/runs/${runId}/bugs`);
    bugsBody.innerHTML = "";
    if (!bugs.length) {
      bugsBody.innerHTML = '<div class="note">No bug reports generated.</div>';
      return;
    }
    for (const b of bugs) {
      const el = document.createElement("div");
      el.className = "detail";
      el.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <strong>${escapeHtml(b.title)}</strong>
          <span class="badge ${b.severity} sev-${b.severity}">${escapeHtml(b.severity)}</span>
          <span class="badge">${escapeHtml(b.priority)}</span>
        </div>
        <div class="note">Test ${escapeHtml(b.test_id)} &middot; ${escapeHtml(b.failure_category.replace(/_/g, " "))} &middot; confidence ${escapeHtml(b.confidence || "&mdash;")}</div>
        <div class="pre" style="max-height:140px;">${escapeHtml(b.actual_result || "")}</div>
        <div style="margin-top:8px;">
          <button class="small secondary" onclick="app.viewBug('${b.id}')">View report</button>
          ${b.screenshot_path ? `<img src="${escapeHtml("/" + String(b.screenshot_path).split("\\").join("/"))}" class="img-wrap" style="margin-top:8px;" alt="evidence">` : ""}
        </div>
      `;
      bugsBody.appendChild(el);
    }
  }

  // ------------------------------------------------------------------ #
  # TEST DETAIL / RERUN
  // ------------------------------------------------------------------ #
  window.app = {
    async viewTest(testId) {
      const data = await fetchJson(`/tests/${testId}`);
      testDetail.classList.remove("hidden");
      const tc = data.test_case;
      const result = data.result || {};
      const stepsHtml = (data.steps || []).map((s, i) => {
        const cls = s.status === "passed" ? "pass" : s.status === "failed" ? "fail" : "";
        return `
          <div class="step ${cls}">
            <strong>Step ${s.step_index + 1} - ${escapeHtml(s.action)}</strong>
            ${s.target ? ` target: ${escapeHtml(JSON.stringify(s.target))}` : ""}
            ${s.value !== undefined ? ` value: ${escapeHtml(String(s.value))}` : ""}
            ${s.status ? ` status: ${s.status}` : ""}
            ${s.error ? `<div class="note" style="color:var(--danger);">error: ${escapeHtml(s.error)}</div>` : ""}
            ${s.screenshot_path ? `<img src="${escapeHtml("/" + String(s.screenshot_path).split("\\").join("/"))}" class="img-wrap" style="margin-top:6px;">` : ""}
          </div>`;
      }).join("");
      testDetail.innerHTML = `
        <h2 style="margin-top:0;">${escapeHtml(tc.title)}</h2>
        <div class="note">${escapeHtml(tc.objective)}</div>
        <div class="note">Expected: ${escapeHtml(tc.expected_outcome)}</div>
        <h3>Result</h3>
        <div class="pre">${escapeHtml(JSON.stringify(result, null, 2) || "No result yet")}</div>
        <h3>Steps</h3>${stepsHtml}
        ${result.status === "failed" ? `<button class="danger small" onclick="app.rerunTest('${testId}')">Rerun this test</button>` : ""}
      `;
      bugDetail.classList.add("hidden");
    },

    async viewBug(bugId) {
      const b = await fetchJson(`/bugs/${bugId}`);
      bugDetail.classList.remove("hidden");
      bugDetail.innerHTML = `
        <h2 style="margin-top:0;">${escapeHtml(b.title)}</h2>
        <div class="note">Bug ${escapeHtml(b.id)} &middot; run ${escapeHtml(b.run_id)} &middot; test ${escapeHtml(b.test_id)}</div>
        <div style="display:flex;gap:12px;margin-bottom:12px;">
          <span class="badge sev-${b.severity}">${escapeHtml(b.severity)}</span>
          <span class="badge">${escapeHtml(b.priority)}</span>
          <span class="badge">${escapeHtml(b.failure_category.replace(/_/g, " "))}</span>
          <span class="badge">confidence ${escapeHtml(b.confidence || "&mdash;")}</span>
        </div>
        <h3>Reproduction steps</h3>
        <div class="pre">${escapeHtml((b.reproduction_steps || []).join("\n"))}</div>
        <h3>Expected result</h3><div class="pre">${escapeHtml(b.expected_result || "")}</div>
        <h3>Actual result</h3><div class="pre">${escapeHtml(b.actual_result || "")}</div>
        <h3>Probable cause</h3><div class="pre">${escapeHtml(b.probable_cause || "")}</div>
        <h3>Limitations</h3><div class="pre">${escapeHtml(b.limitations || "")}</div>
        ${b.screenshot_path ? `<h3>Evidence</h3><img src="${escapeHtml("/" + String(b.screenshot_path).split("\\").join("/"))}" class="img-wrap">` : ""}
        <h3>Console errors</h3><div class="pre">${escapeHtml((b.console_errors || []).join("\n") || "none")}</div>
        <h3>Failed network requests</h3><div class="pre">${escapeHtml((b.network_requests || []).join("\n") || "none")}</div>
        <button class="danger small" onclick="app.rerunTest('${b.test_id}')">Rerun test after fix</button>
      `;
      testDetail.classList.add("hidden");
    },

    async rerunTest(testId) {
      try {
        const resp = await fetchJson(`/tests/${testId}/rerun`, { method: "POST" });
        alert("Rerun started (result " + resp.result_id + "). Refresh to see updated results.");
      } catch (err) {
        alert("Rerun failed: " + err.message);
      }
    },
  };

  startBtn.addEventListener("click", startRun);

  // Defaults
  urlInput.value = "http://localhost:3000";
  goalInput.value =
    "Verify that a user can register, log in, search for a hotel, select a room, and complete the booking form. Check input validation and error handling.";
})();
