# ADR-019: Object storage behind the S3 API

| Field | Value |
|---|---|
| **Status** | Proposed — product selection pending |
| **Date** | 2026-09-26 |

## Decision
The application talks only to the S3 API. The self-hosted product is chosen after a licence and maintenance review (candidates: MinIO, Garage, SeaweedFS).

## Context
Large media must not live in PostgreSQL (Master §56). The community distribution terms of some S3 servers changed in 2025.

## Alternatives
Coupling code to one product's API.

## Reason
Keeps the backend swappable.

## Consequences
The selection must be recorded as a new ADR before first deployment.
