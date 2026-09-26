# ADR-024: Provider-agnostic identity; customers are per tenant

| Field | Value |
|---|---|
| **Status** | Accepted — Master Directive §59–60; Permanent Command §11 |
| **Date** | 2026-09-26 |

## Decision
Global `persons` with provider `identities` (Telegram first; phone, web and others later). Each tenant has its own `customers` record for a person.

## Context
Telegram is the first channel, not the backend; merchants must not see a person's activity at other merchants.

## Alternatives
Users keyed by Telegram id.

## Reason
New channels need no identity rewrite; privacy between merchants.

## Consequences
Account linking across providers requires verified proof of both identities.
