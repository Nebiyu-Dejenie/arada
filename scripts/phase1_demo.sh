#!/usr/bin/env bash
# Phase 1 Definition of Done, from nothing: a fresh, isolated stack is built
# from the repository, migrated from zero, bootstrapped, walked through, and
# (unless ARADA_DEMO_KEEP=1) destroyed again.
#
#   ./scripts/phase1_demo.sh
#
# Uses its own compose project, volume, ports and throwaway secrets, so it
# never touches the developer stack. Requires Docker and uv.
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT="${ARADA_DEMO_PROJECT:-arada-demo-$RANDOM}"
API_PORT="${ARADA_DEMO_API_PORT:-58100}"
PG_PORT="${ARADA_DEMO_PG_PORT:-55532}"
WORK="$(mktemp -d)"
ENV_FILE="$WORK/demo.env"
STATE_FILE="${ARADA_DEMO_STATE:-$WORK/state.json}"

hex() { python3 -c 'import secrets; print(secrets.token_hex(24))'; }
{
  echo "ARADA_PG_SUPERUSER_PASSWORD=$(hex)"
  echo "ARADA_DB_OWNER_PASSWORD=$(hex)"
  echo "ARADA_DB_APP_PASSWORD=$(hex)"
  echo "ARADA_DB_READER_PASSWORD=$(hex)"
  echo "ARADA_KEK_BASE64=$(python3 -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')"
  echo "ARADA_PG_PORT=$PG_PORT"
  echo "ARADA_API_PORT=$API_PORT"
  echo "ARADA_IMAGE=arada-platform:$PROJECT"
} >"$ENV_FILE"
chmod 600 "$ENV_FILE"

compose() { docker compose --env-file "$ENV_FILE" -p "$PROJECT" "$@"; }
cleanup() {
  if [[ "${ARADA_DEMO_KEEP:-0}" != "1" ]]; then
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    docker image rm "arada-platform:$PROJECT" >/dev/null 2>&1 || true
    rm -rf "$WORK"
  else
    echo "kept: project=$PROJECT env=$ENV_FILE"
  fi
}
trap cleanup EXIT

echo "==> [1/5] build image and start a fresh stack ($PROJECT)"
compose up -d --build --wait

echo "==> [2/5] migrations applied from zero:"
compose logs migrate --no-log-prefix | tail -1

echo "==> [3/5] bootstrap the platform identity (CLI, once)"
export ARADA_DEMO_USERNAME="owner-$RANDOM"
ARADA_DEMO_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
export ARADA_DEMO_PASSWORD
compose exec -T -e ARADA_BOOTSTRAP_PASSWORD="$ARADA_DEMO_PASSWORD" api \
  arada admin bootstrap-superadmin --username "$ARADA_DEMO_USERNAME" --display-name "Platform Owner"

echo "==> [4/5] install walkthrough dependencies"
(cd backend && uv sync --frozen --quiet)

echo "==> [5/5] run the Definition-of-Done walkthrough over HTTP"
backend/.venv/bin/python scripts/phase1_walkthrough.py \
  --base-url "http://127.0.0.1:$API_PORT" --state-file "$STATE_FILE"
