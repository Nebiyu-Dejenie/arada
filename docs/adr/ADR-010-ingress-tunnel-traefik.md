# ADR-010: Single controlled ingress: Cloudflare Tunnel → Traefik, all routing in git

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
`cloudflared` runs as a container with one project tunnel, forwarding to Traefik v3 whose routers come from committed files. Unmatched requests get 404. No production service publishes a host port.

## Context
No public origin (Master §15; Permanent §26); a single ingress layer (Master §19).

## Alternatives
Host-level cloudflared with untracked proxy config; cloudflared routing directly to services.

## Reason
Reviewable routing; central security middleware; no drift between hosts and git.

## Consequences
CI rejects `ports:` in production compose files.
