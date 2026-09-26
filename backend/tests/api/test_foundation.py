"""Gate 1: the application starts and the HTTP foundation behaves."""

from __future__ import annotations

import httpx


async def test_liveness_and_readiness(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    ready = await client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"


async def test_every_response_carries_correlation_ids(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert len(response.headers["x-request-id"]) == 32
    assert response.headers["traceparent"].startswith("00-")


async def test_client_supplied_request_id_is_not_trusted(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"x-request-id": "attacker-chosen"})
    assert response.headers["x-request-id"] != "attacker-chosen"


async def test_valid_traceparent_is_continued(client: httpx.AsyncClient) -> None:
    parent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    response = await client.get("/healthz", headers={"traceparent": parent})
    assert response.headers["traceparent"].split("-")[1] == "4bf92f3577b34da6a3ce929d0e0e4736"


async def test_unknown_route_is_a_problem_document(client: httpx.AsyncClient) -> None:
    response = await client.get("/no/such/route")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "urn:arada:problem:not-found"
    assert body["request_id"] == response.headers["x-request-id"]


async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    headers = (await client.get("/healthz")).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "no-store"
    assert headers["x-frame-options"] == "DENY"
    assert "server" not in {k.lower() for k in headers}


async def test_oversized_body_rejected_before_parsing(client: httpx.AsyncClient) -> None:
    response = await client.post("/healthz", content=b"x" * (1_048_576 + 1))
    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
