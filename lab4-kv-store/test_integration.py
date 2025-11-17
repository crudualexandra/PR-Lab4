import os
import time
import requests

# By default we assume docker-compose as defined above
LEADER_URL = os.getenv("LEADER_URL", "http://localhost:5000")

# Followers are reachable by service name from inside Docker network.
# If you want to run the test from the host, you can expose and adjust these.
FOLLOWER_URLS_ENV = os.getenv(
    "FOLLOWER_URLS",
    "http://localhost:5001,http://localhost:5002,http://localhost:5003,http://localhost:5004,http://localhost:5005"
)
FOLLOWERS = [u for u in FOLLOWER_URLS_ENV.split(",") if u.strip()]


def wait_for_leader(timeout=10.0):
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


def main():
    print("══════════════════════════════════════════════")
    print("     Integration test: leader + followers     ")
    print("══════════════════════════════════════════════")
    print(f"Leader URL:    {LEADER_URL}")
    print(f"Follower URLs: {FOLLOWERS if FOLLOWERS else 'NONE'}")
    print()

    wait_for_leader()

    key = "integration-key"
    value = "integration-value"

    # 1) write to leader
    print("\n[1] Writing test key to leader...")
    start = time.perf_counter()
    resp = requests.put(
        f"{LEADER_URL}/kv/{key}",
        json={"value": value},
        timeout=2.0
    )
    elapsed = (time.perf_counter() - start) * 1000.0
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    print(f"    -> PUT status: {resp.status_code}")
    print(f"    -> PUT latency: {elapsed:.2f} ms")
    print(f"    -> PUT body: {body}")
    assert resp.status_code == 200, "Write should succeed"

    # 2) wait a bit so followers can catch up (best-effort)
    print("\n[2] Waiting 1s for replication to followers...")
    time.sleep(1.0)

    # 3) check leader dump
    print("\n[3] Reading dump from leader...")
    leader_dump = requests.get(f"{LEADER_URL}/dump", timeout=2.0).json()
    print(f"    -> Leader has {len(leader_dump)} keys")
    print(f"    -> Leader[{key!r}] = {leader_dump.get(key)!r}")
    assert leader_dump.get(key) == value

    # 4) followers should match leader (eventual consistency)
    print("\n[4] Checking followers against leader...")
    followers_checked = 0
    for follower_url in FOLLOWERS:
        print(f"    - Follower: {follower_url}")
        try:
            follower_dump = requests.get(f"{follower_url}/dump", timeout=2.0).json()
        except Exception as e:
            print(f"      [ERROR] could not contact follower: {e}")
            raise

        followers_checked += 1
        follower_val = follower_dump.get(key)
        print(f"      follower[{key!r}] = {follower_val!r}")
        assert follower_val == value, (
            f"Follower {follower_url} missing or different value "
            f"(expected {value!r})"
        )
        print("      [OK] follower matches leader for this key")

    print("\n══════════════════════════════════════════════")
    print("               Test summary                   ")
    print("══════════════════════════════════════════════")
    print(f"Leader URL:           {LEADER_URL}")
    print(f"Followers configured: {len(FOLLOWERS)}")
    print(f"Followers checked:    {followers_checked}")
    print(f"Test key:             {key!r}")
    print("Result:               ✅ Integration test PASSED")
    print("══════════════════════════════════════════════")


if __name__ == "__main__":
    main()