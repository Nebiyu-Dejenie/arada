# ADR-022: Identifiers: application-generated UUIDv7 plus per-tenant human references

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
Primary keys are UUIDv7 (RFC 9562) generated in the application. Human-readable references (for example `ORD-26-000123`) come from per-tenant sequences.

## Context
IDs must be non-enumerable, index-friendly and independent of the database version.

## Alternatives
Serial IDs (enumerable, leak volume); UUIDv4 (poor index locality).

## Reason
Good index locality without exposing counts.

## Consequences
—
