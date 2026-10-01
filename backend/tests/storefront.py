"""Storefront helpers: a merchant host, its own bot, and Telegram logins.

Bots are fakes (random id and token) and ``initData`` is signed by the test
suite's throwaway key, which the test settings configure as the Telegram
test-environment key. Nothing here is a real credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from tests.support import Persona, unique
from tests.telegram_kit import Signer, fake_bot

# Telegram's published production key (core.telegram.org/bots/webapps
# #validating-data-for-third-party-use; ADR-012). A public value, used only to
# build production Settings in tests; it can verify nothing the suite signs.
TELEGRAM_PRODUCTION_PUBLIC_KEY = "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"


@dataclass
class Storefront:
    tenant_id: str
    slug: str
    host: str
    bot_id: int
    bot_token: str

    def init_data(self, signer: Signer, **kwargs: Any) -> str:
        return signer.init_data(bot_id=self.bot_id, bot_token=self.bot_token, **kwargs)


@dataclass
class Customer:
    storefront: Storefront
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Host": self.storefront.host}


async def open_storefront(
    client: httpx.AsyncClient, root: Persona, tenant_id: str, slug: str
) -> Storefront:
    host = f"{unique('sf-')}.localhost"
    added = await client.post(
        f"/v1/platform/tenants/{tenant_id}/domains", headers=root.headers, json={"hostname": host}
    )
    assert added.status_code == 201, added.text
    bot_id, token = fake_bot()
    bound = await client.put(
        f"/v1/platform/tenants/{tenant_id}/telegram-bot",
        headers=root.headers,
        json={"bot_id": bot_id, "bot_token": token},
    )
    assert bound.status_code == 200, bound.text
    return Storefront(tenant_id=tenant_id, slug=slug, host=host, bot_id=bot_id, bot_token=token)


async def telegram_login(
    client: httpx.AsyncClient, host: str, init_data: str, **extra: Any
) -> httpx.Response:
    return await client.post(
        "/v1/storefront/auth/telegram",
        headers={"Host": host},
        json={"init_data": init_data, **extra},
    )


async def new_customer(
    client: httpx.AsyncClient, sf: Storefront, signer: Signer, **kwargs: Any
) -> Customer:
    response = await telegram_login(client, sf.host, sf.init_data(signer, **kwargs))
    assert response.status_code == 200, response.text
    return Customer(storefront=sf, token=response.json()["access_token"])
