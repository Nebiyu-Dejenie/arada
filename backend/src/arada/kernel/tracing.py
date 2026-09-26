"""W3C Trace Context (``traceparent``) handling.

Phase 1 generates and propagates trace/span ids without an OpenTelemetry SDK.
The ids are OTel-compatible, so adding the SDK and a trace backend later is a
configuration change, not a rewrite (Permanent Command §24).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_INVALID_TRACE = "0" * 32
_INVALID_SPAN = "0" * 16


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    span_id: str
    sampled: bool

    def header(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{'01' if self.sampled else '00'}"


def new_span(parent: TraceContext | None) -> TraceContext:
    """Start a span for this request: continue the parent trace or begin one."""
    trace_id = parent.trace_id if parent else secrets.token_hex(16)
    sampled = parent.sampled if parent else True
    return TraceContext(trace_id=trace_id, span_id=secrets.token_hex(8), sampled=sampled)


def parse_traceparent(value: str | None) -> TraceContext | None:
    if not value:
        return None
    match = _TRACEPARENT.match(value.strip().lower())
    if not match:
        return None
    trace_id, span_id, flags = match.groups()
    if trace_id == _INVALID_TRACE or span_id == _INVALID_SPAN:
        return None
    return TraceContext(trace_id=trace_id, span_id=span_id, sampled=int(flags, 16) & 1 == 1)
