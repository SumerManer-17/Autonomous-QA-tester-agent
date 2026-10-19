"""Integration tests for the FastAPI HTTP layer (no LLM key required)."""

import pytest
from fastapi.testclient import TestClient

GOAL = (
    "Verify that a user can register, log in, search for a hotel, select a room, "
    "and complete the booking form. Check input validation and error handling."
)


class TestHealth:
    def test_health(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body


class TestRunValidation:
    def test_unauthorized_host_rejected(self, api_client):
        resp = api_client.post(
            "/api/v1/runs",
            json={"target_url": "http://evil.example.com/", "goal": "check it"},
        )
        assert resp.status_code == 400

    def test_metadata_endpoint_rejected(self, api_client):
        resp = api_client.post(
            "/api/v1/runs",
            json={"target_url": "http://169.254.169.254/", "goal": "check it"},
        )
        assert resp.status_code == 400

    def test_missing_goal_rejected(self, api_client):
        resp = api_client.post(
            "/api/v1/runs",
            json={"target_url": "http://localhost:3000/"},
        )
        assert resp.status_code == 422


class TestRunLifecycle:
    @pytest.mark.asyncio
    async def test_create_and_get_run(self, api_client, run_pipeline, no_defects):
        resp = api_client.post(
            "/api/v1/runs",
            json={
                "target_url": "http://localhost:3000/",
                "goal": "Check the home page loads.",
                "llm_mode": "disabled",
            },
        )
        assert resp.status_code == 201, resp.text
        run = resp.json()
        assert run["status"] == "pending"
        assert run["id"].startswith("run_")

        # Drive the pipeline to completion so retrieval has data.
        await run_pipeline.execute_run(run["id"], "http://localhost:3000/", "Check the home page loads.", "disabled")

        get_resp = api_client.get(f"/api/v1/runs/{run['id']}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == run["id"]
        assert get_resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_runs(self, api_client, run_pipeline, no_defects):
        await run_pipeline.execute_run(
            "r_list", "http://localhost:3000/", "Check the home page loads.", "disabled"
        )
        resp = api_client.get("/api/v1/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent_run(self, api_client):
        resp = api_client.get("/api/v1/runs/does_not_exist")
        assert resp.status_code == 404


class TestRerunEndpoint:
    @pytest.mark.asyncio
    async def test_rerun_creates_pending_result(
        self, api_client, run_pipeline, no_defects
    ):
        await run_pipeline.execute_run(
            "r_api", "http://localhost:3000/", "Check home page.", "disabled"
        )
        from app.repositories import test_repository

        cases = test_repository.list_test_cases_for_run("r_api")
        assert cases, "pipeline should have generated test cases"
        test_id = cases[0]["id"]

        resp = api_client.post(f"/api/v1/tests/{test_id}/rerun", json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["result_id"].startswith("result_")

    def test_rerun_nonexistent_test(self, api_client):
        resp = api_client.post("/api/v1/tests/test_does_not_exist/rerun", json={})
        assert resp.status_code == 404


class TestBugAndArtifactsEndpoints:
    @pytest.mark.asyncio
    async def test_get_run_bugs(self, api_client, run_pipeline, no_defects):
        await run_pipeline.execute_run(
            "r_bug", "http://localhost:3000/", "Check the home page loads.", "disabled"
        )
        resp = api_client.get("/api/v1/runs/r_bug/bugs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_artifacts_served_for_failed_run(
        self, api_client, run_pipeline, invalid_email_defect
    ):
        await run_pipeline.execute_run(
            "r_art", "http://localhost:3000/", GOAL, "disabled"
        )
        artifacts = api_client.get("/api/v1/runs/r_art/artifacts")
        assert artifacts.status_code == 200
        artifact_list = artifacts.json()
        assert len(artifact_list) >= 1, "a failed run must produce screenshot artifacts"
        first = artifact_list[0]
        # url is like /artifacts/screenshots/<file>
        resp = api_client.get(first["url"])
        assert resp.status_code == 200, first
        assert resp.headers["content-type"].startswith("image/")

    def test_artifact_path_traversal_blocked(self, api_client):
        # Traversal must never disclose a file outside the artifacts dir;
        # the path is either rejected (400) or resolves to a missing file (404).
        resp = api_client.get("/api/v1/artifacts/../../../etc/passwd")
        assert resp.status_code != 200

    def test_get_nonexistent_bug(self, api_client):
        resp = api_client.get("/api/v1/bugs/bug_does_not_exist")
        assert resp.status_code == 404
