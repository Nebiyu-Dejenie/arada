# ADR-026: ROOT_DOMAIN is configuration and currently TBD

| Field | Value |
|---|---|
| **Status** | Accepted — Permanent Command §26–27, §51 |
| **Date** | 2026-09-26 |

## Decision
Every hostname derives from the `ROOT_DOMAIN` setting and the `domains` table. The value is TBD; the owner supplies it at the domain/Cloudflare phase. `arada.fun` and `arada.click` are never used.

## Context
The owner withdrew both previously observed domains from consideration.

## Alternatives
Choosing a domain now.

## Reason
No hard-coded domains; no premature DNS decisions.

## Consequences
Local development uses `*.localhost`. Public staging deployment waits for the domain.
