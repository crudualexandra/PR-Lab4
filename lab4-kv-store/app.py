import os
import threading
import time
import random
from typing import Dict, Any, List

import requests
from flask import Flask, request, jsonify

# ──────────────────────────────────────────────────────────────────────────────
# Configuration from environment variables
# ──────────────────────────────────────────────────────────────────────────────

ROLE = os.getenv("ROLE", "leader")  # "leader" or "follower"

# follower URLs like: "http://f1:5000,http://f2:5000,..."
FOLLOWERS_ENV = os.getenv("FOLLOWERS", "")
FOLLOWER_URLS: List[str] = [u for u in FOLLOWERS_ENV.split(",") if u.strip()]

# write quorum (how many nodes must confirm) – including leader itself
WRITE_QUORUM = int(os.getenv("WRITE_QUORUM", "3"))

# delays in milliseconds (for simulated network lag)
MIN_DELAY_MS = float(os.getenv("MIN_DELAY_MS", "0.1"))  # e.g. 0.1
MAX_DELAY_MS = float(os.getenv("MAX_DELAY_MS", "10.0"))  # e.g. 10.0

# convert to seconds for time.sleep(...)
MIN_DELAY_S = MIN_DELAY_MS / 1000.0
MAX_DELAY_S = MAX_DELAY_MS / 1000.0

# max time to wait for quorum before giving up (seconds)
WRITE_TIMEOUT_SEC = float(os.getenv("WRITE_TIMEOUT_SEC", "1.0"))

PORT = int(os.getenv("PORT", "5000"))

# ──────────────────────────────────────────────────────────────────────────────
# In-memory key-value store (shared by all handlers in the process)
# Thread-safe with a lock
# ──────────────────────────────────────────────────────────────────────────────

store: Dict[str, Any] = {}
store_lock = threading.Lock()

def set_value(key: str, value: Any) -> None:
    """Store a value in the local in-memory KV store (thread-safe)."""
    with store_lock:
        store[key] = value

def get_value(key: str):
    """Get a value from the local KV store (thread-safe)."""
    with store_lock:
        return store.get(key)

def dump_store() -> Dict[str, Any]:
    """Return a copy of the entire store (for consistency checks)."""
    with store_lock:
        return dict(store)

# ──────────────────────────────────────────────────────────────────────────────
# Flask app
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    """Healthcheck endpoint."""
    return jsonify({
        "role": ROLE,
        "status": "ok"
    })

@app.route("/kv/<key>", methods=["GET"])
def get_kv(key: str):
    """Read endpoint, available on leader and followers."""
    value = get_value(key)
    if value is None:
        return jsonify({"error": "key not found"}), 404
    return jsonify({"key": key, "value": value})

@app.route("/kv/<key>", methods=["PUT"])
def put_kv(key: str):
    """
    Write endpoint.
    Only the leader accepts writes from clients.
    Follower returns an error for writes.
    """
    if ROLE != "leader":
        return jsonify({"error": "writes are only accepted by the leader"}), 400

    data = request.get_json(force=True, silent=True) or {}
    if "value" not in data:
        return jsonify({"error": "JSON must have a 'value' field"}), 400

    value = data["value"]

    # 1) Apply write locally on the leader
    set_value(key, value)

    # 2) Semi-synchronous replication to followers
    #    Leader itself counts as one confirmation.
    total_nodes = 1 + len(FOLLOWER_URLS)
    required = min(max(WRITE_QUORUM, 1), total_nodes)

    # If quorum is 1, we only need the leader -> immediate success
    if required <= 1 or not FOLLOWER_URLS:
        return jsonify({
            "key": key,
            "value": value,
            "acks": 1,
            "required": required,
            "success": True,
            "role": ROLE
        }), 200

    ack_count = 1  # leader is already done
    ack_lock = threading.Lock()
    done_event = threading.Event()

    def replicate_to_follower(follower_url: str):
        nonlocal ack_count

        # simulate network lag before sending
        delay = random.uniform(MIN_DELAY_S, MAX_DELAY_S)
        time.sleep(delay)

        try:
            resp = requests.post(
                f"{follower_url}/replicate",
                json={"key": key, "value": value},
                timeout=WRITE_TIMEOUT_SEC
            )
            if resp.status_code == 200:
                with ack_lock:
                    ack_count += 1
                    # if we reached quorum, signal main thread
                    if ack_count >= required:
                        done_event.set()
        except Exception:
            # We ignore failures here; they simply don't increase ack_count
            pass

    # spawn one thread per follower
    for url in FOLLOWER_URLS:
        t = threading.Thread(
            target=replicate_to_follower,
            args=(url,),
            daemon=True
        )
        t.start()

    # Wait until either quorum reached or timeout
    done_event.wait(timeout=WRITE_TIMEOUT_SEC)

    success = ack_count >= required
    status_code = 200 if success else 503

    return jsonify({
        "key": key,
        "value": value,
        "acks": ack_count,
        "required": required,
        "success": success,
        "role": ROLE
    }), status_code

@app.route("/replicate", methods=["POST"])
def replicate():
    """
    Called by the leader to push a write to a follower.
    Follower applies the write locally and returns success.
    """
    data = request.get_json(force=True, silent=True) or {}
    key = data.get("key")
    value = data.get("value")

    if key is None or value is None:
        return jsonify({"error": "replicate expects 'key' and 'value'"}), 400

    set_value(key, value)
    return jsonify({"status": "stored", "role": ROLE}), 200

@app.route("/dump", methods=["GET"])
def dump():
    """
    Return full store (for consistency checking in tests).
    DO NOT expose in a real system; it's for the lab.
    """
    return jsonify(dump_store())

if __name__ == "__main__":
    # threaded=True => each request is handled in its own thread
    app.run(host="0.0.0.0", port=PORT, threaded=True)