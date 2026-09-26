"""Registry of vertical-specific code extensions (03_BLUEPRINT_ENGINE.md §8).

Genuinely vertical-specific logic lives here as named, registered functions
that blueprints reference by key. Platform modules never branch on a
vertical: they ask the registry. A blueprint that references an unregistered
extension cannot be saved or published.

Phase 1 registers only what the reference vertical's blueprint needs to be
valid; the validators run against real data from Phase 3 (catalog).
"""

from __future__ import annotations

from collections.abc import Callable

Validator = Callable[[str], bool]

_REGISTRY: dict[str, Validator] = {}


def register(key: str) -> Callable[[Validator], Validator]:
    def decorator(fn: Validator) -> Validator:
        if key in _REGISTRY:
            raise ValueError(f"extension {key} registered twice")
        _REGISTRY[key] = fn
        return fn

    return decorator


def is_registered(key: str) -> bool:
    return key in _REGISTRY


def get(key: str) -> Validator:
    return _REGISTRY[key]


def registered() -> frozenset[str]:
    return frozenset(_REGISTRY)


@register("imei.luhn")
def imei_luhn(value: str) -> bool:
    """A 15-digit IMEI whose last digit is the Luhn check digit."""
    if len(value) != 15 or not value.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(value)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
