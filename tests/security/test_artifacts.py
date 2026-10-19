"""Security tests: artifact retrieval must not escape the artifacts directory."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("path", ["../../../etc/passwd", "..\\..\\..\\windows\\win.ini", "../outside.txt"])
def test_path_traversal_blocked(path):
    resp = client.get(f"/api/v1/artifacts/{path}")
    # Traversal must never disclose a file outside the artifacts dir;
    # the path is either rejected (400) or resolves to a missing file (404).
    assert resp.status_code != 200, f"{path!r} should not be served, got {resp.status_code}"
