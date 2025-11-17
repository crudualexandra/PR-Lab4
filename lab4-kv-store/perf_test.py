import os
import time
import queue
import threading
import statistics
from typing import List

import requests

# ──────────────────────────────────────────────────────────────────────────────
# Configuration (override with env vars if you want)
# ──────────────────────────────────────────────────────────────────────────────

LEADER_URL = os.getenv("LEADER_URL", "http://localhost:5000")

FOLLOWER_URLS_ENV = os.getenv(
    "FOLLOWER_URLS",
    "http://localhost:5001,http://localhost:5002,http://localhost:5003,"
    "http://localhost:5004,http://localhost:5005"
)
FOLLOWERS = [u for u in FOLLOWER_URLS_ENV.split(",") if u.strip()]

NUM_WRITES = int(os.getenv("NUM_WRITES", "10000"))
NUM_KEYS = int(os.getenv("NUM_KEYS", "100"))
NUM_THREADS = int(os.getenv("NUM_THREADS", "20"))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def wait_for_leader(timeout: float = 10.0) -> None:
    """Wait until the leader health endpoint is up."""
    deadline = time.time() + timeout
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        try:
            r = requests.get(f"{LEADER_URL}/health", timeout=1.0)
            if r.status_code == 200:
                print(f"[OK] Leader is healthy after {attempts} probe(s)")
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("Leader did not become healthy in time")


def worker(
    job_queue: queue.Queue,
    latencies: List[float],
    lat_lock: threading.Lock,
    success_counter: List[int],
    error_counter: List[int],
) -> None:
    """Worker thread: repeatedly take a job (write index) and send a PUT."""
    while True:
        try:
            idx = job_queue.get_nowait()
        except queue.Empty:
            return

        key = f"key-{idx % NUM_KEYS}"
        value = f"value-{idx}"

        start = time.perf_counter()
        try:
            resp = requests.put(
                f"{LEADER_URL}/kv/{key}",
                json={"value": value},
                timeout=5.0,
            )
            if resp.status_code == 200:
                elapsed = time.perf_counter() - start
                with lat_lock:
                    latencies.append(elapsed)
                success_counter[0] += 1
            else:
                error_counter[0] += 1
        except Exception:
            error_counter[0] += 1
        finally:
            job_queue.task_done()


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("══════════════════════════════════════════════")
    print("         Performance test: write load         ")
    print("══════════════════════════════════════════════")
    print(f"Leader URL:     {LEADER_URL}")
    print(f"Follower URLs:  {FOLLOWERS if FOLLOWERS else 'NONE'}")
    print(f"NUM_WRITES:     {NUM_WRITES}")
    print(f"NUM_KEYS:       {NUM_KEYS}")
    print(f"NUM_THREADS:    {NUM_THREADS}")
    print("══════════════════════════════════════════════\n")

    wait_for_leader()

    # Prepare job queue: indices 0 .. NUM_WRITES-1
    job_queue: queue.Queue = queue.Queue()
    for i in range(NUM_WRITES):
        job_queue.put(i)

    latencies: List[float] = []
    lat_lock = threading.Lock()
    success_counter = [0]  # wrap in list so it's mutable from threads
    error_counter = [0]

    # Start worker threads
    threads: List[threading.Thread] = []
    print("[1] Starting workers and issuing writes...")
    t0 = time.perf_counter()
    for _ in range(NUM_THREADS):
        t = threading.Thread(
            target=worker,
            args=(job_queue, latencies, lat_lock, success_counter, error_counter),
        )
        t.start()
        threads.append(t)

    # Wait for completion
    job_queue.join()
    for t in threads:
        t.join()
    t1 = time.perf_counter()

    total_time = t1 - t0
    total_success = success_counter[0]
    total_errors = error_counter[0]

    print("\n[2] Write phase finished.")
    print(f"    Successful writes: {total_success}")
    print(f"    Failed writes:     {total_errors}")
    print(f"    Total time:        {total_time:.3f} s")

    if not latencies:
        print("    No successful writes recorded, skipping latency stats.")
    else:
        # Convert seconds to ms
        lat_ms = [x * 1000.0 for x in latencies]
        lat_ms.sort()
        avg = statistics.mean(lat_ms)
        med = statistics.median(lat_ms)
        p95 = lat_ms[int(0.95 * (len(lat_ms) - 1))]
        p99 = lat_ms[int(0.99 * (len(lat_ms) - 1))]
        min_lat = lat_ms[0]
        max_lat = lat_ms[-1]
        throughput = total_success / total_time if total_time > 0 else 0.0

        print("\n[3] Latency statistics (successful writes only):")
        print(f"    Count:      {len(lat_ms)}")
        print(f"    Average:    {avg:.3f} ms")
        print(f"    Median:     {med:.3f} ms")
        print(f"    P95:        {p95:.3f} ms")
        print(f"    P99:        {p99:.3f} ms")
        print(f"    Min:        {min_lat:.3f} ms")
        print(f"    Max:        {max_lat:.3f} ms")
        print(f"    Throughput: {throughput:.2f} writes/sec")

    # Consistency check: compare leader dump with each follower
    print("\n[4] Consistency check: leader vs followers...")
    try:
        leader_dump = requests.get(f"{LEADER_URL}/dump", timeout=10.0).json()
    except Exception as e:
        print(f"    [ERROR] Could not fetch leader dump: {e}")
        leader_dump = None

    followers_checked = 0
    followers_matching = 0

    if leader_dump is not None:
        for follower_url in FOLLOWERS:
            print(f"    - Follower: {follower_url}")
            try:
                follower_dump = requests.get(
                    f"{follower_url}/dump", timeout=10.0
                ).json()
            except Exception as e:
                print(f"      [ERROR] Could not contact follower: {e}")
                continue

            followers_checked += 1
            if follower_dump == leader_dump:
                followers_matching += 1
                print("      [OK] Replica matches leader.")
            else:
                # Optional: show how many keys differ
                diff_keys = set(leader_dump.keys()) ^ set(follower_dump.keys())
                print("      [MISMATCH] Replica differs from leader.")
                print(f"      Keys differing (symmetric diff): {len(diff_keys)}")

    print("\n══════════════════════════════════════════════")
    print("               Performance summary            ")
    print("══════════════════════════════════════════════")
    print(f"Total writes requested:   {NUM_WRITES}")
    print(f"Successful writes:        {total_success}")
    print(f"Failed writes:            {total_errors}")
    print(f"Total elapsed time:       {total_time:.3f} s")
    if latencies:
        print(f"Average latency:          {avg:.3f} ms")
        print(f"P95 latency:             {p95:.3f} ms")
        print(f"Throughput:              {throughput:.2f} writes/sec")
    else:
        print("Latency stats:            N/A (no successes)")
    print(f"Followers configured:     {len(FOLLOWERS)}")
    print(f"Followers checked:        {followers_checked}")
    print(f"Followers matching dump:  {followers_matching}")
    print("══════════════════════════════════════════════")


if __name__ == "__main__":
    main()