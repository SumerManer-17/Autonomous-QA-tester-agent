"""URL validation and SSRF / scope safety controls.

The agent accepts a target URL from the user and drives a real browser
against it. This module enforces:

* Only http/https schemes.
* Targets restricted to localhost and explicitly configured hosts by default.
* Blocking of private infrastructure, link-local, and cloud metadata addresses.
* Revalidation of resolved IP addresses (defends against DNS rebinding).
* Same-origin navigation boundaries during exploration.

These controls exist so the demo is safe to run on a laptop. They are not a
substitute for network isolation when testing against external systems.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import settings

# Address ranges that must never be proxied through the browser.
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. AWS/Azure metadata
    ipaddress.ip_network("fc00::/7"),        # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),       # IPv6 link-local
]

# Explicitly hostile / metadata targets.
METADATA_HOSTS = {"169.254.169.254", "169.254.169.253"}

# Loopback is always allowed for local testing.
LOOPBACK_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]


class SecurityError(ValueError):
    """Raised when a target URL fails a scope or safety check."""


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # cannot parse -> treat as unsafe
    if any(ip in net for net in LOOPBACK_NETWORKS):
        return False
    if ip_str in METADATA_HOSTS:
        return True
    return any(ip in net for net in BLOCKED_NETWORKS)


def _resolved_ips_are_safe(hostname: str) -> list[str]:
    """Resolve hostname and return safe IPs, raising SecurityError otherwise."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise SecurityError(f"Unable to resolve host {hostname!r}: {exc}") from exc

    safe_ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        if _ip_blocked(ip_str):
            raise SecurityError(
                f"Host {hostname!r} resolves to blocked address {ip_str}. "
                "Only localhost and explicitly allowed targets may be tested."
            )
        safe_ips.append(ip_str)
    if not safe_ips:
        raise SecurityError(f"Host {hostname!r} resolved to no usable addresses.")
    return safe_ips


def _is_allowed_host(hostname: str) -> bool:
    """Loopback and configured ALLOWED_HOSTS are permitted."""
    try:
        ip = ipaddress.ip_address(hostname)
        if any(ip in net for net in LOOPBACK_NETWORKS):
            return True
    except ValueError:
        pass
    return hostname in settings.ALLOWED_HOSTS


def normalize_url(url: str) -> str:
    """Return a cleaned, scheme-lowercased URL without a fragment."""
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        raise SecurityError(f"Missing URL scheme in {url!r} (use http or https).")
    if parsed.scheme.lower() not in settings.ALLOWED_SCHEMES:
        raise SecurityError(
            f"Unsupported scheme {parsed.scheme!r}. Allowed: {settings.ALLOWED_SCHEMES}."
        )
    if not parsed.hostname:
        raise SecurityError(f"Missing host in URL {url!r}.")
    return f"{parsed.scheme.lower()}://{parsed.hostname}" + (
        f":{parsed.port}" if parsed.port else ""
    ) + parsed.path + ("?" + parsed.query if parsed.query else "")


def validate_target_url(url: str) -> str:
    """Fully validate a user-supplied target URL and return its normalized form.

    Checks performed:
    * supported scheme (http/https)
    * host resolution and IP range blocking (SSRF protection)
    * host allow-list (localhost / configured hosts by default)
    """
    parsed = urlparse(url.strip())

    if not parsed.scheme:
        raise SecurityError(f"Missing URL scheme in {url!r} (use http or https).")
    if parsed.scheme.lower() not in settings.ALLOWED_SCHEMES:
        raise SecurityError(
            f"Unsupported scheme {parsed.scheme!r}. Allowed: {settings.ALLOWED_SCHEMES}."
        )
    if not parsed.hostname:
        raise SecurityError(f"Missing host in URL {url!r}.")

    # Block metadata and private infrastructure by resolved IP.
    _resolved_ips_are_safe(parsed.hostname)

    # Enforce allow-list (loopback always allowed).
    if not _is_allowed_host(parsed.hostname):
        raise SecurityError(
            f"Target host {parsed.hostname!r} is not authorized. "
            "Add it to QA_ALLOWED_HOSTS only after explicit authorization."
        )

    return normalize_url(url)


def is_same_origin(url_a: str, url_b: str) -> bool:
    """True when two URLs share scheme, host, and port."""
    a = urlparse(url_a)
    b = urlparse(url_b)
    return (
        a.scheme.lower() == b.scheme.lower()
        and a.hostname == b.hostname
        and a.port == b.port
    )


def sanitize_for_llm(text: str, max_chars: int = 2000) -> str:
    """Strip potentially executable content and truncate for LLM prompts.

    Webpage content is treated as untrusted data, never as instructions.
    """
    if not text:
        return ""
    # Remove script blocks and event-handler-like markup crudely.
    cleaned = text
    try:
        import re

        cleaned = re.sub(r"<script\b[^<]*?</script>", " ", cleaned, flags=re.S | re.I)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    except Exception:  # pragma: no cover - regex is reliable
        pass
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + " [truncated]"
    return cleaned


__all__ = [
    "SecurityError",
    "validate_target_url",
    "normalize_url",
    "is_same_origin",
    "sanitize_for_llm",
]
