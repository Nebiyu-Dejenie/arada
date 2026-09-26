# ADR-021: ARADA is fully separate from unrelated local projects

| Field | Value |
|---|---|
| **Status** | Accepted — Permanent Command §26, §51 |
| **Date** | 2026-09-26 |

## Decision
ARADA shares no code, runtime, database, tunnel, credentials or domain with other projects on the development workstation, including those using `arada.fun` and `arada.click`. General engineering lessons may inform designs.

## Context
The owner stated that those domains belong to unrelated projects.

## Alternatives
Extending or co-hosting with another project.

## Reason
Blast-radius isolation and a clean ownership boundary.

## Consequences
Nothing is imported from other local repositories.
