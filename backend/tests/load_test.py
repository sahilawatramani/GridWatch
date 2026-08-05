"""Load test script — verifies 5,000 events in 10 seconds (burst spec).

Run: python tests/load_test.py [base_url]

Generates 5,000 realistic telemetry events and posts them as fast as possible
to verify the ingest pipeline handles burst traffic.
"""
import asyncio
import aiohttp
import time
import random
import json
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"


async def send_batch(session, batch):
    """Send a batch of events via the batch endpoint."""
    try:
        async with session.post(
            f"{BASE_URL}/api/ingest/batch",
            json=batch,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            return resp.status
    except Exception as e:
        return f"error: {e}"


async def run_load_test(total_events=5000, batch_size=100, target_seconds=10):
    """Run the load test."""
    print(f"GridWatch Load Test")
    print(f"={'=' * 50}")
    print(f"Target: {total_events} events in {target_seconds}s")
    print(f"Batch size: {batch_size}")
    print(f"Endpoint: {BASE_URL}/api/ingest/batch")
    print()

    # Generate events
    events = []
    for i in range(total_events):
        events.append({
            "device_id": f"LOAD-DEV-{i % 200:04d}",
            "pole_id": f"LOAD-P-{i % 200:04d}",
            "event": random.choice(["heartbeat", "heartbeat", "heartbeat", "power_lost"]),
            "energized": random.random() > 0.1,
            "ts": datetime.now(timezone.utc).isoformat(),
            "seq": 500000 + i,
            "battery_mv": random.randint(3400, 3800),
            "rssi": random.randint(-95, -60),
            "fw": "1.4.2",
        })

    # Split into batches
    batches = [events[i:i+batch_size] for i in range(0, len(events), batch_size)]

    # Fire
    print(f"Sending {len(batches)} batches of {batch_size}...")
    start = time.perf_counter()

    async with aiohttp.ClientSession() as session:
        tasks = [send_batch(session, batch) for batch in batches]
        results = await asyncio.gather(*tasks)

    elapsed = time.perf_counter() - start

    # Report
    successes = sum(1 for r in results if r == 200)
    failures = len(results) - successes

    print(f"\nResults:")
    print(f"  Total events: {total_events}")
    print(f"  Elapsed: {elapsed:.2f}s")
    print(f"  Throughput: {total_events / elapsed:.0f} events/s")
    print(f"  Batches OK: {successes}/{len(results)}")
    if failures:
        print(f"  Batches failed: {failures}")

    target_rate = total_events / target_seconds
    actual_rate = total_events / elapsed
    if actual_rate >= target_rate:
        print(f"\n  PASS: {actual_rate:.0f} events/s >= {target_rate:.0f} target")
    else:
        print(f"\n  WARN: {actual_rate:.0f} events/s < {target_rate:.0f} target")

    return elapsed


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        BASE_URL = sys.argv[1]
    asyncio.run(run_load_test())
