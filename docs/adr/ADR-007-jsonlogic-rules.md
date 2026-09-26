# ADR-007: Rules expressed in JSONLogic

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
Validation, conditional-field and workflow-guard rules in blueprints use JSONLogic, evaluated in the browser for UX and re-evaluated on the server as the authority.

## Context
The Super Admin must define rules without code changes (Master §37).

## Alternatives
Embedded scripting (Lua/JS); CEL.

## Reason
Sandboxed, serialisable, diffable, with equivalent evaluators in Python and TypeScript.

## Consequences
Complex logic that JSONLogic cannot express goes into registered extensions, not into the rule language.
