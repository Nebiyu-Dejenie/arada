# ADR-018: Search on PostgreSQL: full text + trigram + structured filters behind SearchPort

| Field | Value |
|---|---|
| **Status** | Accepted — mandated by Permanent Command §19, §34 |
| **Date** | 2026-09-26 |

## Decision
Weighted `tsvector` full-text search, `pg_trgm` for fuzzy and typo-tolerant matching (including transliterated Amharic/Latin brand names), and typed attribute filters, all behind a `SearchPort` interface.

## Context
Search must start resource-efficient; OpenSearch only when PostgreSQL becomes insufficient.

## Alternatives
OpenSearch on day one.

## Reason
No extra cluster to run; the interface allows a later swap.

## Consequences
Revisit when search p95 exceeds its target or relevance needs outgrow Postgres.
