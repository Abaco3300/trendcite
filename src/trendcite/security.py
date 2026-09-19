"""Security utilities: secret redaction, untrusted-text sanitisation and URL safety.

Everything TrendCite retrieves from the web is *untrusted data*. These helpers make
sure that data is bounded in size, stripped of control characters and markup, never
confused with instructions, and never allowed to smuggle credentials into logs.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"

# Patterns for common credential formats. Ordered from most to least specific so
# that specific token shapes are replaced before generic key=value matching.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),  # Anthropic
    re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub classic tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),  # GitHub fine-grained tokens
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),  # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),  # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]{16,}=*"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key|auth)"
        r"(\s*[:=]\s*)(['\"]?)[^\s'\"&]{8,}\3"
    ),
)

# Environment variables whose *values* must never appear in output or logs.
SENSITIVE_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "GITHUB_TOKEN",
    "X_BEARER_TOKEN",
)


def redact(text: str) -> str:
    """Replace credential-shaped substrings and known secret env values with a marker."""
    if not text:
        return text
    out = text
    for name in SENSITIVE_ENV_VARS:
        value = os.environ.get(name)
        if value and len(value) >= 8:
            out = out.replace(value, REDACTED)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
        else:
            out = pattern.sub(REDACTED, out)
    return out


class RedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from every record before it is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive against bad format args
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        return True


def configure_logging(verbose: bool = False) -> None:
    """Configure the ``trendcite`` logger to stderr with secret redaction."""
    logger = logging.getLogger("trendcite")
    if any(isinstance(f, RedactingFilter) for h in logger.handlers for f in h.filters):
        logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
        return
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("trendcite %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logger.propagate = False


# --------------------------------------------------------------------------------------
# Untrusted text handling
# --------------------------------------------------------------------------------------

MAX_TITLE_CHARS = 300
MAX_EXCERPT_CHARS = 1200

_TAG_RE = re.compile(r"<[^>]{0,2000}>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_WS_RE = re.compile(r"\s+")

# Heuristic signals that source text is trying to address an AI system. Matching text
# is *flagged* for the reader; it is never obeyed and never removed (removal would
# destroy evidence).
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)ignore (all |any )?(previous|prior|above) (instructions|prompts?)"),
    re.compile(r"(?i)disregard (the |all |your )?(system|previous|prior) (prompt|instructions)"),
    re.compile(r"(?i)\byou are now\b"),
    re.compile(r"(?i)\bsystem prompt\b"),
    re.compile(r"(?i)(reveal|print|output|send) (your |the )?(api key|secret|password|token)"),
    re.compile(r"(?i)</?(system|assistant|untrusted_evidence|instructions?)>"),
    re.compile(r"(?i)\b(run|execute) (this|the following) (command|code|script)\b"),
    re.compile(r"(?i)\b(rm -rf|curl [^ ]+ \| ?(ba)?sh|powershell -enc)"),
)


def clean_text(value: object, limit: int) -> str:
    """Normalise untrusted text: unescape entities, strip tags/control chars, bound length."""
    if value is None:
        return ""
    text = str(value)[: limit * 8]  # bound work before regex processing
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)  # double-encoded feeds are common
    text = _CONTROL_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def injection_flags(text: str) -> list[str]:
    """Return a list of heuristic flags if the text looks like it addresses an AI system."""
    if any(p.search(text) for p in _INJECTION_PATTERNS):
        return ["possible_prompt_injection"]
    return []


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|#!])")


def md_escape(text: str) -> str:
    """Escape Markdown/HTML-significant characters so untrusted text renders inertly."""
    return _MD_SPECIAL.sub(r"\\\1", text)


# --------------------------------------------------------------------------------------
# URL safety
# --------------------------------------------------------------------------------------

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src", "si"}


class UnsafeURLError(ValueError):
    """Raised when a URL is not permitted for fetching or display."""


def _host_is_private(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        return True
    if lowered.endswith((".internal", ".local")):
        return True
    try:
        ip = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def canonicalize_url(url: str) -> str:
    """Return a canonical http(s) URL or raise :class:`UnsafeURLError`.

    Canonicalisation lowercases scheme/host, strips credentials, default ports,
    fragments and common tracking parameters, and sorts nothing else so the
    original resource identity is preserved.
    """
    raw = (url or "").strip()
    if not raw or len(raw) > 2048:
        raise UnsafeURLError("empty or overlong URL")
    if _CONTROL_RE.search(raw) or any(c.isspace() for c in raw):
        raise UnsafeURLError("URL contains whitespace or control characters")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError(f"scheme not allowed: {scheme or '(none)'}")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    port = parts.port
    netloc = host if ":" not in host else f"[{host}]"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
        ]
    )
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def ensure_fetchable(url: str) -> str:
    """Canonicalise a URL and refuse obviously internal destinations (basic SSRF guard).

    Note: this checks literal hosts/IPs only; it does not resolve DNS. TrendCite
    only fetches URLs from its own configuration, never URLs found inside content.
    """
    canonical = canonicalize_url(url)
    host = urlsplit(canonical).hostname or ""
    if _host_is_private(host):
        raise UnsafeURLError(f"refusing to fetch private/internal host: {host}")
    return canonical


def safe_display_url(url: str) -> str | None:
    """Canonical URL suitable for display in reports, or ``None`` if unsafe."""
    try:
        return canonicalize_url(url)
    except UnsafeURLError:
        return None
