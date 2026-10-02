"""The owner's live-sample checker prints verdicts, never values."""

from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
from types import ModuleType

import pytest

from tests.telegram_kit import Signer, encode, fake_bot

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "telegram_sample_check.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("telegram_sample_check", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answers: list[str],
    fingerprints: dict[str, str],
) -> tuple[int, str]:
    script = load()
    replies = iter(answers)
    monkeypatch.setattr(script.getpass, "getpass", lambda _prompt: next(replies))
    monkeypatch.setattr(script, "TELEGRAM_KEY_FINGERPRINTS", fingerprints)
    code = script.main()
    return code, capsys.readouterr().out


def test_reports_a8_and_leaks_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    signer = Signer()
    bot_id, token = fake_bot()
    user = {"id": 912345678, "first_name": "ሰላም", "last_name": "ተስፋዬ ገ"}
    fields = signer.fields(bot_id=bot_id, bot_token=token, user=user)
    raw = encode(fields)
    fingerprint = hashlib.sha256(bytes.fromhex(signer.public_hex)).hexdigest()
    code, out = run(
        monkeypatch, capsys, [str(bot_id), token, raw, signer.public_hex], {fingerprint: "test"}
    )
    assert code == 0
    assert "A8 (form-decoded, UTF-8)         HMAC MATCH · Ed25519 MATCH" in out
    assert "ARADA validator verdict: ACCEPTED" in out
    assert "user has non-ASCII text:   True" in out
    for secret in (
        token,
        raw,
        fields["hash"],
        fields["signature"],
        "ሰላም",
        "912345678",
        str(bot_id),
    ):
        assert secret not in out


def test_refuses_anything_but_the_test_environment_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    signer = Signer()
    production = hashlib.sha256(bytes.fromhex(signer.public_hex)).hexdigest()
    for fingerprints in ({production: "production"}, {}):
        code, out = run(
            monkeypatch, capsys, ["1", "t" * 20, "x=1", signer.public_hex], fingerprints
        )
        assert code == 2
        assert "refusing" in out


def test_stdin_mode_takes_a_long_sample_whole_and_reports_its_length(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hidden terminal prompt can silently cut a long line (1024 bytes on macOS),
    which would look like an A8 failure. ``--init-data-stdin`` reads the sample
    from a pipe instead, and the length lets the owner spot any truncation."""
    signer = Signer()
    bot_id, token = fake_bot()
    long_name = "ሰላማዊት ተስፋዬ " * 5  # 60 characters: Telegram allows up to 64
    user = {"id": 912345678, "first_name": long_name, "last_name": long_name}
    raw = encode(signer.fields(bot_id=bot_id, bot_token=token, user=user))
    assert len(raw) > 1024
    fingerprint = hashlib.sha256(bytes.fromhex(signer.public_hex)).hexdigest()
    script = load()
    replies = iter([str(bot_id), token, signer.public_hex])
    monkeypatch.setattr(script.getpass, "getpass", lambda _prompt: next(replies))
    monkeypatch.setattr(script, "TELEGRAM_KEY_FINGERPRINTS", {fingerprint: "test"})
    monkeypatch.setattr(script.sys, "stdin", io.StringIO(raw + "\n"))
    code = script.main(["--init-data-stdin"])
    out = capsys.readouterr().out
    assert code == 0
    assert f"received initData: {len(raw)} characters" in out
    assert "A8 (form-decoded, UTF-8)         HMAC MATCH · Ed25519 MATCH" in out
    for secret in (token, raw, "ሰላማዊት", "912345678"):
        assert secret not in out


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('user={"first_name":"ሰላም"}&auth_date=1', "disallowed raw characters"),
        ("user=%FF&auth_date=1", "field 'user': not UTF-8 after percent-decoding"),
        ("user=%zz&auth_date=1", "field 'user': invalid percent escape"),
        ("auth_date=1&auth_date=2", "duplicate field 'auth_date'"),
        ("auth_date", "pair without '='"),
        ("a-b=1", "field name outside [A-Za-z0-9_]{1,64}"),
        ("query_id=a%0Ab&auth_date=1", "field 'query_id': contains a line feed"),
    ],
)
def test_a_strict_parse_rejection_names_the_rule_never_the_value(raw: str, expected: str) -> None:
    """If the live sample fails the strict parse, the owner must be able to report
    *why* without sharing it."""
    lines = load().diagnose_parse(raw)
    assert any(expected in line for line in lines), lines
    for value in ("ሰላም", "first_name"):
        assert all(value not in line for line in lines)
