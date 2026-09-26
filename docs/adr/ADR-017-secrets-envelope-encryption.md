# ADR-017: Secrets: envelope encryption with AAD; infrastructure secrets outside this repo

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
Per-record data keys (AES-256-GCM) with AAD binding each ciphertext to its table, row and tenant, wrapped by a versioned key-encryption key held outside the database and image. Infrastructure secrets live in a separate private operations repository (SOPS/age or Ansible Vault).

## Context
Bot tokens and provider credentials are per merchant; this repository is public (Permanent §28).

## Alternatives
Plaintext environment variables per merchant; Vault on day one.

## Reason
Ciphertext cannot be swapped across tenants; key rotation is a re-wrap.

## Consequences
Secret recovery depends on offline escrow of the key-encryption key.
