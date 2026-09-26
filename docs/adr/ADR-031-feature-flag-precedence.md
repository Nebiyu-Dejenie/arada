# ADR-031: Feature flag precedence

| Field | Value |
|---|---|
| **Status** | Proposed — implemented in Phase 1 |
| **Date** | 2026-09-26 |

## Decision
Most decisive first: an enforced platform override (kill switch) → tenant override → vertical override → the default declared by the tenant's pinned blueprint version → a platform (global default) override → the flag's built-in default. Every evaluated value reports its source. Flags and overrides are platform configuration: control plane, changed only with `flags.manage`, and audited.

## Context
Permanent Command §29 asks for platform, vertical and tenant flags. Blueprints already declare feature defaults (03_BLUEPRINT_ENGINE.md).

## Alternatives
Most-specific-wins without a kill switch (no safe emergency stop); tenant self-service toggles (flags often gate paid or plan features; deferred until plans exist).

## Reason
It gives operations an emergency stop, lets blueprints carry sensible defaults, and makes every value explainable.

## Consequences
Evaluation is a pure function, tested alone. Percentage rollouts and plan-driven entitlements are Planned.
