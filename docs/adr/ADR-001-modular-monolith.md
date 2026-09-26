# ADR-001: Modular monolith with process roles

| Field | Value |
|---|---|
| **Status** | Accepted — mandated by Permanent Command §34–35; Master Directive §97 |
| **Date** | 2026-09-26 |

## Decision
Build one backend codebase and one image with hard internal module boundaries, deployed as process roles `api`, `worker`, `scheduler`, `migrate`.

## Context
The platform must eventually serve thousands of merchants, but the first deployment must be small, affordable and operable by a very small team.

## Alternatives
Microservices from day one; separate deployables per vertical.

## Reason
Lowest operational cost; module boundaries (import-linter contracts, module-owned tables, events) keep future extraction possible without rewriting the domain model.

## Consequences
Boundary discipline must be enforced in CI. A module is extracted only on measured evidence (independent scaling, failure isolation, enterprise tier).
