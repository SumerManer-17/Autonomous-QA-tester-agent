"""Unit tests for URL validation and SSRF/scope controls."""

import pytest

from app.core.security import SecurityError, is_same_origin, sanitize_for_llm, validate_target_url


class TestValidateTargetUrl:
    def test_allows_localhost(self):
        assert validate_target_url("http://localhost:3000/") == "http://localhost:3000/"

    def test_allows_loopback_address(self):
        assert validate_target_url("http://127.0.0.1:8000/path?q=1") == "http://127.0.0.1:8000/path?q=1"

    def test_rejects_missing_scheme(self):
        with pytest.raises(SecurityError):
            validate_target_url("localhost:3000/")

    def test_rejects_unsupported_scheme(self):
        with pytest.raises(SecurityError):
            validate_target_url("ftp://localhost/")
        with pytest.raises(SecurityError):
            validate_target_url("javascript:alert(1)")

    def test_rejects_missing_host(self):
        with pytest.raises(SecurityError):
            validate_target_url("http:///path")

    def test_rejects_unauthorized_host(self):
        with pytest.raises(SecurityError):
            validate_target_url("http://evil.example.com/")

    def test_rejects_cloud_metadata(self):
        with pytest.raises(SecurityError):
            validate_target_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_private_ranges(self):
        with pytest.raises(SecurityError):
            validate_target_url("http://10.0.0.1/")
        with pytest.raises(SecurityError):
            validate_target_url("http://172.16.0.1/")
        with pytest.raises(SecurityError):
            validate_target_url("http://192.168.1.1/")

    def test_rejects_link_local(self):
        with pytest.raises(SecurityError):
            validate_target_url("http://169.254.0.1/")


class TestIsSameOrigin:
    def test_true_for_matching(self):
        assert is_same_origin("http://localhost:3000/a", "http://localhost:3000/b") is True

    def test_false_for_different_port(self):
        assert is_same_origin("http://localhost:3000/a", "http://localhost:3001/b") is False

    def test_false_for_different_host(self):
        assert is_same_origin("http://localhost:3000/a", "http://127.0.0.1:3000/b") is False


class TestSanitizeForLLM:
    def test_strips_script_tags(self):
        dirty = "<script>alert(1)</script><input>hello</input>"
        assert "<script>" not in sanitize_for_llm(dirty)
        assert "alert" not in sanitize_for_llm(dirty)

    def test_truncates(self):
        long_text = "x" * 5000
        out = sanitize_for_llm(long_text)
        assert len(out) <= 2000 + len(" [truncated]")
        assert out.endswith(" [truncated]")

    def test_collapses_whitespace(self):
        assert sanitize_for_llm("a   \n\n  b") == "a b"
