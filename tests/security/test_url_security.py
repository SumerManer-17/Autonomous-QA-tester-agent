"""Security tests: unauthorized targets must be rejected before any browser starts."""

import pytest

from app.core.security import SecurityError, validate_target_url


ALLOWED = [
    "http://localhost:3000/",
    "http://127.0.0.1:8000/path?q=x",
    "http://[::1]/",
]

BLOCKED = [
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
    "http://172.16.254.1/",
    "http://192.168.1.1/",
    "http://evil.example.com/",
    "http://example.com/",
    "ftp://localhost/",
    "javascript:alert(1)",
    "data:text/html,<script>",
    "localhost:3000",
    "",
]


@pytest.mark.parametrize("url", ALLOWED)
def test_allowed_urls(url):
    if url:
        assert validate_target_url(url).startswith("http://")


@pytest.mark.parametrize("url", BLOCKED)
def test_blocked_urls(url):
    if url:
        with pytest.raises(SecurityError):
            validate_target_url(url)
