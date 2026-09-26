"""Feature flag precedence (pure function)."""

from __future__ import annotations

from arada.flags.evaluation import Override, evaluate


def value(**kw: object) -> tuple[bool, str]:
    params: dict[str, object] = {
        "default": False,
        "platform": None,
        "vertical": None,
        "tenant": None,
        "blueprint_default": None,
    }
    params.update(kw)
    result = evaluate("reviews", **params)  # type: ignore[arg-type]
    return result.enabled, result.source


def test_default_applies_when_nothing_else_does() -> None:
    assert value() == (False, "default")
    assert value(default=True) == (True, "default")


def test_precedence_from_general_to_specific() -> None:
    assert value(platform=Override(True)) == (True, "platform")
    assert value(platform=Override(True), blueprint_default=False) == (False, "blueprint")
    assert value(blueprint_default=False, vertical=Override(True)) == (True, "vertical")
    assert value(vertical=Override(True), tenant=Override(False)) == (False, "tenant")


def test_enforced_platform_override_is_a_kill_switch() -> None:
    assert value(platform=Override(False, enforced=True), tenant=Override(True)) == (
        False,
        "platform_enforced",
    )
    assert value(platform=Override(True, enforced=True), tenant=Override(False)) == (
        True,
        "platform_enforced",
    )
