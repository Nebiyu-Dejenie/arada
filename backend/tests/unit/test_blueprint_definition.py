"""Blueprint definitions: validation, versions, compatibility, extensions."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from arada.blueprints import extensions
from arada.blueprints.definition import SemVer, classify, validate
from arada.kernel.errors import ValidationFailed

REPO = Path(__file__).resolve().parents[3]
SEEDS = REPO / "blueprints" / "phones"


def seed(version: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((SEEDS / f"{version}.yaml").read_text())
    return data


def minimal() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entities": {
            "item": {
                "kind": "core",
                "attributes": [
                    {"key": "name", "type": "string", "required": True},
                    {"key": "size", "type": "enum", "options": [{"key": "s"}, {"key": "m"}]},
                    {"key": "weight", "type": "number", "min": 0, "max": 100},
                ],
            }
        },
    }


def with_attrs(defn: dict[str, Any], mutate: Any) -> dict[str, Any]:
    out = copy.deepcopy(defn)
    mutate(out["entities"]["item"]["attributes"])
    return out


# ------------------------------------------------------------- validation
def test_reference_seeds_are_valid() -> None:
    for version in ("1.0.0", "1.1.0", "2.0.0"):
        validate(seed(version))


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda a: a.append({"key": "x", "type": "colour"}), "is not one of"),
        (lambda a: a.append({"key": "x", "type": "enum"}), "options"),
        (
            lambda a: a.append({"key": "x", "type": "string", "options": [{"key": "a"}]}),
            "should not be valid",
        ),
        (
            lambda a: a.append({"key": "x", "type": "relation", "target": "missing"}),
            "relation target",
        ),
        (lambda a: a.append({"key": "name", "type": "string"}), "duplicate attribute key"),
        (lambda a: a.append({"key": "x", "type": "number", "min": 5, "max": 1}), "min is greater"),
        (
            lambda a: a.append({"key": "x", "type": "string", "extensions": ["no.such"]}),
            "unknown extension",
        ),
        (
            lambda a: a.append({"key": "x", "type": "string", "admin": True}),
            "Additional properties",
        ),
    ],
)
def test_invalid_definitions_are_rejected(mutate: Any, fragment: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate(with_attrs(minimal(), mutate))
    assert exc.value.errors
    assert any(fragment in msg for msgs in exc.value.errors.values() for msg in msgs), (
        exc.value.errors
    )


def test_unknown_top_level_keys_and_schema_versions_rejected() -> None:
    bad = minimal() | {"schema_version": 2}
    with pytest.raises(ValidationFailed):
        validate(bad)
    with pytest.raises(ValidationFailed):
        validate(minimal() | {"sql": "DROP TABLE"})


# ------------------------------------------------------------- versions
def test_semver_parsing_and_ordering() -> None:
    assert SemVer.parse("1.10.0") > SemVer.parse("1.9.9")
    assert SemVer.parse("2.0.0").bump_from(SemVer.parse("1.9.0")) == "major"
    assert SemVer.parse("1.2.0").bump_from(SemVer.parse("1.1.5")) == "minor"
    assert SemVer.parse("1.1.6").bump_from(SemVer.parse("1.1.5")) == "patch"
    for bad in ("1.0", "v1.0.0", "01.0.0", "1.0.0-beta", "1.0.0; DROP"):
        with pytest.raises(ValidationFailed):
            SemVer.parse(bad)


# ------------------------------------------------------------- compatibility
@pytest.mark.parametrize(
    ("mutate", "level"),
    [
        (lambda a: a.append({"key": "x", "type": "string"}), "minor"),
        (lambda a: a.append({"key": "x", "type": "string", "required": True}), "major"),
        (lambda a: a.pop(), "major"),
        (lambda a: a[0].update(type="text"), "major"),
        (lambda a: a[2].update(required=True), "major"),
        (lambda a: a[1]["options"].pop(), "major"),
        (lambda a: a[1]["options"].append({"key": "l"}), "minor"),
        (lambda a: a[2].update(max=50), "major"),
        (lambda a: a[2].update(max=500), "minor"),
        (lambda a: a[0].update(label={"en": "Title"}), "patch"),
        (lambda a: None, "none"),
    ],
)
def test_change_classification(mutate: Any, level: str) -> None:
    base = minimal()
    assert classify(base, with_attrs(base, mutate)).level == level


def test_reference_seed_progression() -> None:
    assert classify(seed("1.0.0"), seed("1.1.0")).level == "minor"
    major = classify(seed("1.1.0"), seed("2.0.0"))
    assert major.level == "major"
    assert any("color" in r for r in major.reasons)


# ------------------------------------------------------------- extensions
def test_imei_luhn_extension() -> None:
    check = extensions.get("imei.luhn")
    assert check("490154203237518")
    assert not check("490154203237519")
    assert not check("49015420323751")
    assert not check("49015420323751x")


def test_platform_code_never_branches_on_a_vertical() -> None:
    """Permanent Command §47: no hard-coded verticals outside extensions."""
    src = REPO / "backend" / "src" / "arada"
    pattern = re.compile(
        r"['\"](phones?|cars?|property|fashion|food|jobs|events|furniture|beauty)['\"]", re.I
    )
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if path.name != "extensions.py" and pattern.search(path.read_text())
    ]
    assert offenders == []
