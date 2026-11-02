"""Production hardening for the HTTP surface: authentication, rate limiting, security headers, CORS.

Everything is configured from the environment (see .env.example) and implemented as one pure-ASGI middleware so it
also covers the OTLP ingest routes. Defaults are safe for local development (auth off, with a startup warning);
set TRACEMIND_AUTH_REQUIRED=true in production to refuse to start without credentials.

  TRACEMIND_API_KEY            bearer token required on /api/*
  TRACEMIND_INGEST_TOKEN       bearer token required on /v1/* (set the same value in the collector's exporter headers)
  TRACEMIND_AUTH_REQUIRED      "true": fail startup if either token is missing
  TRACEMIND_CORS_ORIGINS       comma-separated allowed browser origins (default: none, i.e. same-origin only)
  TRACEMIND_RATE_LIMIT_PER_MIN per-client budget for /api/* reads (default 240, 0 disables)
  TRACEMIND_HEAVY_LIMIT_PER_MIN per-client budget for model-cost POSTs: investigations, remediations (default 10)
  TRACEMIND_INGEST_LIMIT_PER_MIN per-client budget for /v1/* (default 6000, 0 disables)
  TRACEMIND_TRUST_PROXY        "true": take the client address from X-Forwarded-For (only behind a trusted proxy)
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

log = logging.getLogger("tracemind.security")

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

OPEN_PATHS = {"/healthz", "/readyz"}
_HEAVY = re.compile(r"^/api/(incidents/[^/]+/investigations|investigations/[^/]+/remediations)$")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class TokenBucket:
    """Per-key token bucket: `per_min` tokens refill continuously, burst equals one minute of budget."""

    def __init__(self, per_min: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_min, self.clock = per_min, clock
        self.lock = threading.Lock()
        self.state: dict[str, tuple[float, float]] = {}

    def take(self, key: str) -> float:
        """Return 0.0 if allowed, else seconds until a token is available."""
        if self.per_min <= 0:
            return 0.0
        now, rate = self.clock(), self.per_min / 60.0
        with self.lock:
            tokens, last = self.state.get(key, (float(self.per_min), now))
            tokens = min(float(self.per_min), tokens + (now - last) * rate)
            if tokens >= 1.0:
                self.state[key] = (tokens - 1.0, now)
                if len(self.state) > 10_000:  # bound memory under address churn
                    self._evict(now)
                return 0.0
            self.state[key] = (tokens, now)
            return (1.0 - tokens) / rate

    def _evict(self, now: float) -> None:
        cutoff = now - 120
        for k in [k for k, (_, last) in self.state.items() if last < cutoff]:
            del self.state[k]


def check_startup_config() -> None:
    """Called from the app lifespan. Warns (or, with TRACEMIND_AUTH_REQUIRED, refuses) when auth is not configured."""
    missing = [n for n in ("TRACEMIND_API_KEY", "TRACEMIND_INGEST_TOKEN") if not os.environ.get(n)]
    if not missing:
        return
    if _flag("TRACEMIND_AUTH_REQUIRED"):
        raise RuntimeError(f"TRACEMIND_AUTH_REQUIRED is set but {', '.join(missing)} is empty")
    log.warning("authentication DISABLED for %s - fine for local development, not for anything reachable by others",
                ", ".join(missing))


def _bearer(headers: list[tuple[bytes, bytes]]) -> str:
    for k, v in headers:
        if k == b"authorization":
            val = v.decode("latin-1")
            if val[:7].lower() == "bearer ":
                return val[7:].strip()
    return ""


def _authorized(presented: str, expected: str) -> bool:
    return hmac.compare_digest(presented.encode(), expected.encode())


class SecurityMiddleware:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app
        self.read = TokenBucket(_int("TRACEMIND_RATE_LIMIT_PER_MIN", 240))
        self.heavy = TokenBucket(_int("TRACEMIND_HEAVY_LIMIT_PER_MIN", 10))
        self.ingest = TokenBucket(_int("TRACEMIND_INGEST_LIMIT_PER_MIN", 6000))
        self.origins = {o.strip() for o in os.environ.get("TRACEMIND_CORS_ORIGINS", "").split(",") if o.strip()}
        self.trust_proxy = _flag("TRACEMIND_TRUST_PROXY")

    def _client(self, scope: Scope) -> str:
        if self.trust_proxy:
            for k, v in scope["headers"]:
                if k == b"x-forwarded-for":
                    return v.decode("latin-1").split(",")[0].strip()
        c = scope.get("client")
        return c[0] if c else "unknown"

    async def _reply(self, send: Send, status: int, detail: str, extra: list[tuple[bytes, bytes]] | None = None,
                     cors: list[tuple[bytes, bytes]] | None = None) -> None:
        body = json.dumps({"detail": detail}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                   *SECURITY_HEADERS, *(extra or []), *(cors or [])]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, method = scope["path"], scope["method"]
        origin = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"origin"), "")
        cors: list[tuple[bytes, bytes]] = []
        if origin and origin in self.origins:
            cors = [(b"access-control-allow-origin", origin.encode()), (b"vary", b"Origin"),
                    (b"access-control-allow-headers", b"authorization, content-type"),
                    (b"access-control-allow-methods", b"GET, POST, OPTIONS")]
        if method == "OPTIONS" and cors:  # CORS preflight carries no credentials by design
            await self._reply(send, 204, "", cors=cors)
            return

        if path not in OPEN_PATHS:
            is_ingest = path.startswith("/v1/")
            expected = os.environ.get("TRACEMIND_INGEST_TOKEN" if is_ingest else "TRACEMIND_API_KEY", "")
            if expected and not _authorized(_bearer(scope["headers"]), expected):
                await self._reply(send, 401, "missing or invalid credentials",
                                  [(b"www-authenticate", b'Bearer realm="tracemind"')], cors)
                return
            bucket = self.ingest if is_ingest else (self.heavy if method == "POST" and _HEAVY.match(path) else self.read)
            wait = bucket.take(f"{'i' if is_ingest else 'a'}:{self._client(scope)}" +
                               (":h" if bucket is self.heavy else ""))
            if wait > 0:
                await self._reply(send, 429, "rate limit exceeded", [(b"retry-after", str(int(wait) + 1).encode())], cors)
                return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                present = {k for k, _ in message["headers"]}
                message["headers"] = [*message["headers"], *[h for h in SECURITY_HEADERS if h[0] not in present], *cors]
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ---- redaction of secrets / PII before text is sent to a third-party model provider -----------------------------

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED:private-key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED:jwt]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer [REDACTED:token]"),
    (re.compile(r"\b(?:AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})\b"),
     "[REDACTED:api-key]"),
    (re.compile(r"(?i)\b([a-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|authorization)[a-z0-9_.-]*)"
                r"(\"?\s*[:=]\s*\"?)([^\s\"',;&]{3,})"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@/]+)(@)"), r"\1[REDACTED]\3"),  # user:pass@ in URLs
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED:email]"),
]


def redact(text: str) -> str:
    """Mask credentials and common PII. Evidence refs (span:/log:/sig:/code:) and ids contain none of these shapes."""
    if os.environ.get("TRACEMIND_REDACTION", "on").lower() in ("off", "0", "false"):
        return text
    for pat, repl in _REDACTIONS:
        text = pat.sub(repl, text)
    return text
