"""Owner-run conformance check of a live Telegram *test-environment* sample.

Telegram publishes no test vectors, and two points of the Mini App protocol
are not stated by the official docs (assumption A8: values are percent-decoded
as form data, and signed over their UTF-8 bytes). The only proof that ARADA's
validator matches Telegram is a real sample. Run this on the developer
workstation, right after opening a test bot's Mini App:

    cd backend && uv run python ../scripts/telegram_sample_check.py

It prompts for the bot id, the bot token, the raw ``Telegram.WebApp.initData``
string and Telegram's public key for the environment, all with hidden input.
A hidden terminal prompt can silently cut a long line (1024 bytes on macOS),
so a long sample is better piped in, for example from the clipboard:

    pbpaste | uv run python ../scripts/telegram_sample_check.py --init-data-stdin

Either way the script prints the length it received: compare it with
``Telegram.WebApp.initData.length`` in the Mini App before trusting a verdict.
It **prints no values** (no token, no initData, no hash, no name), writes
nothing to disk and makes no network call. If the strict parse rejects the
sample, it names the rule that failed, never the offending value. Nothing from it may be committed:
the sample contains personal data and the repository is public
(PHASE_2_PLAN.md §4). Use a Telegram account and bot in the **test**
environment, never production credentials. For A8, use a first or last name
with non-ASCII characters (for example Amharic) and a space.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from arada.kernel.config import TELEGRAM_KEY_FINGERPRINTS
from arada.telegram import miniapp


def _variant_fields(raw: str, decode: str) -> dict[str, str] | None:
    """Alternative readings of the query string, to confirm or refute A8."""
    fields: dict[str, str] = {}
    for pair in raw.split("&"):
        key, sep, value = pair.partition("=")
        if not sep:
            return None
        if decode == "raw":
            fields[key] = value
        elif decode == "percent-only":  # '+' kept as '+'
            fields[unquote(key)] = unquote(value)
        else:
            return None
    return fields


def diagnose_parse(raw: str) -> list[str]:
    """Why the strict parse (A8) refuses ``raw``: rule names and protocol field
    names only, never a value, so the owner can report a failure safely."""
    findings: list[str] = []
    if len(raw) > miniapp.MAX_INIT_DATA_BYTES:
        findings.append(f"longer than {miniapp.MAX_INIT_DATA_BYTES} characters")
    disallowed = {c for c in raw if not miniapp._RAW.fullmatch(c)}
    if disallowed:
        ascii_chars = sorted(repr(c) for c in disallowed if c.isascii())
        non_ascii = sum(1 for c in raw if not c.isascii())
        findings.append(
            f"disallowed raw characters (not percent-encoded): ASCII {ascii_chars}, "
            f"non-ASCII x{non_ascii}"
        )
    pairs = raw.split("&")
    if len(pairs) > miniapp.MAX_FIELDS:
        findings.append(f"more than {miniapp.MAX_FIELDS} fields")
    seen: set[str] = set()
    for index, pair in enumerate(pairs):
        key_part, sep, value_part = pair.partition("=")
        if not sep:
            findings.append(f"pair #{index + 1}: pair without '='")
            continue
        try:
            key = miniapp._decode_component(key_part)
        except miniapp.InitDataRejected:
            findings.append(f"pair #{index + 1}: field name does not decode")
            continue
        if not miniapp._KEY.fullmatch(key):
            findings.append(
                f"pair #{index + 1}: field name outside [A-Za-z0-9_]{{1,64}} (length {len(key)})"
            )
            continue
        if key in seen:
            findings.append(f"duplicate field '{key}'")
        seen.add(key)
        if miniapp._BAD_ESCAPE.search(value_part):
            findings.append(f"field '{key}': invalid percent escape")
            continue
        try:
            miniapp._decode_component(value_part)
        except miniapp.InitDataRejected:
            findings.append(f"field '{key}': not UTF-8 after percent-decoding")
        except UnicodeEncodeError:
            pass  # a non-ASCII raw character, already reported above
    return findings or ["no specific rule identified"]


def _hmac_ok(fields: dict[str, str], token: str) -> bool:
    expected = miniapp.expected_hash(fields, token)
    try:
        received = bytes.fromhex(fields.get("hash", ""))
    except ValueError:
        return False
    return hmac.compare_digest(received, expected)


def _signature_ok(fields: dict[str, str], bot_id: int, key: Ed25519PublicKey) -> bool:
    try:
        signature = miniapp.decode_signature(fields.get("signature", ""))
        key.verify(signature, miniapp.signed_message(fields, bot_id))
    except (miniapp.InitDataRejected, InvalidSignature, ValueError):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a live Telegram test-environment sample.")
    parser.add_argument(
        "--init-data-stdin",
        action="store_true",
        help="read the raw initData from standard input (avoids terminal line limits)",
    )
    args = parser.parse_args([] if argv is None else argv)
    bot_id = int(getpass.getpass("Test bot id (digits): ").strip())
    token = getpass.getpass("Test bot token: ").strip()
    if args.init_data_stdin:
        raw = sys.stdin.read().strip()
    else:
        raw = getpass.getpass("Raw Telegram.WebApp.initData: ").strip()
    key_hex = getpass.getpass("Telegram public key (hex) for this environment: ").strip().lower()

    environment = TELEGRAM_KEY_FINGERPRINTS.get(hashlib.sha256(bytes.fromhex(key_hex)).hexdigest())
    print(f"key: Telegram {environment or 'UNKNOWN (not a documented Telegram key)'} key")
    if environment != "test":
        print("refusing: run this with the TEST environment key and a test bot only")
        return 2
    key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))

    print(f"received initData: {len(raw)} characters (must equal Telegram.WebApp.initData.length)")
    try:
        fields = miniapp.parse(raw)
    except miniapp.InitDataRejected as exc:
        print(f"parse (A8 strict form decoding): REJECTED ({exc.reason})")
        for finding in diagnose_parse(raw):
            print(f"  - {finding}")
        fields = {}
    else:
        print(f"parse (A8 strict form decoding): ok; field names: {sorted(fields)}")

    print("\nWhich reading of the data does Telegram's hash and signature match?")
    readings = {"A8 (form-decoded, UTF-8)": fields or None}
    for variant in ("raw", "percent-only"):
        readings[f"alternative: {variant}"] = _variant_fields(raw, variant)
    for label, candidate in readings.items():
        if candidate is None:
            print(f"  {label:32} n/a")
            continue
        print(
            f"  {label:32} HMAC {'MATCH' if _hmac_ok(candidate, token) else 'no'}"
            f" · Ed25519 {'MATCH' if _signature_ok(candidate, bot_id, key) else 'no'}"
        )

    print("\nSample coverage for A8 (yes/no only):")
    print(f"  raw contains '+':          {'+' in raw}")
    print(f"  raw contains '%20':        {'%20' in raw}")
    user = fields.get("user", "")
    print(f"  user has non-ASCII text:   {not user.isascii()}")
    print(f"  user has a space:          {' ' in user}")
    print(f"  signature padded with '=': {fields.get('signature', '').endswith('=')}")
    print(
        f"  hash is lower-case hex:    {fields.get('hash', '') == fields.get('hash', '').lower()}"
    )

    try:
        verified = miniapp.verify(
            raw,
            bot_id=bot_id,
            bot_token=token,
            public_key=key,
            now=datetime.now(UTC),
            max_age=timedelta(hours=1),
            future_skew=timedelta(seconds=60),
        )
    except miniapp.InitDataRejected as exc:
        print(f"\nARADA validator verdict: REJECTED ({exc.reason})")
        return 1
    age = int((datetime.now(UTC) - verified.auth_date).total_seconds())
    print(f"\nARADA validator verdict: ACCEPTED (auth_date {age} s ago)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
