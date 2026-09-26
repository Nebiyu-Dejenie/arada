# ADR-020: Docker Compose + Ansible; no Kubernetes yet

| Field | Value |
|---|---|
| **Status** | Accepted — mandated by Permanent Command §25, §34; Master Directive §20 |
| **Date** | 2026-09-26 |

## Decision
Deploy with Docker Compose on VMs, configure hosts with Ansible, and use Terraform only where it adds value (for example Cloudflare).

## Context
The initial deployment is self-hosted and cost-conscious.

## Alternatives
Kubernetes now.

## Reason
The smallest operational surface.

## Consequences
Revisit only when the triggers in `11_DEPLOYMENT.md` are met, based on metrics.
