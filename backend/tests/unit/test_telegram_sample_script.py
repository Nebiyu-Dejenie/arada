"""The owner's live-sample checker prints verdicts, never values."""

from __future__ import annotations

import hashlib
import importlib.util
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
