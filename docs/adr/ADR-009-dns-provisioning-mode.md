# ADR-009: DNS provisioning mode

| Field | Value |
|---|---|
| **Status** | Deferred — decided with ADR-008 at the domain phase |
| **Date** | 2026-09-26 |

## Decision
Candidate: explicit proxied DNS records per merchant created idempotently through a `DnsProvider` adapter, a wildcard tunnel ingress rule, and wildcard DNS as a scale fallback.

## Context
Merchant creation must not require manual DNS work (Master §17).

## Alternatives
Manual records; per-merchant tunnel routes.

## Reason
Unknown hosts never reach the origin; auditable; no tunnel restart per merchant.

## Consequences
Requires a zone-scoped Cloudflare API token at the domain phase.
