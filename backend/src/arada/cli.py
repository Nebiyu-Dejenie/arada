"""``arada`` command-line interface (operations only; never a bypass of RBAC).

Secrets are read from the environment or an interactive prompt, never from
command-line arguments (which leak into shell history and process lists).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from arada.kernel.config import Environment, get_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(owner_url: str) -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    cfg.attributes["owner_url"] = owner_url
    return cfg


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"error: environment variable {name} is required")
    return value


def cmd_db_bootstrap_roles(_: argparse.Namespace) -> int:
    from arada.ops.db_bootstrap import RolePasswords, bootstrap_roles

    asyncio.run(
        bootstrap_roles(
            _require_env("ARADA_DB_SUPERUSER_URL"),
            _require_env("ARADA_DB_NAME"),
            RolePasswords(
                owner=_require_env("ARADA_DB_OWNER_PASSWORD"),
                app=_require_env("ARADA_DB_APP_PASSWORD"),
                reader=_require_env("ARADA_DB_READER_PASSWORD"),
            ),
        )
    )
    print("database roles bootstrapped")
    return 0


def cmd_db_upgrade(args: argparse.Namespace) -> int:
    command.upgrade(_alembic_config(_require_env("ARADA_DATABASE_OWNER_URL")), args.revision)
    print(f"database upgraded to {args.revision}")
    return 0


def cmd_db_downgrade(args: argparse.Namespace) -> int:
    if os.environ.get("ARADA_ENVIRONMENT", "development") == Environment.PRODUCTION.value:
        sys.exit("error: downgrade is disabled in production; roll forward instead")
    command.downgrade(_alembic_config(_require_env("ARADA_DATABASE_OWNER_URL")), args.revision)
    print(f"database downgraded to {args.revision}")
    return 0


def cmd_config_check(_: argparse.Namespace) -> int:
    settings = get_settings()
    print(f"environment={settings.environment.value}")
    print(f"root_domain={settings.root_domain or 'TBD'}")
    print(f"require_mfa_for_privileged_scopes={settings.require_mfa_for_privileged_scopes}")
    print("configuration OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arada", description="ARADA platform operations")
    sub = parser.add_subparsers(dest="group", required=True)

    db = sub.add_parser("db", help="database operations").add_subparsers(dest="cmd", required=True)
    db.add_parser(
        "bootstrap-roles", help="create/repair database roles (superuser DSN)"
    ).set_defaults(func=cmd_db_bootstrap_roles)
    up = db.add_parser("upgrade", help="apply migrations")
    up.add_argument("--revision", default="head")
    up.set_defaults(func=cmd_db_upgrade)
    down = db.add_parser("downgrade", help="revert migrations (never in production)")
    down.add_argument("--revision", required=True)
    down.set_defaults(func=cmd_db_downgrade)

    cfg = sub.add_parser("config", help="configuration").add_subparsers(dest="cmd", required=True)
    cfg.add_parser("check", help="validate configuration").set_defaults(func=cmd_config_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
