#!/usr/bin/env python3
"""Indicative API throughput/latency measurement against a running stack.

Measures an authenticated, tenant-scoped, RLS-enforced request
(GET /v1/t/{slug}: session lookup + tenant resolution + grants + profile
read, two transactions) and the unauthenticated liveness probe. Results on
a developer workstation are *indicative only*; production sizing uses the
same script on the real machines (docs/11_DEPLOYMENT.md §3).

    python scripts/measure_api.py --state-file state.json --requests 2000 --concurrency 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx


async def run(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], total: int, concurrency: int
) -> dict[str, float]:
    latencies: list[float] = []
    errors = 0
    queue: asyncio.Queue[int] = asyncio.Queue()
    for i in range(total):
        queue.put_nowait(i)

    async def worker() -> None:
        nonlocal errors
        while not queue.empty():
            queue.get_nowait()
            started = time.perf_counter()
            response = await client.get(url, headers=headers)
            latencies.append((time.perf_counter() - started) * 1000)
            if response.status_code != 200:
                errors += 1

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed = time.perf_counter() - started
    latencies.sort()
    return {
        "requests": total,
        "errors": errors,
        "rps": round(total / elapsed, 1),
        "p50_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1], 1),
        "p99_ms": round(latencies[int(len(latencies) * 0.99) - 1], 1),
    }


async def main(state: dict[str, str], requests: int, concurrency: int) -> None:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=state["base_url"], timeout=30, limits=limits) as client:
        login = await client.post(
            "/v1/auth/login", json={"username": state["username"], "password": state["password"]}
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        tenant_url = f"/v1/t/{state['tenant_slug']}"
        await run(client, tenant_url, headers, 100, concurrency)  # warm-up
        results = {
            "liveness GET /healthz": await run(client, "/healthz", {}, requests, concurrency),
            "tenant GET /v1/t/{slug} (auth+RLS)": await run(
                client, tenant_url, headers, requests, concurrency
            ),
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=20)
    cli = parser.parse_args()
    asyncio.run(main(json.loads(Path(cli.state_file).read_text()), cli.requests, cli.concurrency))
