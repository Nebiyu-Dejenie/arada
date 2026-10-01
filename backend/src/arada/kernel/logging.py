"""Structured logging with correlation fields and secret redaction.

Every log line carries request_id, trace_id, tenant_id and user_id when known.
A redaction processor removes secret-bearing keys and token-shaped values
before anything is rendered (09_SECURITY.md §10).
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any, TextIO

import structlog

from arada.kernel.context import current_correlation

REDACTED = "[REDACTED]"

_SECRET_KEYS = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|cookie|totp|otp_code|init_?data|api_?key|"
    r"private_?key|credential|kek|dsn)",
    re.IGNORECASE,
)
_SECRET_VALUES = [
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token shape
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\$argon2(id|i|d)\$[^\s\"']+"),
    re.compile(r"postgres(ql)?(\+\w+)?://[^\s:@/]+:[^\s@/]+@"),
]


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        for pattern in _SECRET_VALUES:
            value = pattern.sub(REDACTED, value)
        return value
    if isinstance(value, dict):
        return {
            k: (REDACTED if _SECRET_KEYS.search(str(k)) else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    return value


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict.keys()):
        if key == "event":
            event_dict[key] = _redact_value(event_dict[key])
        elif _SECRET_KEYS.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def correlation_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    corr = current_correlation()
    for name in ("request_id", "trace_id", "tenant_id", "user_id"):
        value = getattr(corr, name)
        if value is not None:
            event_dict.setdefault(name, value)
    return event_dict


def configure_logging(
    level: str = "INFO", fmt: str = "json", *, stream: TextIO | None = None
) -> None:
    """Configure structlog. ``stream`` defaults to stdout (tests pass a buffer
    to inspect exactly what the redacting pipeline emits)."""
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            correlation_processor,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
