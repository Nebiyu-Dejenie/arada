"""Blueprint definition documents: meta-schema, semantic validation, versions.

A definition describes a vertical's entities and typed attributes
(03_BLUEPRINT_ENGINE.md §1-§3). Phase 1 covers the foundation: entities,
attributes, feature defaults and extension references. Forms, rules and
workflows arrive as ``schema_version`` 2 in later phases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Any

from jsonschema import Draft202012Validator

from arada.blueprints import extensions
from arada.kernel.errors import ValidationFailed

ATTRIBUTE_TYPES = (
    "string", "text", "number", "boolean", "enum", "multi_enum", "date", "datetime",
    "location", "image", "document", "money", "measurement", "relation",
)  # fmt: skip

_IDENT = "^[a-z][a-z0-9_]{1,39}$"
_LABEL: dict[str, Any] = {
    "type": "object",
    "required": ["en"],
    "additionalProperties": False,
    "properties": {
        "en": {"type": "string", "minLength": 1, "maxLength": 80},
        "am": {"type": "string", "minLength": 1, "maxLength": 80},
    },
}

META_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "entities"],
    "properties": {
        "schema_version": {"const": 1},
        "description": {"type": "string", "maxLength": 500},
        "entities": {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 30,
            "propertyNames": {"pattern": _IDENT},
            "additionalProperties": {"$ref": "#/$defs/entity"},
        },
        "features": {
            "type": "object",
            "propertyNames": {"pattern": _IDENT},
            "additionalProperties": {"type": "boolean"},
        },
        "extensions": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 50,
            "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"},
        },
    },
    "$defs": {
        "label": _LABEL,
        "entity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "attributes"],
            "properties": {
                "kind": {"enum": ["core", "custom"]},
                "label": {"$ref": "#/$defs/label"},
                "attributes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 200,
                    "items": {"$ref": "#/$defs/attribute"},
                },
            },
        },
        "attribute": {
            "type": "object",
            "additionalProperties": False,
            "required": ["key", "type"],
            "properties": {
                "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,39}$"},
                "type": {"enum": list(ATTRIBUTE_TYPES)},
                "label": {"$ref": "#/$defs/label"},
                "required": {"type": "boolean"},
                "unit": {"type": "string", "minLength": 1, "maxLength": 16},
                "min": {"type": "number"},
                "max": {"type": "number"},
                "options": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["key"],
                        "properties": {
                            "key": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_]{0,39}$"},
                            "label": {"$ref": "#/$defs/label"},
                        },
                    },
                },
                "target": {"type": "string", "pattern": _IDENT},
                "filterable": {"type": "boolean"},
                "searchable": {"type": "boolean"},
                "unique_within_tenant": {"type": "boolean"},
                "pii": {"type": "boolean"},
                "visibility": {"enum": ["public", "staff", "owner"]},
                "extensions": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
                    },
                },
            },
            "allOf": [
                {
                    "if": {"properties": {"type": {"enum": ["enum", "multi_enum"]}}},
                    "then": {"required": ["options"]},
                    "else": {"not": {"required": ["options"]}},
                },
                {
                    "if": {"properties": {"type": {"const": "relation"}}},
                    "then": {"required": ["target"]},
                    "else": {"not": {"required": ["target"]}},
                },
            ],
        },
    },
}

_VALIDATOR = Draft202012Validator(META_SCHEMA)
Draft202012Validator.check_schema(META_SCHEMA)


def validate(definition: dict[str, Any]) -> None:
    """Structural (meta-schema) then semantic validation. Raises ValidationFailed."""
    errors: dict[str, list[str]] = {}
    for err in sorted(_VALIDATOR.iter_errors(definition), key=lambda e: list(e.path)):
        path = "definition" + "".join(
            f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.path
        )
        errors.setdefault(path, []).append(err.message[:200])
        if len(errors) >= 20:
            break
    if errors:
        raise ValidationFailed("blueprint definition is invalid", errors=errors)

    entities: dict[str, Any] = definition["entities"]
    for name, entity in entities.items():
        keys: set[str] = set()
        for attr in entity["attributes"]:
            where = f"definition.entities.{name}.{attr['key']}"
            if attr["key"] in keys:
                errors.setdefault(where, []).append("duplicate attribute key")
            keys.add(attr["key"])
            options = [o["key"] for o in attr.get("options", [])]
            if len(options) != len(set(options)):
                errors.setdefault(where, []).append("duplicate option key")
            if "min" in attr and "max" in attr and attr["min"] > attr["max"]:
                errors.setdefault(where, []).append("min is greater than max")
            if attr["type"] == "relation" and attr["target"] not in entities:
                errors.setdefault(where, []).append("relation target is not an entity")
            for ext in attr.get("extensions", []):
                if not extensions.is_registered(ext):
                    errors.setdefault(where, []).append(f"unknown extension {ext}")
    for ext in definition.get("extensions", []):
        if not extensions.is_registered(ext):
            errors.setdefault("definition.extensions", []).append(f"unknown extension {ext}")
    if errors:
        raise ValidationFailed("blueprint definition is invalid", errors=errors)


# ---------------------------------------------------------------- versions
_SEMVER = re.compile(r"^(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})$")


@total_ordering
@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> SemVer:
        match = _SEMVER.match(value)
        if not match:
            raise ValidationFailed(errors={"version": ["must be MAJOR.MINOR.PATCH (e.g. 1.0.0)"]})
        return cls(*(int(x) for x in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def bump_from(self, previous: SemVer) -> str:
        if self.major != previous.major:
            return "major"
        if self.minor != previous.minor:
            return "minor"
        return "patch"


# ---------------------------------------------------------------- compatibility
LEVELS = ("none", "patch", "minor", "major")


@dataclass(frozen=True, slots=True)
class Compatibility:
    level: str
    reasons: tuple[str, ...]


def _attrs(definition: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (entity, attr["key"]): attr
        for entity, spec in definition["entities"].items()
        for attr in spec["attributes"]
    }


_PRESENTATION_KEYS = {"label"}


def classify(old: dict[str, Any], new: dict[str, Any]) -> Compatibility:
    """Classify the change from ``old`` to ``new`` (03_BLUEPRINT_ENGINE.md §6).

    major: can break existing merchants or data (removals, type changes,
           newly required fields, narrowed constraints, removed options).
    minor: additive and backward compatible.
    patch: presentation only (labels, description).
    """
    major: list[str] = []
    minor: list[str] = []
    patch: list[str] = []

    for entity in old["entities"].keys() - new["entities"].keys():
        major.append(f"entity {entity} removed")
    for entity in new["entities"].keys() - old["entities"].keys():
        minor.append(f"entity {entity} added")

    old_attrs, new_attrs = _attrs(old), _attrs(new)
    for key in old_attrs.keys() - new_attrs.keys():
        if key[0] in new["entities"]:
            major.append(f"attribute {key[0]}.{key[1]} removed")
    for key in new_attrs.keys() - old_attrs.keys():
        if key[0] not in old["entities"]:
            continue
        target = major if new_attrs[key].get("required") else minor
        target.append(
            f"attribute {key[0]}.{key[1]} added" + (" as required" if target is major else "")
        )

    for key in old_attrs.keys() & new_attrs.keys():
        a, b = old_attrs[key], new_attrs[key]
        name = f"{key[0]}.{key[1]}"
        if a["type"] != b["type"]:
            major.append(f"{name} type {a['type']} -> {b['type']}")
        if not a.get("required") and b.get("required"):
            major.append(f"{name} became required")
        elif a.get("required") and not b.get("required"):
            minor.append(f"{name} became optional")
        if a.get("unit") != b.get("unit"):
            major.append(f"{name} unit changed")
        if a.get("target") != b.get("target"):
            major.append(f"{name} relation target changed")
        old_opts = {o["key"] for o in a.get("options", [])}
        new_opts = {o["key"] for o in b.get("options", [])}
        if old_opts - new_opts:
            major.append(f"{name} options removed: {sorted(old_opts - new_opts)}")
        if new_opts - old_opts:
            minor.append(f"{name} options added: {sorted(new_opts - old_opts)}")
        for bound in ("min", "max"):
            old_v, new_v = a.get(bound), b.get(bound)
            if old_v == new_v:
                continue
            if new_v is None:
                minor.append(f"{name} {bound} removed (widened)")
            elif old_v is None:
                major.append(f"{name} {bound} added (narrowed)")
            elif (bound == "min" and new_v > old_v) or (bound == "max" and new_v < old_v):
                major.append(f"{name} {bound} narrowed")
            else:
                minor.append(f"{name} {bound} widened")
        for flag in ("filterable", "searchable", "pii", "visibility", "unique_within_tenant"):
            if a.get(flag) != b.get(flag):
                (major if flag == "unique_within_tenant" and b.get(flag) else minor).append(
                    f"{name} {flag} changed"
                )
        if set(a.get("extensions", [])) - set(b.get("extensions", [])):
            major.append(f"{name} extension removed")
        if set(b.get("extensions", [])) - set(a.get("extensions", [])):
            major.append(f"{name} extension added (stricter validation)")
        if {k: v for k, v in a.items() if k in _PRESENTATION_KEYS} != {
            k: v for k, v in b.items() if k in _PRESENTATION_KEYS
        }:
            patch.append(f"{name} label changed")

    for ext in set(old.get("extensions", [])) - set(new.get("extensions", [])):
        major.append(f"extension {ext} removed")
    for ext in set(new.get("extensions", [])) - set(old.get("extensions", [])):
        minor.append(f"extension {ext} added")
    if old.get("features") != new.get("features"):
        minor.append("feature defaults changed")
    for entity in old["entities"].keys() & new["entities"].keys():
        if old["entities"][entity].get("label") != new["entities"][entity].get("label"):
            patch.append(f"entity {entity} label changed")
        if old["entities"][entity]["kind"] != new["entities"][entity]["kind"]:
            major.append(f"entity {entity} kind changed")
    if old.get("description") != new.get("description"):
        patch.append("description changed")

    if major:
        return Compatibility("major", tuple(major))
    if minor:
        return Compatibility("minor", tuple(minor))
    if patch:
        return Compatibility("patch", tuple(patch))
    return Compatibility("none", ())
