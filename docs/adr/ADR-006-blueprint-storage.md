# ADR-006: Blueprint storage: immutable versioned documents, no per-blueprint DDL

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
Blueprint versions are JSON documents validated by a meta-schema and immutable once published. Core entities are relational tables with platform-owned columns plus `attributes jsonb`; custom entities use `entity_records`; filterable attributes are projected into a typed `attribute_values` table.

## Context
Verticals must be data, not code (Master §4, §75), but JSON must not replace relational design for core entities (Permanent §22).

## Alternatives
Per-vertical tables created at runtime; pure EAV.

## Reason
Safe dynamic fields; indexed range filters; money, stock and isolation columns stay platform-controlled.

## Consequences
The projection must be maintained transactionally on every write.
