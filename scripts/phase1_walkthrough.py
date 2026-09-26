#!/usr/bin/env python3
"""Phase 1 Definition-of-Done walkthrough, over HTTP only, against a running stack.

Runs the owner's acceptance sequence end to end and asserts every step:
platform identity -> MFA -> vertical -> versioned blueprint -> two tenants ->
owners, admins and staff via invitations -> blueprint assignment ->
permissions enforced -> tenant isolation -> feature flags -> audit records.

Usage (normally through scripts/phase1_demo.sh, which prepares a fresh stack):
    ARADA_DEMO_USERNAME=... ARADA_DEMO_PASSWORD=... \
    python scripts/phase1_walkthrough.py --base-url http://127.0.0.1:58100

The password comes from the environment, never argv. Exit status 0 means
every step passed.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pyotp
import yaml

SEEDS = Path(__file__).resolve().parents[1] / "blueprints" / "phones"
RESULTS: list[tuple[str, bool, str]] = []


class StepFailed(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise StepFailed(message)


def step(name: str) -> Any:
    def decorator(fn: Any) -> Any:
        def run(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except (StepFailed, AssertionError, httpx.HTTPError) as exc:
                RESULTS.append((name, False, str(exc)))
                report()
                sys.exit(1)
            RESULTS.append((name, True, f"{(time.perf_counter() - started) * 1000:.0f} ms"))
            return result

        return run

    return decorator


def report() -> None:
    width = max(len(n) for n, _, _ in RESULTS)
    print("\nPhase 1 walkthrough")
    print("-" * (width + 30))
    for name, ok, note in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {note}")
    print("-" * (width + 30))
    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"{passed}/{len(RESULTS)} steps passed")


class Actor:
    def __init__(self, client: httpx.Client, username: str, password: str) -> None:
        self.client = client
        self.username = username
        self.password = password
        self.token: str | None = None
        self.totp: pyotp.TOTP | None = None
        self._last_step = -1

    @property
    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def code(self) -> str:
        if self.totp is None:
            raise StepFailed("TOTP not enrolled")
        step_no = max(int(time.time() // 30), self._last_step + 1)
        self._last_step = step_no
        return self.totp.at(step_no * 30)

    def login(self) -> None:
        body: dict[str, Any] = {"username": self.username, "password": self.password}
        if self.totp:
            body["totp_code"] = self.code()
        r = self.client.post("/v1/auth/login", json=body)
        check(r.status_code == 200, f"login {self.username}: {r.status_code} {r.text}")
        self.token = r.json()["access_token"]


def expect(r: httpx.Response, status: int, what: str) -> Any:
    check(r.status_code == status, f"{what}: expected {status}, got {r.status_code} {r.text[:300]}")
    return r.json() if r.content else None


def seed(version: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((SEEDS / f"{version}.yaml").read_text())
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:58000")
    parser.add_argument("--state-file", help="write non-secret ids (and test logins) for tooling")
    args = parser.parse_args()
    username = os.environ["ARADA_DEMO_USERNAME"]
    password = os.environ["ARADA_DEMO_PASSWORD"]
    suffix = secrets.token_hex(3)

    client = httpx.Client(base_url=args.base_url, timeout=30)
    root = Actor(client, username, password)
    world: dict[str, Any] = {"tenants": {}}

    @step("1. application healthy and database ready")
    def health() -> None:
        expect(client.get("/healthz"), 200, "healthz")
        expect(client.get("/readyz"), 200, "readyz")

    @step("2. platform identity logs in and enrols TOTP (MFA)")
    def identity() -> None:
        root.login()
        denied = client.post(
            "/v1/platform/verticals", headers=root.h, json={"key": "probe", "name_en": "P"}
        )
        expect(denied, 403, "platform action before MFA")
        enrol = expect(client.post("/v1/me/mfa/totp", headers=root.h), 200, "totp enrol")
        root.totp = pyotp.TOTP(enrol["secret"])
        expect(
            client.post("/v1/me/mfa/totp/confirm", headers=root.h, json={"code": root.code()}),
            204,
            "totp confirm",
        )
        me = expect(client.get("/v1/me", headers=root.h), 200, "me")
        check(me["roles"]["platform"] == ["SUPER_ADMIN"], "super admin role")
        check(me["mfa"]["session_verified"], "session MFA-verified")

    @step("3. vertical and versioned blueprint (Phones 1.0.0, 1.1.0) published")
    def blueprint() -> None:
        world["vertical"] = f"phones_{suffix}"
        expect(
            client.post(
                "/v1/platform/verticals",
                headers=root.h,
                json={"key": world["vertical"], "name_en": "Phones", "name_am": "ስልኮች"},
            ),
            201,
            "vertical",
        )
        bp = expect(
            client.post(
                "/v1/platform/blueprints",
                headers=root.h,
                json={"vertical": world["vertical"], "key": "retail", "name_en": "Retail phones"},
            ),
            201,
            "blueprint",
        )
        world["blueprint"] = bp["id"]
        world["versions"] = {}
        for version in ("1.0.0", "1.1.0"):
            draft = expect(
                client.post(
                    f"/v1/platform/blueprints/{bp['id']}/versions",
                    headers=root.h,
                    json={"version": version, "definition": seed(version)},
                ),
                201,
                f"draft {version}",
            )
            published = expect(
                client.post(
                    f"/v1/platform/blueprints/{bp['id']}/versions/{draft['id']}:publish",
                    headers=root.h,
                ),
                200,
                f"publish {version}",
            )
            world["versions"][version] = draft["id"]
            check(
                published["change_level"] in {"initial", "minor"},
                f"{version} classified {published['change_level']}",
            )
        disguised = expect(
            client.post(
                f"/v1/platform/blueprints/{bp['id']}/versions",
                headers=root.h,
                json={"version": "1.2.0", "definition": seed("2.0.0")},
            ),
            201,
            "disguised draft",
        )
        expect(
            client.post(
                f"/v1/platform/blueprints/{bp['id']}/versions/{disguised['id']}:publish",
                headers=root.h,
            ),
            409,
            "breaking change as minor refused",
        )

    @step("4. tenants A and B created, each pinned to Phones 1.0.0")
    def tenants() -> None:
        for key, name in (("a", "ABC Phones"), ("b", "XYZ Phones")):
            slug = f"{key * 3}-phones-{suffix}"
            created = expect(
                client.post(
                    "/v1/platform/tenants",
                    headers=root.h,
                    json={
                        "slug": slug,
                        "display_name": name,
                        "vertical": world["vertical"],
                        "blueprint_version_id": world["versions"]["1.0.0"],
                    },
                ),
                201,
                f"tenant {key}",
            )
            check(created["tenant"]["blueprint_version"] == "1.0.0", "pinned to 1.0.0")
            world["tenants"][key] = {
                "id": created["tenant"]["id"],
                "slug": slug,
                "owner_token": created["owner_invitation"]["token"],
            }

    def join(token: str, role_hint: str) -> Actor:
        uname = f"{role_hint}{secrets.token_hex(3)}"
        pw = secrets.token_urlsafe(18)
        expect(
            client.post(
                "/v1/invitations:accept",
                json={
                    "token": token,
                    "new_account": {"username": uname, "password": pw, "display_name": uname},
                },
            ),
            200,
            f"accept {role_hint}",
        )
        actor = Actor(client, uname, pw)
        actor.login()
        return actor

    @step("5. owners, admins and staff join via invitations; tenants activated")
    def roles() -> None:
        for key, t in world["tenants"].items():
            owner = join(t["owner_token"], f"owner{key}")
            admin_inv = expect(
                client.post(
                    f"/v1/t/{t['slug']}/invitations",
                    headers=owner.h,
                    json={"roles": ["TENANT_ADMIN"]},
                ),
                201,
                "invite admin",
            )
            admin = join(admin_inv["token"], f"admin{key}")
            staff_inv = expect(
                client.post(
                    f"/v1/t/{t['slug']}/invitations",
                    headers=admin.h,
                    json={"roles": ["TENANT_STAFF"]},
                ),
                201,
                "invite staff",
            )
            staff = join(staff_inv["token"], f"staff{key}")
            expect(
                client.post(f"/v1/platform/tenants/{t['id']}:activate", headers=root.h),
                200,
                "activate",
            )
            t.update(owner=owner, admin=admin, staff=staff)
            members = expect(
                client.get(f"/v1/t/{t['slug']}/staff", headers=admin.h), 200, "staff list"
            )
            t["memberships"] = {m["username"]: m["membership_id"] for m in members}
            check(len(members) == 3, "three members")

    @step("6. blueprint assigned explicitly: A -> 1.1.0, B stays on 1.0.0")
    def assign() -> None:
        a, b = world["tenants"]["a"], world["tenants"]["b"]
        moved = expect(
            client.post(
                f"/v1/platform/tenants/{a['id']}/blueprint-assignment",
                headers=root.h,
                json={
                    "blueprint_version_id": world["versions"]["1.1.0"],
                    "reason": "adopt battery health",
                },
            ),
            200,
            "assign",
        )
        check(moved["blueprint_version"] == "1.1.0", "A on 1.1.0")
        b_now = expect(client.get(f"/v1/t/{b['slug']}", headers=b["admin"].h), 200, "B detail")
        check(b_now["blueprint_version"] == "1.0.0", "B unchanged on 1.0.0")

    @step("7. permissions enforced server-side (admin can, staff cannot)")
    def permissions() -> None:
        a = world["tenants"]["a"]
        current = client.get(f"/v1/t/{a['slug']}", headers=a["admin"].h)
        etag = current.headers["etag"]
        expect(
            client.patch(
                f"/v1/t/{a['slug']}/profile",
                headers={**a["staff"].h, "If-Match": etag},
                json={"tagline": "staff try"},
            ),
            403,
            "staff edits profile",
        )
        expect(
            client.post(
                f"/v1/t/{a['slug']}/invitations",
                headers=a["staff"].h,
                json={"roles": ["TENANT_STAFF"]},
            ),
            403,
            "staff invites",
        )
        expect(
            client.post(
                f"/v1/t/{a['slug']}/invitations",
                headers=a["admin"].h,
                json={"roles": ["TENANT_OWNER"]},
            ),
            403,
            "admin mints owner",
        )
        expect(
            client.patch(
                f"/v1/t/{a['slug']}/profile",
                headers={**a["admin"].h, "If-Match": etag},
                json={"tagline": "Genuine phones"},
            ),
            200,
            "admin edits profile",
        )
        expect(
            client.get("/v1/platform/tenants", headers=a["owner"].h),
            403,
            "tenant owner on platform",
        )

    @step("8. tenant isolation: A cannot read, change or probe B")
    def isolation() -> None:
        a, b = world["tenants"]["a"], world["tenants"]["b"]
        before = expect(client.get(f"/v1/t/{b['slug']}", headers=b["owner"].h), 200, "B before")
        for actor in ("owner", "admin", "staff"):
            h = a[actor].h
            expect(client.get(f"/v1/t/{b['slug']}", headers=h), 404, f"A {actor} reads B")
            expect(
                client.patch(
                    f"/v1/t/{b['slug']}/profile",
                    headers={**h, "If-Match": '"1"'},
                    json={"tagline": "pwned"},
                ),
                404,
                f"A {actor} edits B",
            )
            expect(
                client.get(f"/v1/t/{b['slug']}/staff", headers=h), 404, f"A {actor} lists B staff"
            )
        b_member = next(iter(b["memberships"].values()))
        expect(
            client.put(
                f"/v1/t/{a['slug']}/staff/{b_member}/roles",
                headers=a["admin"].h,
                json={"roles": ["TENANT_STAFF"]},
            ),
            404,
            "IDOR with B membership id",
        )
        spoof = expect(
            client.get(f"/v1/t/{a['slug']}", headers={**a["admin"].h, "X-Tenant-ID": b["id"]}),
            200,
            "spoofed header",
        )
        check(spoof["id"] == a["id"], "header ignored")
        after = expect(client.get(f"/v1/t/{b['slug']}", headers=b["owner"].h), 200, "B after")
        check(before["profile"] == after["profile"], "B unchanged")

    @step("9. feature flags: tenant override for A only")
    def flags() -> None:
        a, b = world["tenants"]["a"], world["tenants"]["b"]
        expect(
            client.put(
                "/v1/platform/feature-flags/ai/overrides",
                headers=root.h,
                json={
                    "scope_type": "tenant",
                    "tenant": a["slug"],
                    "enabled": True,
                    "reason": "pilot",
                },
            ),
            204,
            "override",
        )
        fa = {
            f["key"]: f
            for f in expect(
                client.get(f"/v1/t/{a['slug']}/features", headers=a["staff"].h), 200, "A flags"
            )
        }
        fb = {
            f["key"]: f
            for f in expect(
                client.get(f"/v1/t/{b['slug']}/features", headers=b["staff"].h), 200, "B flags"
            )
        }
        check(fa["ai"]["enabled"] and fa["ai"]["source"] == "tenant", "A has ai")
        check(not fb["ai"]["enabled"], "B does not")
        check(fa["reviews"]["source"] == "blueprint", "blueprint default applies")

    @step("10. audit records generated and tenant-isolated")
    def audit() -> None:
        a, b = world["tenants"]["a"], world["tenants"]["b"]
        events = expect(
            client.get(
                f"/v1/t/{a['slug']}/audit-events", headers=a["admin"].h, params={"limit": 200}
            ),
            200,
            "A audit",
        )
        actions = {e["action"] for e in events}
        for needed in (
            "tenant.created",
            "tenant.invitation_accepted",
            "tenant.activated",
            "tenant.blueprint_assigned",
            "tenant.profile_updated",
            "feature_flag.override_set",
        ):
            check(needed in actions, f"missing audit action {needed}")
        check(all(e["tenant_id"] == a["id"] for e in events), "A sees only A")
        check(all(e["request_id"] and e["trace_id"] for e in events), "events correlated")
        platform = expect(
            client.get("/v1/platform/audit-events", headers=root.h, params={"limit": 200}),
            200,
            "platform audit",
        )
        seen = {e["tenant_id"] for e in platform}
        check({a["id"], b["id"]} <= seen, "platform audit spans tenants")
        expect(
            client.get(f"/v1/t/{a['slug']}/audit-events", headers=a["staff"].h),
            403,
            "staff cannot read audit",
        )

    for fn in (
        health,
        identity,
        blueprint,
        tenants,
        roles,
        assign,
        permissions,
        isolation,
        flags,
        audit,
    ):
        fn()
    report()

    if args.state_file:
        a = world["tenants"]["a"]
        Path(args.state_file).write_text(
            json.dumps(
                {
                    "base_url": args.base_url,
                    "tenant_slug": a["slug"],
                    "username": a["staff"].username,
                    "password": a["staff"].password,
                }
            )
        )


if __name__ == "__main__":
    main()
