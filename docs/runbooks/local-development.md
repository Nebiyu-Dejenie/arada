# Runbook: local development and reproduction

Audience: engineers working on the ARADA backend. Requirements: Linux or WSL2, Docker with Compose v2, and [uv](https://docs.astral.sh/uv/). Python 3.12 is used through uv.

## 1. First run (from a fresh clone)

```bash
./scripts/init-env.sh                 # generates .env with random local secrets (gitignored, mode 600)
docker compose up -d --build --wait   # postgres -> role bootstrap -> migrations -> api
curl -s http://127.0.0.1:58000/readyz # {"status":"ready","database":"ok"}
```

Ports are bound to `127.0.0.1` only: the API on `ARADA_API_PORT` (default 58000) and PostgreSQL on `ARADA_PG_PORT` (default 55432). Change them in `.env` if another project already uses them.

## 2. Create the platform owner (once per database)

```bash
docker compose exec -e ARADA_BOOTSTRAP_PASSWORD='<a strong password>' api \
  arada admin bootstrap-superadmin --username owner --display-name "Platform Owner"
```

Then log in (`POST /v1/auth/login`), enrol TOTP (`POST /v1/me/mfa/totp` and `/confirm`), and log in again with a code. **Platform permissions are withheld until the session is MFA-verified.** API docs: `http://127.0.0.1:58000/docs` (off in production).

## 3. Tests and quality gates (same as CI)

```bash
cd backend
uv sync --frozen
uv run ruff check . ../scripts && uv run ruff format --check . ../scripts
uv run mypy
uv run lint-imports
uv run pytest -q                      # needs the compose postgres; each run creates and drops its own database
```

Set `ARADA_TEST_KEEP_DB=1` to keep the test database for inspection.

## 4. Reproduce Phase 1 from zero

```bash
./scripts/phase1_demo.sh
```

This builds the image, starts an **isolated** stack (its own project, volume, ports and secrets), migrates from zero, bootstraps the platform identity, runs the ten-step Definition-of-Done walkthrough over HTTP, and tears everything down. Set `ARADA_DEMO_KEEP=1` to keep the stack.

## 5. Indicative performance

```bash
ARADA_DEMO_KEEP=1 ARADA_DEMO_STATE=/tmp/state.json ./scripts/phase1_demo.sh
backend/.venv/bin/python scripts/measure_api.py --state-file /tmp/state.json
```

Numbers from a developer laptop are **not** sizing numbers (ADR-004 Evidence). Real sizing is measured on the target machines.

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `port is already allocated` | Another project uses the port. Change `ARADA_API_PORT` / `ARADA_PG_PORT` in `.env`. |
| Tests fail with "database tests need PostgreSQL" | Run `./scripts/init-env.sh && docker compose up -d --wait postgres`. |
| `403 mfa-required-for-scope` as super admin | Enrol and confirm TOTP in this session, or log in with a TOTP code. |
| `404` on another tenant's URL | Expected: non-members cannot see tenants (`02_TENANCY.md` §4). |
| Migrations fail with a role error | Roles are created by `arada db bootstrap-roles` (the `db-bootstrap` service). Run it before `arada db upgrade`. |
