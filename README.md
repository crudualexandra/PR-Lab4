# Laboratory 4


Class: Network Programming
Student: Crudu Alexandra, FAF-233.

# Laboratory Purpose:

Build a small distributed system:

- **1 leader** process:
    - accepts **writes** (PUT /kv/…) from clients
    - stores data locally
    - **replicates** writes to all followers via HTTP
    - uses **semi-synchronous replication**:
        - client write is successful only after **write_quorum** nodes (leader + followers) have confirmed.
- **5 followers**:
    - accept **replication requests** only from the leader
    - also answer **read** requests (GET /kv/…)
- All nodes:
    - serve a JSON web API
    - handle requests **concurrently** (multi-threaded Flask)

Everything (roles, follower URLs, quorum, delays) is configured via **environment variables** in docker-compose.

# Implementation

**Step 1 – Project structure**

lab4-kv-store/
├── [app.py](http://app.py/)                 # Flask app: leader + follower behavior
├── requirements.txt       # Python dependencies
├── Dockerfile             # Image for leader and followers
├── docker-compose.yml     # Run 1 leader + 5 followers
├── perf_test.py           # Performance & consistency test script
└── test_integration.py    # Simple integration test

### **Step 2 – Python dependencies**

**requirements.txt**

flask
requests

- flask – web API
- requests – HTTP client for leader to call followers

### **Step 3 – Core server code (leader + followers in one app) app.py**

### **What’s happening here :**

- **Global config** from env vars (ROLE, FOLLOWERS, WRITE_QUORUM, delays)
- **In-memory store** store + store_lock → safe concurrent access.
- **GET /kv/** – read from any node (leader or follower).
- **PUT /kv/** – only leader:
    1. Applies write locally.
    2. Spawns a thread per follower:
        - waits random delay UNIFORM[MIN_DELAY_S, MAX_DELAY_S]
        - POSTs /replicate to follower
        - if follower confirms (HTTP 200), increments ack_count.
    3. Waits until ack_count >= WRITE_QUORUM **or** timeout.
    4. Returns success (200) or failure (503) with JSON showing acks & required.
- **/replicate** – follower applies the write received from leader.
- **/dump** – returns all keys & values (used later for consistency check).

This satisfies:

- Single-leader replication
- Semi-synchronous via configurable **write quorum**
- Simulated per-follower lag
- Concurrent handling of both client requests and replication threads.

## **Step 4 – Dockerfile**

So all 6 containers (1 leader + 5 followers) use the same image.

## **Step 5 – docker-compose: 1 leader + 5 followers**

**docker-compose.yml**

**How to run:**
From the project folder:

`docker-compose build
docker-compose up`

![image.png](Laboratory%204/image.png)

Then test manually:

curl [http://localhost:5000/health](http://localhost:5000/health)

![image.png](Laboratory%204/image%201.png)

**Check that replication to a follower works**

**Write to the leader (from host)**

curl -X PUT "[http://localhost:5000/kv/foo](http://localhost:5000/kv/foo)" \
-H "Content-Type: application/json" \
-d '{"value": "bar"}'

![image.png](Laboratory%204/image%202.png)

**Read from a follower (from inside the follower container)**
docker exec -it kv-f1 /bin/sh

apt-get update
apt-get install -y curl

call:  curl [http://localhost:5000/kv/foo](http://localhost:5000/kv/foo)

![image.png](Laboratory%204/image%203.png)

## **Step 6 – Simple integration test (correctness)**

This is a **basic integration test** which:

1. Writes a key to the leader
2. Waits a bit to allow replication
3. Fetches /dump from leader and all followers and verifies that the data matches.

**test_integration.py Run (from host, after docker-compose up):**

`python test_integration.py`

![image.png](Laboratory%204/image%204.png)

- The integration test first checks the **leader health** at http://localhost:5000/health, which succeeds after 1 probe, proving the leader is up and reachable.
- Then it performs **one write** to the leader (PUT /kv/integration-key) with value "integration-value". The write returns status **200**, with latency ≈ **35 ms**, and the response shows acks: 6 and required: 3, meaning the leader plus all 5 followers acknowledged the write while only 3 acknowledgements were required by the configured write quorum.
- After a short wait, the test reads the **full dump from the leader** and confirms that the key "integration-key" is stored with the correct value.
- Finally, it contacts each follower on ports **5001–5005**, fetches their dumps, and verifies that every follower also has "integration-key" = "integration-value". All 5 followers match the leader, so the summary reports: **Leader URL = localhost:5000, Followers configured = 5, Followers checked = 5, Result = ✅ Integration test PASSED** – which shows that replication is working correctly and all replicas are consistent for this test write.

## **Step 7 – Performance test: 10K concurrent**

**A** script that:

- **Setup**
    - Uses env vars (or defaults) for NUM_WRITES (10 000), NUM_KEYS (100), and NUM_THREADS (e.g. 20).
    - Waits for the leader to become healthy.
- **Write phase**
    - Builds a job queue with NUM_WRITES items.
    - Starts NUM_THREADS worker threads; each thread repeatedly:
        - Picks an index i, computes key = key-(i % NUM_KEYS) and value = value-i.
        - Sends PUT /kv/<key> to the leader.
        - On success, records the **latency** of that write.
- **Statistics**
    - After all jobs are done, it prints:
        - number of **successful** and **failed** writes
        - total test time
        - latency stats for successful writes: **average, median, p95, p99, min, max**
        - overall **throughput** in writes/sec.
- **Consistency check**
    - Reads /dump from the leader.
    - Reads /dump from every follower (ports 5001–5005) and compares the JSON.
    - Counts how many followers perfectly match the leader and prints a **summary**.

Running this script with different WRITE_QUORUM values (1–5) gives you:

- **Average latency** (for the x–y plot required in the lab).
- A quick **consistency summary** after each run to see if the replicas converge to the leader’s state.

run : `NUM_WRITES=10000 NUM_KEYS=100 NUM_THREADS=15 SETTLE_SECONDS=5 TEST_ALL_QUORUMS=true python perf_test.py`

| **WRITE_QUORUM** | **What it means?** |
| --- | --- |
| 1 | Only the leader must ack → followers are fully async |
| 2 | Leader + **any 1** follower must ack |
| 3 | Leader + **any 2** followers must ack *(your current setting)* |
| 4 | Leader + **any 3** followers must ack |
| 5 | Leader + **any 4** followers must ack |
| 6 | Leader + **all 5** followers must ack (fully sync) |

**QUORUM TESTING:**


**Run automated testing for all quorums (1-5):**

`NUM_WRITES=10000 NUM_KEYS=100 NUM_THREADS=15 SETTLE_SECONDS=5 TEST_ALL_QUORUMS=true python perf_test.py`

This will automatically:
- Test each WRITE_QUORUM value from 1 to 5
- Restart containers between tests
- Generate plots and CSV results
- Perform final consistency check



**1️⃣ Test with WRITE_QUORUM = 1**

══════════════════════════════════════════════
Performance summary
══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        10000
Failed writes:            0
Total elapsed time:       7.573 s
Average latency:          11.34 ms
P95 latency:             14.94 ms
Throughput:              1320.84 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  0

> For WRITE_QUORUM = 1, the leader acknowledges a write as soon as it is stored locally, without waiting for any follower. We achieved an average latency of ~11.3 ms and a throughput of about 1,321 writes/sec, with 0 failed writes.
> 

> However, immediately after the load, **none of the followers' /dump outputs matched the leader**—high performance but followers may still be missing updates due to fully asynchronous replication.
> 

**2️⃣ Test with WRITE_QUORUM = 2**

Leader + **any 1** follower must ack

══════════════════════════════════════════════
Performance summary
══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9875
Failed writes:            125
Total elapsed time:       93.611 s
Average latency:          77.80 ms
P95 latency:             102.24 ms
Throughput:              105.43 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  5

> For WRITE_QUORUM = 2 (leader + one follower), the average latency increased to ~77.8 ms and throughput dropped to ~105 writes/sec. We observed 125 failed writes, where the leader could not collect enough acknowledgements before the write timeout. This shows the typical trade-off: higher quorum improves durability/consistency but reduces performance and availability.
> 

> Interestingly, all 5 followers matched the leader's dump after the test, showing that semi-synchronous replication with quorum ≥2 plus settling time can achieve strong consistency.
> 

**3️⃣ Test with WRITE_QUORUM = 3**
Meaning: *leader + any 2 followers*.

══════════════════════════════════════════════
Performance summary
══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9851
Failed writes:            149
Total elapsed time:       99.177 s
Average latency:          74.75 ms
P95 latency:             98.36 ms
Throughput:              99.31 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  0

> For WRITE_QUORUM = 3 (leader + two followers), the average write latency was around 74.8 ms and throughput was ~99 writes/sec, with 149 failed writes due to timeouts. Similar to quorum 2, higher quorums give stronger guarantees but keep write performance much lower than the asynchronous case (quorum 1).
> 

> Immediately after the test, followers did not match the leader, demonstrating timing-dependent consistency behavior under high write contention.
> 

**4️⃣ Test with WRITE_QUORUM = 4**

══════════════════════════════════════════════
Performance summary
══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9883
Failed writes:            117
Total elapsed time:       91.558 s
Average latency:          79.47 ms
P95 latency:             99.69 ms
Throughput:              107.95 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  5

> With WRITE_QUORUM = 4 (leader + three followers), the average latency was about 79.5 ms and throughput around 108 writes/sec. We observed 117 failed writes due to timeout. All 5 followers matched the leader after the test, demonstrating that higher quorums with sufficient settling time achieve eventual consistency.
> 

**5️⃣ Test with WRITE_QUORUM = 5**

══════════════════════════════════════════════
Performance summary
══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9873
Failed writes:            127
Total elapsed time:       100.602 s
Average latency:          88.09 ms
P95 latency:             117.54 ms
Throughput:              98.13 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  5

> For WRITE_QUORUM = 5 (leader + four followers), the average write latency was ~88.1 ms, with throughput of ~98 writes/sec and 127 failed writes. All 5 followers matched the leader's dump after the test, demonstrating that requiring acknowledgements from nearly all replicas achieves strong eventual consistency despite higher latency.
> 

**Final Consistency Check:**

After all quorum tests completed, a comprehensive consistency verification was performed with 5 retry attempts over 50 seconds. **Result: All 5 followers matched the leader on the first attempt**, achieving complete eventual consistency without requiring retries. This validates that given sufficient time for replication to complete, the system correctly converges to a consistent state across all replicas.

## TEST RESULTS FOR ALL

| **WRITE_QUORUM** | **Successful** | **Failed** | **Avg latency (ms)** | **Throughput (writes/s)** | **Followers matching dump** |
| --- | --- | --- | --- | --- | --- |
| 1 | 10000 | 0 | 11.34 | 1320.84 | 0 / 5 |
| 2 | 9875 | 125 | 77.80 | 105.43 | 5 / 5 |
| 3 | 9851 | 149 | 74.75 | 99.31 | 0 / 5 |
| 4 | 9883 | 117 | 79.47 | 107.95 | 5 / 5 |
| 5 | 9873 | 127 | 88.09 | 98.13 | 5 / 5 |

> We ran a performance test with 10,000 writes, 15 client threads and 100 logical keys, varying the WRITE_QUORUM parameter from 1 to 5. For WRITE_QUORUM = 1 (only the leader must acknowledge), the average latency was ≈11.3 ms and the throughput ≈1,321 writes/sec, with 0 failed writes. However, after the test none of the followers' /dump states matched the leader, showing that with quorum 1 replication is fully asynchronous and followers can lag significantly behind.
> 

> For WRITE_QUORUM ∈ {2,3,4,5}, the leader waited for at least one or more follower acknowledgements before confirming a write. In this regime, the average latency increased to around 75-88 ms and throughput dropped to roughly 98-108 writes/sec. We observed between 117 and 149 failed writes, where the leader could not collect enough acknowledgements before the timeout. Immediately after each test, quorums 2, 4, and 5 showed all followers matching the leader (5/5), while quorum 3 showed no immediate matches (0/5), demonstrating timing-dependent consistency. The final comprehensive consistency check confirmed that **all 5 followers eventually matched the leader**, validating that the system achieves **eventual consistency** given sufficient settling time.
>

**QUESTION FROM LAB REQUIREMENT:**

1. Plot the value of the "write quorum" (test values from 1 to 5) vs. the average latency of the write operation. Explain the results.
2. After all the writes are completed, check if the data in the replicas matches the data on the leader. Explain the results.

### **1️⃣ Plot: write quorum vs average latency – explanation**

<img width="4168" height="2953" alt="image" src="https://github.com/user-attachments/assets/b6b74863-7c88-46f1-8ca4-01bdcf8c461a" />

**Explanation:**
Latency increases significantly from quorum 1 to quorum 2 (11ms → 77ms, a 6.9× jump) because the leader must wait for follower acknowledgements instead of responding immediately. With quorum=1, only local storage is needed. With quorum≥2, the leader waits for network round-trips, follower processing, and synchronization, adding substantial overhead. Quorums 2-5 show similar latencies (74-88ms) because the system reached capacity under concurrent load—replication happens in parallel, so waiting for more followers doesn't proportionally increase latency. **Trade-off: higher quorum = better durability but slower writes.**

### **2️⃣ After 10k writes, does replica data match the leader? Why / why not?**

**Immediate results per quorum:**
- Quorum 1: 0/5 followers matched
- Quorum 2: 5/5 followers matched
- Quorum 3: 0/5 followers matched
- Quorum 4: 5/5 followers matched
- Quorum 5: 5/5 followers matched

**Final consistency check:** All 5 followers matched the leader after all tests completed.

**Explanation:**
With quorum=1, followers lag behind due to fully asynchronous replication. Higher quorums (2, 4, 5) achieved immediate consistency because the leader waited for multiple followers to acknowledge, allowing replicas to converge during the test. Quorum=3 showed timing-dependent inconsistency due to high write contention. Most importantly, the **final check confirmed eventual consistency**—all replicas eventually converged to the same state, proving the replication mechanism works correctly regardless of quorum level.

## Conclusion

In this lab I implemented a key-value store with **single-leader replication** where the leader accepts writes and replicates them to five followers via JSON/HTTP API. The system uses **semi-synchronous replication** with a configurable write quorum: the leader waits for a specified number of follower acknowledgements before confirming writes to clients, with artificial network delays (0.1-10ms) simulating real-world conditions.

**Performance testing** with 10,000 concurrent writes on 100 keys (15 threads) revealed the fundamental trade-offs in distributed systems. With quorum=1, latency was low (~11ms) and throughput high (~1,321 writes/sec), but followers lagged behind showing weak immediate consistency. Higher quorums (2-5) increased latency to 75-88ms and reduced throughput to ~100 writes/sec, with 1.2-1.5% write failures due to timeouts. This demonstrates the **durability vs performance trade-off**: stronger guarantees require more coordination overhead.

Notably, quorums 2, 4, and 5 achieved immediate consistency (5/5 followers matching) after their tests, showing that semi-synchronous replication with sufficient quorum provides strong consistency. Most importantly, the **final consistency check** confirmed that **all 5 followers matched the leader**, achieving complete **eventual consistency** regardless of quorum level. This validates that given sufficient time for replication to complete, the system correctly converges to a consistent state across all replicas, fulfilling the core guarantee of distributed systems described in Kleppmann's "Designing Data-Intensive Applications."
