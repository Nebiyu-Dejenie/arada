# ADR-008: Hostname naming convention

| Field | Value |
|---|---|
| **Status** | Deferred — Permanent Command §27: finalise at the domain/tenant-routing phase |
| **Date** | 2026-09-26 |

## Decision
Not yet decided. The leading candidate, from the evaluation in `05_DOMAIN_AND_TUNNEL.md` §2, is `<slug>.<ROOT_DOMAIN>` per merchant, with shared console hosts (`merchant.`, `admin.`, `finance.`).

## Context
The Master Directive asked for an evaluation; the Permanent Command defers the final choice. `ROOT_DOMAIN` is TBD.

## Alternatives
Per-merchant role hosts (`admin-<slug>`, `finance-<slug>`).

## Reason
The candidate uses one DNS record per merchant, a single admin attack surface, and clean cookie isolation.

## Consequences
Application code must read all hostnames from configuration and the `domains` table, so the final convention needs no code change.
