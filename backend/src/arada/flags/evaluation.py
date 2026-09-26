"""Pure feature-flag evaluation (no I/O), so the precedence rule is testable alone."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Source = Literal[
    "platform_enforced", "tenant", "vertical", "blueprint", "platform", "default"
]  # fmt: skip


@dataclass(frozen=True, slots=True)
class Override:
    enabled: bool
    enforced: bool = False


@dataclass(frozen=True, slots=True)
class FlagValue:
    key: str
    enabled: bool
    source: Source


def evaluate(
    key: str,
    *,
    default: bool,
    platform: Override | None,
    vertical: Override | None,
    tenant: Override | None,
    blueprint_default: bool | None,
) -> FlagValue:
    """Most decisive first:

    1. an *enforced* platform override (emergency kill switch or global force)
    2. the tenant's own override
    3. the tenant's vertical override
    4. the default declared by the tenant's pinned blueprint version
    5. a non-enforced platform override (changes the global default)
    6. the flag's built-in default
    """
    if platform is not None and platform.enforced:
        return FlagValue(key, platform.enabled, "platform_enforced")
    if tenant is not None:
        return FlagValue(key, tenant.enabled, "tenant")
    if vertical is not None:
        return FlagValue(key, vertical.enabled, "vertical")
    if blueprint_default is not None:
        return FlagValue(key, blueprint_default, "blueprint")
    if platform is not None:
        return FlagValue(key, platform.enabled, "platform")
    return FlagValue(key, default, "default")
