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

run : `NUM_WRITES=10000 NUM_KEYS=100 NUM_THREADS=20 python perf_test.py`

| **WRITE_QUORUM** | **What it means?** |
| --- | --- |
| 1 | Only the leader must ack → followers are fully async |
| 2 | Leader + **any 1** follower must ack |
| 3 | Leader + **any 2** followers must ack *(your current setting)* |
| 4 | Leader + **any 3** followers must ack |
| 5 | Leader + **any 4** followers must ack |
| 6 | Leader + **all 5** followers must ack (fully sync) |

**QUORUM TESTING:**
**quorum = 1** (only the leader has to ack)

`WRITE_QUORUM: "1”`

RESTART: 

`docker-compose down
docker-compose up --build -d`

RUN:

`python perf_test.py`

SAME FOR EACH FROM 1 TO 5

**1️⃣ Test with WRITE_QUORUM = 1**

══════════════════════════════════════════════
Performance summary

══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        10000
Failed writes:            0
Total elapsed time:       8.225 s
Average latency:          16.408 ms
P95 latency:             23.774 ms
Throughput:              1215.73 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  0

> For WRITE_QUORUM = 1, the leader acknowledges a write as soon as it is stored locally, without waiting for any follower. In our 10k-write performance test (20 threads, 100 keys), we achieved an average latency of ~16.4 ms and a throughput of about 1,216 writes/sec, with 0 failed writes.
> 

> However, immediately after the load, **none of the followers’ /dump outputs matched the leader high performance followers may still be missing updates**
> 

**2️⃣ Test with WRITE_QUORUM = 2**

Leader + **any 1** follower must ack

══════════════════════════════════════════════
Performance summary

══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9832
Failed writes:            168
Total elapsed time:       96.249 s
Average latency:          106.770 ms
P95 latency:             146.407 ms
Throughput:              102.15 writes/sec
Followers configured:     5
Followers checked:        0
Followers matching dump:  0
══════════════════════════════════════════════

> For WRITE_QUORUM = 2 (leader + one follower), the average latency increased to ~106.8 ms and throughput dropped to ~102 writes/sec. We also observed 168 failed writes, where the leader could not collect enough acknowledgements from followers before the write timeout. This shows the typical trade-off: higher quorum improves durability/consistency but reduces performance and availability.
> 

> Under WRITE_QUORUM = 2, the leader becomes so loaded that a full /dump request may time out at 10 seconds, which illustrates how higher quorum and heavy write load can also impact read performance and observability.
> 

**3️⃣ Test with WRITE_QUORUM = 3**
Meaning: *leader + any 2 followers*.

══════════════════════════════════════════════
Performance summary

══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9822
Failed writes:            178
Total elapsed time:       95.463 s
Average latency:          99.594 ms
P95 latency:             113.214 ms
Throughput:              102.89 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  0
══════════════════════════════════════════════

> For WRITE_QUORUM = 3 (leader + two followers), the average write latency stayed around 100 ms and throughput was ~103 writes/sec, with 178 failed writes due to timeouts while waiting for acknowledgements. This is similar to the quorum 2 case: higher quorums give stronger guarantees but keep write performance much lower than the asynchronous case (quorum 1).
> 

**4️⃣ Test with WRITE_QUORUM = 4**

══════════════════════════════════════════════
Performance summary

══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9806
Failed writes:            194
Total elapsed time:       96.028 s
Average latency:          106.328 ms
P95 latency:             130.556 ms
Throughput:              102.12 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  0
══════════════════════════════════════════════

> With WRITE_QUORUM = 4 (leader + three followers), the average latency was about 106 ms and throughput around 102 writes/sec. We observed 194 failed writes, caused by the leader not receiving enough acknowledgements from followers before the timeout. This shows that requiring acknowledgements from more replicas further reduces availability and increases the probability of write failures under load.
> 

**Consistency**

> Immediately after the 10k writes, all replicas stored the same set of 100 keys, but none of the followers had an identical dump to the leader. This indicates that followers are still catching up on the most recent updates (replication lag), even though writes are only reported successful if a relatively large number of replicas acknowledge them.
> 

**5️⃣ Test with WRITE_QUORUM = 5**

══════════════════════════════════════════════
Performance summary

══════════════════════════════════════════════
Total writes requested:   10000
Successful writes:        9812
Failed writes:            188
Total elapsed time:       75.705 s
Average latency:          104.825 ms
P95 latency:             127.379 ms
Throughput:              129.61 writes/sec
Followers configured:     5
Followers checked:        5
Followers matching dump:  0
══════════════════════════════════════════════

