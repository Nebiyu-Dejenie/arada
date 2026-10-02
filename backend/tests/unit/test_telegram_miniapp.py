"""Mini App ``initData`` validator: the verified spec, case by case (ADR-012).

Vectors are generated in-test (throwaway Ed25519 key, fake token), so these
tests prove the validator matches our reading of the official text
(PHASE_2_PLAN.md §5). Conformance with Telegram is proven only by the owner's
live test-environment sample, which is never committed.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arada.telegram import miniapp
from arada.telegram.miniapp import InitDataRejected
from tests.telegram_kit import Signer, encode, fake_bot, hmac_hex, login_widget_hash

MAX_AGE = timedelta(hours=1)
SKEW = timedelta(seconds=60)


@pytest.fixture(scope="module")
def signer() -> Signer:
    return Signer()


@pytest.fixture(scope="module")
def bot() -> tuple[int, str]:
    return fake_bot()


def check(
    raw: str,
    signer: Signer,
    bot: tuple[int, str],
    *,
    now: datetime | None = None,
    key: Ed25519PrivateKey | None = None,
) -> miniapp.VerifiedInitData:
    bot_id, token = bot
    return miniapp.verify(
        raw,
        bot_id=bot_id,
        bot_token=token,
        public_key=(key or signer.key).public_key(),
        now=now or datetime.now(UTC),
        max_age=MAX_AGE,
        future_skew=SKEW,
    )


def reason(raw: str, signer: Signer, bot: tuple[int, str], **kwargs: object) -> str:
    with pytest.raises(InitDataRejected) as caught:
        check(raw, signer, bot, **kwargs)  # type: ignore[arg-type]
    return caught.value.reason


def test_a_valid_vector_passes(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, token = bot
    user = {"id": 279058397, "first_name": "Abebe", "last_name": "Kebede", "language_code": "am"}
    verified = check(signer.init_data(bot_id=bot_id, bot_token=token, user=user), signer, bot)
    assert verified.user == miniapp.TelegramUser(279058397, "Abebe", "Kebede", "am")
    assert len(verified.hash) == 32


@pytest.mark.parametrize("field", ["user", "auth_date", "start_param", "query_id"])
def test_tampering_with_any_signed_field_fails(
    signer: Signer, bot: tuple[int, str], field: str
) -> None:
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token, extra={"start_param": "p_abc"})
    values[field] = {
        "user": json.dumps({"id": 1, "first_name": "Mallory"}),
        "auth_date": str(int(time.time()) - 1),
        "start_param": "p_other",
        "query_id": "AAHforged",
    }[field]
    assert reason(encode(values), signer, bot) == "bad_hash"


def test_hmac_valid_but_unsigned_data_forged_with_the_token_fails(
    signer: Signer, bot: tuple[int, str]
) -> None:
    """AUTH-2: anyone holding the token can produce a valid hash, not a signature."""
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token)
    forger = Signer()  # not Telegram's key
    values["signature"] = forger.signature(values, bot_id)
    values["hash"] = hmac_hex(values, token)  # the hash is valid for the forged data
    assert reason(encode(values), signer, bot) == "bad_signature"


def test_signature_for_another_bot_id_fails(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id + 1, bot_token=token)  # signed for another bot
    assert reason(encode(values), signer, bot) == "bad_signature"


def test_hash_made_with_another_bot_token_fails(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, _ = bot
    _, other_token = fake_bot()
    raw = signer.init_data(bot_id=bot_id, bot_token=other_token)
    assert reason(raw, signer, bot) == "bad_hash"


def test_test_environment_signature_is_refused_under_the_production_key(
    signer: Signer, bot: tuple[int, str]
) -> None:
    bot_id, token = bot
    test_environment = Signer()
    raw = test_environment.init_data(bot_id=bot_id, bot_token=token)
    assert check(raw, test_environment, bot).user.id > 0  # valid in its own environment
    assert reason(raw, test_environment, bot, key=signer.key) == "bad_signature"


@pytest.mark.parametrize("missing", ["hash", "signature", "auth_date", "user"])
def test_missing_required_fields_fail(signer: Signer, bot: tuple[int, str], missing: str) -> None:
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token)
    del values[missing]
    assert reason(encode(values), signer, bot) == "malformed"


@pytest.mark.parametrize("duplicated", ["hash", "signature", "user", "auth_date"])
def test_duplicate_fields_fail(signer: Signer, bot: tuple[int, str], duplicated: str) -> None:
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token)
    raw = encode(values) + f"&{duplicated}={quote(values[duplicated], safe='')}"
    assert reason(raw, signer, bot) == "malformed"


def test_stale_future_and_non_integer_auth_date(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, token = bot
    now = int(time.time())
    stale = signer.init_data(bot_id=bot_id, bot_token=token, auth_date=now - 3601)
    assert reason(stale, signer, bot) == "stale"
    just_in = signer.init_data(bot_id=bot_id, bot_token=token, auth_date=now - 3590)
    assert check(just_in, signer, bot)
    future = signer.init_data(bot_id=bot_id, bot_token=token, auth_date=now + 120)
    assert reason(future, signer, bot) == "future"
    skewed = signer.init_data(bot_id=bot_id, bot_token=token, auth_date=now + 30)
    assert check(skewed, signer, bot)
    # Signed but beyond what a timestamp can be (year 10000+): refused, not a crash.
    for bad in ("1.5", "-5", "", "١٢٣", "1e9", " 1", "253402300800", "999999999999"):
        values = signer.fields(bot_id=bot_id, bot_token=token, extra={"auth_date": bad})
        assert reason(encode(values), signer, bot) == "malformed", bad


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "a" * 4097,
        "hash=%zz",
        "user=%E1%88",  # truncated UTF-8 sequence
        "user=%FF",  # not UTF-8
        "auth_date=1&&hash=x",
        "auth_date",  # no '='
        "auth_date=1\nhash=x",
        "auth_date=1&hash=x\x00",
        "bad key=1",
        "k%0A=1",  # newline inside a key
        '{"id":1}',
    ],
)
def test_structurally_malformed_input_fails(signer: Signer, bot: tuple[int, str], raw: str) -> None:
    assert reason(raw, signer, bot) == "malformed"


def test_oversized_but_otherwise_valid_input_fails(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, token = bot
    raw = signer.init_data(bot_id=bot_id, bot_token=token, extra={"padding": "x" * 4096})
    assert reason(raw, signer, bot) == "malformed"


def test_unknown_fields_are_covered_by_hash_and_signature(
    signer: Signer, bot: tuple[int, str]
) -> None:
    """Bot API 10.1 added ``chat_join_request_query_id``; no code change is needed."""
    bot_id, token = bot
    values = signer.fields(
        bot_id=bot_id,
        bot_token=token,
        extra={"chat_join_request_query_id": "123", "chat_type": "private", "future_field": "x"},
    )
    assert check(encode(values), signer, bot)
    values["future_field"] = "y"
    assert reason(encode(values), signer, bot) == "bad_hash"
    dropped = dict(values)
    dropped.pop("chat_type")
    assert reason(encode(dropped), signer, bot) == "bad_hash"


def test_signature_is_in_the_hmac_string_but_not_in_the_signed_message(
    signer: Signer, bot: tuple[int, str]
) -> None:
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token)
    assert "signature=" in miniapp.data_check_string(values, exclude=frozenset({"hash"}))
    assert b"signature=" not in miniapp.signed_message(values, bot_id)
    assert miniapp.signed_message(values, bot_id).startswith(f"{bot_id}:WebAppData\n".encode())
    # A hash computed WITHOUT signature in the string is wrong.
    without = {k: v for k, v in values.items() if k != "signature"}
    values["hash"] = hmac_hex(without, token)
    assert reason(encode(values), signer, bot) == "bad_hash"


def test_hash_letter_case_and_length(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token)
    assert check(encode({**values, "hash": values["hash"].upper()}), signer, bot)
    assert check(encode({**values, "hash": values["hash"].lower()}), signer, bot)
    for bad in (values["hash"][:63], values["hash"] + "0", "g" * 64):
        assert reason(encode({**values, "hash": bad}), signer, bot) == "malformed"


def test_signature_padding_alphabet_and_length(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, token = bot
    padded = signer.fields(bot_id=bot_id, bot_token=token, signature_padding=True)
    assert padded["signature"].endswith("==")
    assert check(encode(padded), signer, bot)
    unpadded = signer.fields(bot_id=bot_id, bot_token=token)
    assert not unpadded["signature"].endswith("=")
    assert check(encode(unpadded), signer, bot)

    def with_signature(value: str) -> str:
        values = dict(unpadded)
        values["signature"] = value
        values["hash"] = hmac_hex(values, token)
        return encode(values)

    standard = unpadded["signature"].replace("-", "+").replace("_", "/")
    if standard != unpadded["signature"]:
        assert reason(with_signature(standard), signer, bot) == "malformed"
    assert reason(with_signature(unpadded["signature"][:-2]), signer, bot) == "malformed"
    assert reason(with_signature(unpadded["signature"] + "="), signer, bot) == "malformed"
    assert reason(with_signature("A" * 85 + "=="), signer, bot) == "malformed"


def test_non_ascii_spaces_and_plus_follow_assumption_a8(
    signer: Signer, bot: tuple[int, str]
) -> None:
    """A8: decoded values, UTF-8 bytes. Confirmed only by the live sample."""
    bot_id, token = bot
    user = {"id": 42, "first_name": "አበበ", "last_name": "ከበደ ወ+ልዴ", "language_code": "am"}
    values = signer.fields(bot_id=bot_id, bot_token=token, user=user)
    for raw in (encode(values), encode(values, plus_for_space=True)):
        verified = check(raw, signer, bot)
        assert verified.user.first_name == "አበበ"
        assert verified.user.last_name == "ከበደ ወ+ልዴ"
    # The literal '+' must stay percent-encoded: a raw '+' would mean a space.
    assert "%2B" in encode(values)


@pytest.mark.parametrize(
    "user",
    [
        None,
        "[]",
        '{"first_name":"A"}',
        '{"id":"1","first_name":"A"}',
        '{"id":true,"first_name":"A"}',
        '{"id":0,"first_name":"A"}',
        '{"id":9007199254740992,"first_name":"A"}',
        '{"id":1}',
        '{"id":1,"first_name":"  "}',
        '{"id":1,"first_name":"A","is_bot":true}',
        '{"id":1,"first_name":"A","last_name":5}',
        '{"id":1,"id":2,"first_name":"A"}',
        '{"id":NaN,"first_name":"A"}',
        "not json",
    ],
)
def test_user_must_be_a_documented_webappuser(
    signer: Signer, bot: tuple[int, str], user: str | None
) -> None:
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token)
    if user is None:
        del values["user"]
    else:
        values["user"] = user
    values["signature"] = signer.signature(values, bot_id)
    values["hash"] = hmac_hex(values, token)
    assert reason(encode(values), signer, bot) == "malformed"


def test_largest_documented_user_id_is_accepted(signer: Signer, bot: tuple[int, str]) -> None:
    bot_id, token = bot
    user = {"id": 2**53 - 1, "first_name": "Max"}
    assert check(signer.init_data(bot_id=bot_id, bot_token=token, user=user), signer, bot)


def test_receiver_and_chat_are_never_used_for_identity(
    signer: Signer, bot: tuple[int, str]
) -> None:
    bot_id, token = bot
    values = signer.fields(
        bot_id=bot_id,
        bot_token=token,
        user={"id": 7, "first_name": "Real"},
        extra={"receiver": json.dumps({"id": 8, "first_name": "Other", "is_bot": True})},
    )
    assert check(encode(values), signer, bot).user.id == 7


def test_login_widget_mechanism_never_validates_mini_app_data(
    signer: Signer, bot: tuple[int, str]
) -> None:
    """The legacy widget keys its HMAC with SHA256(token): a different mechanism."""
    bot_id, token = bot
    values = signer.fields(bot_id=bot_id, bot_token=token)
    values["hash"] = login_widget_hash(values, token)
    assert reason(encode(values), signer, bot) == "bad_hash"
    # Widget-shaped data (no signature, flat fields) is malformed for a Mini App.
    widget = {"id": "7", "first_name": "A", "auth_date": str(int(time.time()))}
    widget["hash"] = login_widget_hash(widget, token)
    assert reason(encode(widget), signer, bot) == "malformed"


def test_an_openid_connect_id_token_is_not_init_data(signer: Signer, bot: tuple[int, str]) -> None:
    jwt_like = "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL29hdXRoLnRlbGVncmFtLm9yZyJ9.c2ln"
    assert reason(jwt_like, signer, bot) == "malformed"
    assert reason(f"id_token={jwt_like}", signer, bot) == "malformed"


def test_empty_init_data_of_keyboard_and_inline_launches_fails(
    signer: Signer, bot: tuple[int, str]
) -> None:
    assert reason("", signer, bot) == "malformed"


def test_validator_has_no_application_or_io_imports() -> None:
    source = (Path(miniapp.__file__)).read_text()
    for forbidden in ("arada.", "sqlalchemy", "httpx", "fastapi", "requests", "socket"):
        assert f"import {forbidden}" not in source, forbidden
        assert f"from {forbidden}" not in source, forbidden
