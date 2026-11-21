"""Small closed-loop load test for POST /v1/detect.

Reports p50/p95 latency of successful requests, throughput, and how many requests were
rejected as overloaded (503) or timed out (504). Example:

  python scripts/load_test.py --url http://127.0.0.1:8000 --image photo.jpg --concurrency 8 --requests 200
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import time
from collections import Counter
from pathlib import Path

import httpx


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--requests", type=int, default=100)
    args = parser.parse_args()

    payload = args.image.read_bytes()
    statuses: Counter[int] = Counter()
    latencies: list[float] = []
    remaining = args.requests

    async def worker(client: httpx.AsyncClient) -> None:
        nonlocal remaining
        while remaining > 0:
            remaining -= 1
            started = time.perf_counter()
            try:
                response = await client.post(
                    f"{args.url}/v1/detect", content=payload, headers={"Content-Type": "image/jpeg"}
                )
                statuses[response.status_code] += 1
                if response.status_code == 200:
                    latencies.append((time.perf_counter() - started) * 1000)
            except httpx.HTTPError:
                statuses[0] += 1

    async with httpx.AsyncClient(timeout=30) as client:
        ready = (await client.get(f"{args.url}/readyz")).json()
        wall = time.perf_counter()
        await asyncio.gather(*(worker(client) for _ in range(args.concurrency)))
        wall = time.perf_counter() - wall
        token = os.environ.get("ECOREVIVE_METRICS_TOKEN", "")
        response = await client.get(f"{args.url}/v1/metrics", headers={"Authorization": f"Bearer {token}"})
        server = response.json() if response.status_code == 200 else {}

    report = {
        "model": ready.get("model"),
        "host": {"cpu": platform.processor(), "logical_cpus": os.cpu_count(), "os": platform.platform()},
        "settings": {"concurrency": args.concurrency, "requests": args.requests, "image_bytes": len(payload)},
        "status_counts": dict(statuses),
        "throughput_rps": round(statuses[200] / wall, 2),
        "client_latency_ms": {
            "p50": round(percentile(latencies, 0.5), 1) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 1) if latencies else None,
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
        },
        "server_inference_ms": server.get("latency", {}).get("inference"),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