> For WRITE_QUORUM = 5 (leader + four followers), the average write latency was ~104.8 ms, with a throughput of ~130 writes/sec and 188 failed writes due to timeouts while waiting for enough acknowledgements. All replicas stored the same 100 keys, but none of the followers’ dumps were identical to the leader: some values were still older, which shows replication lag (followers had not yet applied all of the latest updates when we checked).
> 

## TEST RESULTS FOR ALL

| **WRITE_QUORUM** | **Successful** | **Failed** | **Avg latency (ms)** | **Throughput (writes/s)** | **Followers matching dump** |
| --- | --- | --- | --- | --- | --- |
| 1 | 10000 | 0 | 16.41 | 1215.73 | 0 / 5 |
| 2 | 9832 | 168 | 106.77 | 102.15 | 0 / 0 (leader dump timeout) |
| 3 | 9822 | 178 | 99.59 | 102.89 | 0 / 5 |
| 4 | 9806 | 194 | 106.33 | 102.12 | 0 / 5 |
| 5 | 9812 | 188 | 104.83 | 129.61 | 0 / 5 |

> We ran a performance test with 10,000 writes, 20 client threads and 100 logical keys, varying the WRITE_QUORUM parameter from 1 to 5. For WRITE_QUORUM = 1 (only the leader must acknowledge), the average latency was ≈16.4 ms and the throughput ≈1,216 writes/sec, with 0 failed writes. However, after the test none of the followers’ /dump states matched the leader and 100 keys were missing or outdated on replicas, which shows that with quorum 1 replication is fully asynchronous and followers can lag significantly behind the leader.
> 

> For WRITE_QUORUM ∈ {2,3,4,5}, the leader waited for at least one or more follower acknowledgements before confirming a write. In this regime, the average latency increased to around 100 ms and throughput dropped to roughly 100–130 writes/sec. We also observed between 168 and 194 failed writes, where the leader could not collect enough acknowledgements before the timeout, which illustrates the trade-off: higher quorums improve durability guarantees but reduce performance and availability. Immediately after the write phase, all replicas contained the same 100 keys, but none of the followers had an identical dump to the leader, meaning that some values were still older on the followers—replication was still catching up, so the system shows **replication lag eventual consistency**
> 

**QUESTION FROM LAB REQUIREMENT:**

1. Plot the value of the "write quorum" (test values from 1 to 5) vs. the average latency of the write operation. Explain the results.
2. After all the writes are completed, check if the data in the replicas matches the data on the leader. Explain the results.

### **1️⃣ Plot: write quorum vs average latency – explanation**

As we increase the write quorum from 1 to 5, the leader has to wait for acknowledgements from more replicas before replying, so the **average write latency jumps up** (from ≈16 ms at quorum 1 to ≈100 ms for quorum ≥2) and throughput drops.

With higher quorums the latency is dominated by the **slowest required follower** and by the random network delays we added, so the curve is higher and relatively flat for quorums 2–5.

### **2️⃣ After 10k writes, does replica data match the leader? Why / why not?**

Immediately after the 10k concurrent writes, **none of the followers had a dump identical to the leader**: they had the same set of keys, but some values were older, which means they were still catching up with the latest updates.

This happens because replication is asynchronous in the background: even with higher quorums the leader only waits for *some* followers to acknowledge each write, while other followers may still be applying previous operations, so the system exhibits **replication lag and eventual consistency**, not instant synchronization.

## Conclusion

In this lab I designed and implemented a simple key–value store with **single-leader replication**, where only the leader accepts client writes and propagates them to five followers over a JSON/HTTP API. All components (role, follower list, write quorum, artificial network delay) are configured via environment variables in docker-compose.yml, and both leader and followers handle requests concurrently using threads. On the leader side I implemented **semi-synchronous replication**: the leader always writes locally, starts replication to all followers in parallel with a random delay in [0.1 ms, 10 ms] for each follower, and only reports success when a configurable number of acknowledgements (“write quorum”) has been collected or a timeout is reached.

The **integration test** showed that the basic replication mechanism works as expected: a write to the leader is stored locally and eventually appears on all followers, while the write response includes both the total number of acknowledgements and the configured quorum. The **performance test** stressed the system with 10,000 concurrent writes on 100 keys (20 threads), and allowed me to measure how the **write quorum affects latency and throughput**. With WRITE_QUORUM = 1 (leader only), average latency was very low and throughput high, but followers lagged behind and none of them matched the leader’s dump immediately after the test, illustrating weak consistency. For higher quorums (2–5), average latency increased to around 100 ms, throughput dropped to ≈100–130 writes/sec, and some writes failed due to timeouts while waiting for enough follower acknowledgements, which reflects the trade-off between **performance, availability, and stronger durability/consistency guarantees** described in Kleppmann’s chapter on replication.
