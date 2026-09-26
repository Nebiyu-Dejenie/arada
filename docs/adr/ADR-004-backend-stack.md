# ADR-004: Backend stack: Python + FastAPI

| Field | Value |
|---|---|
| **Status** | Assumed — documented assumption per Permanent Command §53; the owner may override before Phase 1 code |
| **Date** | 2026-09-26 |

## Decision
Python 3.12+ (images pin an exact minor version), FastAPI, Pydantic v2 + pydantic-settings (typed configuration), SQLAlchemy 2 Core over asyncpg, Alembic, aiogram 3.

## Context
The owner has not specified a stack. The development workstation has Python 3.12, Node 22 and Docker. Webhook-heavy, I/O-bound workloads dominate.

## Alternatives
Spring Boot / Java; Go; NestJS / TypeScript.

## Reason
Strong async I/O ecosystem, mature Telegram library, fast iteration, strict typing via mypy, and prior in-house experience with these patterns.

## Consequences
CPU-bound hotspots, if measured, are extracted into a faster runtime later. Changing the stack after Phase 1 would be expensive, so an override should come before Phase 1 starts.
