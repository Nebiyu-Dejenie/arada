# 13 — Disaster Recovery

Status: **Proposed; backup destination blocked on Q5** · Phase 1 (backups and restore drill are Phase 1 exit criteria)

## 1. Objectives

| Stage | RPO (max data loss) | RTO (max time to restore service) | How |
|---|---|---|---|
| Launch (Stage 1) | **≤ 5 min** | **≤ 4 h** | pgBackRest: continuous WAL archiving to an **off-site** encrypted repository, plus daily full/diff backups |
| Growth (Stage 2) | ≤ 1 min (async replica) | ≤ 1 h | Streaming replica + documented, rehearsed promotion |
| Later | ≈ 0 for committed payments (synchronous replica for finance) | ≤ 15 min | Synchronous commit for the finance database, automated failover (Patroni) — only when justified |

The ledger is the asset that matters most. **A lost payment record is worse than downtime.** Provider statements are the independent second copy that lets reconciliation detect any gap after a restore (§5).

## 2. What is backed up

| Asset | Method | Frequency | Retention | Encrypted |
|---|---|---|---|---|
| PostgreSQL (all planes) | pgBackRest full (weekly) + differential (daily) + WAL (continuous) | continuous | 35 days PITR; monthly fulls for 12 months | ✓ (repository cipher, key in the private ops secrets) |
| Object store (media, documents, statements) | Versioned bucket + nightly replication to the off-site target | nightly | 90 days of versions | ✓ |
| Redis | Not backed up for recovery. It is disposable by design: the platform must fully recover from Postgres. AOF is kept only for fast restart. | — | — | — |
| Configuration | Git (this repo + private ops repo) | on change | forever | ops repo encrypted |
| Secrets | KEK, backup cipher key, tunnel credentials, Cloudflare token: **escrowed offline** (password manager + sealed paper copy in two locations) | on rotation | current + previous | ✓ |
| Cloudflare zone config | Terraform state (encrypted remote state in the ops repo or an off-site bucket) | on change | versioned | ✓ |

**Off-site** means a different physical site and failure domain from VM-DATA: a second location or NAS, or an encrypted S3-compatible bucket with a third-party provider. The choice is **Q5**. A backup on the same disk or box **does not count** (lesson `00` §6.3).

## 3. Automated restore verification

**Weekly job**, on a scratch VM or container:

1. Restore the latest backup plus WAL to a timestamp 10 minutes ago.
2. Run integrity checks:
   - `amcheck` on indexes
   - row counts versus production (within the expected drift)
   - **the ledger trial balance must be 0 for every currency**
   - `account_balances` rebuild must match
   - the latest `provider_events` must be present
3. Publish the result as a metric, which alerts on failure. Record the actual restore duration as the **measured RTO** for the database step.

A **manual game-day drill** runs quarterly, following §4 end-to-end on staging, and the results are recorded in `docs/runbooks/dr-drills.md`.

## 4. Scenarios and procedures

| Scenario | Procedure (summary; full runbooks in Phase 1) |
|---|---|
| **App VM lost** | Provision a new VM with Ansible (cloud-init + playbook), place the tunnel credentials, deploy the current release digest. The tunnel reconnects and **no DNS changes are needed**. Target: < 1 h. |
| **Data VM lost** | Provision a VM, restore with pgBackRest from off-site to the latest WAL, verify (§3), repoint pgbouncer, start the apps in *read-only maintenance*, reconcile (§5), then open. Target: < 4 h. |
| **Bad migration or data corruption** | Stop writes (maintenance flag), PITR to a *new* instance just before the incident, diff affected tables, and roll forward corrective changes into production. Never overwrite production blindly. |
| **Tunnel credentials lost** | Create a new tunnel with Terraform/API, update DNS CNAME targets through the `edge` reconciler (all records carry the `arada:` marker), and rotate. Target: < 30 min. |
| **Cloudflare account compromise** | Revoke tokens, rotate tunnel credentials, restore zone configuration from Terraform, audit DNS for injected records. Registrar (Hostinger) account security is MFA-protected and independent. |
| **Bot token compromise** | `replaceManagedBotToken` (managed) or a guided BotFather revoke (BYO). Restore the webhook, audit sessions issued in the window, and, if forged `initData` is suspected, revoke all sessions of that tenant (the Ed25519 check should already block forgery). |
| **KEK compromise or loss** | Loss: restore from escrow. Compromise: generate a new KEK, re-wrap all DEKs, rotate all third-party credentials the KEK protected (provider keys, bot tokens). |
| **Ransomware on a host** | Rebuild hosts from Ansible. Backups are safe because the off-site repository is **append-only / object-locked** and the backup credentials cannot delete. |

## 5. Post-restore financial reconciliation (mandatory before reopening checkout)

1. Find the restore point `T`.
2. For every payment configuration, fetch provider transactions from `T − 1h` to now, using `fetch_status` or the statements API.
3. Any provider success not present in `finance.provider_events` is re-ingested through the **normal** webhook-processing path. It is idempotent, so replays are safe.
4. Any refund or payout sent after `T` is re-recorded from the provider records.
5. Reconciliation must show 100% matched, or have open items assigned, before checkout re-opens.
6. Notify affected merchants with the gap window.

## 6. Responsibilities

Until an ops team exists, the Super Admin owns DR decisions, and this document plus the runbooks must let a competent engineer execute them without prior context. Every runbook states: trigger, prerequisites, exact commands, verification, rollback, and who to notify.
