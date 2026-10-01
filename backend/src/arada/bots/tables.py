from __future__ import annotations

from sqlalchemy import BigInteger, Column, Integer, LargeBinary, Table, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from arada.kernel.sql import metadata

TS = TIMESTAMP(timezone=True)

telegram_bots = Table(
    "telegram_bots",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("telegram_bot_id", BigInteger, nullable=False),
    Column("token_ciphertext", LargeBinary, nullable=False),
    Column("token_nonce", LargeBinary, nullable=False),
    Column("wrapped_dek", LargeBinary, nullable=False),
    Column("dek_nonce", LargeBinary, nullable=False),
    Column("kek_version", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("created_by", UUID(as_uuid=True), nullable=True),
    Column("disabled_at", TS, nullable=True),
)

telegram_init_data_uses = Table(
    "telegram_init_data_uses",
    metadata,
    Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    Column("hash_digest", LargeBinary, primary_key=True),
    Column("first_used_at", TS, nullable=False),
    Column("use_count", Integer, nullable=False),
    Column("expires_at", TS, nullable=False),
)
