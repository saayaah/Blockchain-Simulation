"""Web control center for the blockchain simulation.

The web UI can create and control multiple real blockchain peers. Each peer is
run in its own process so process-local consensus state (for example
``Chain.instance`` in the PoS implementation) is isolated correctly.
"""

import multiprocessing
import threading
import time
import uuid
from collections import deque
from datetime import datetime

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from node_worker import node_process_main

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
CORS(app)

MP = multiprocessing.get_context("spawn")
LOCK = threading.RLock()
NODES = {}


def _now():
    return datetime.now().strftime("%H:%M:%S")


def add_activity(node, message, level="info", detail=""):
    node["activity"].appendleft({
        "time": _now(),
        "level": level,
        "message": message,
        "detail": detail,
    })


def _next_request_id():
    return uuid.uuid4().hex


def _make_node_id():
    return uuid.uuid4().hex[:10]


def _node_public(node):
    cfg = node["config"]
    return {
        "id": node["id"],
        "name": cfg["name"],
        "host": cfg["host"],
        "port": cfg["p2p_port"],
        "room_id": cfg["room_id"],
        "signalling_url": cfg["signalling_url"],
        "consensus": cfg["consensus"],
        "node_mode": "malicious" if cfg["malicious"] else "normal",
        "staker": cfg["staker"],
        "load": cfg["load"],
        "save": cfg["save"],
        "status": node["status"],
        "error": node.get("error"),
    }


def _record_snapshot(node, snapshot):
    previous = node.get("last_snapshot")
    node["last_snapshot"] = snapshot

    if not snapshot:
        return
    if previous is None:
        add_activity(node, "Node state is being monitored", "success")
        return

    old_peers = len(previous.get("known_peers", []))
    new_peers = len(snapshot.get("known_peers", []))
    old_mempool = len(previous.get("mempool", []))
    new_mempool = len(snapshot.get("mempool", []))
    old_stakers = len(previous.get("current_stakers", {}))
    new_stakers = len(snapshot.get("current_stakers", {}))
    old_blocks = previous.get("chain_length", 0)
    new_blocks = snapshot.get("chain_length", 0)
    old_slashed = set(previous.get("slashed_blocks", []))
    new_slashed = set(snapshot.get("slashed_blocks", []))

    if new_peers != old_peers:
        add_activity(node, "Peer discovery updated", "success", f"{new_peers} known peer(s)")
    if new_mempool != old_mempool:
        add_activity(node, "Mempool changed", "info", f"{new_mempool} pending transaction(s)")
    if new_stakers != old_stakers:
        add_activity(node, "PoS staking set changed", "info", f"{new_stakers} active staker(s)")
    if new_blocks != old_blocks:
        if new_blocks > old_blocks:
            add_activity(node, f"Block #{new_blocks - 1} detected", "success", "Blockchain height increased")
        else:
            add_activity(node, "Blockchain height changed", "warning", f"{new_blocks} block(s)")
    for pos in sorted(new_slashed - old_slashed):
        add_activity(
            node,
            "EQUIVOCATION DETECTED — BLOCK SLASHED",
            "error",
            f"Conflicting blocks signed by the same validator at position {pos}",
        )


def _handle_worker_message(node, msg):
    kind = msg.get("type")
    if kind == "activity":
        add_activity(node, msg.get("message", "Worker activity"), msg.get("level", "info"), msg.get("detail", ""))
    elif kind == "started":
        node["status"] = "running"
        node["error"] = None
        state = msg.get("state") or {}
        node["snapshot"] = state
        _record_snapshot(node, state)
        add_activity(node, "Node is running", "success", f"{node['config']['name']} · {node['config']['host']}:{node['config']['p2p_port']}")
        add_activity(node, "Joined signalling room", "success", f"Room: {node['config']['room_id']} · {msg.get('discovered', 0)} peer(s) discovered")
    elif kind in {"error", "fatal_state"}:
        if kind == "error":
            node["error"] = msg.get("error", "Node worker error")
            node["status"] = "error"
            add_activity(node, "Node error", "error", node["error"])
        else:
            state = msg.get("state") or {}
            node["snapshot"] = state
            node["error"] = state.get("error") or node.get("error")
    elif kind == "stopped":
        node["status"] = "stopped"
        state = msg.get("state") or {}
        node["snapshot"] = state
        add_activity(node, "Node stopped", "warning")


def _node_request(node, action, timeout=8, **payload):
    """Send one command to a worker and wait for its matching response."""
    with node["request_lock"]:
        if not node["process"].is_alive() and action != "state":
            raise RuntimeError("node process is not running")

        request_id = _next_request_id()
        node["commands"].put({"id": request_id, "action": action, **payload})
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                msg = node["responses"].get(timeout=min(0.5, remaining))
            except Exception:
                continue

            _handle_worker_message(node, msg)
            if msg.get("id") != request_id:
                continue

            if not msg.get("ok", False):
                raise RuntimeError(msg.get("error") or msg.get("message") or "Node command failed")
            return msg

        raise TimeoutError(f"Timed out waiting for node '{node['config']['name']}'")


def _refresh_node(node):
    if node["status"] in {"stopped", "error"} and not node["process"].is_alive():
        return node.get("snapshot") or {}
    try:
        msg = _node_request(node, "state", timeout=3)
        snapshot = msg.get("state") or {}
        node["snapshot"] = snapshot
        return snapshot
    except Exception as exc:
        if not node["process"].is_alive():
            node["status"] = "stopped"
        node["error"] = str(exc)
        return node.get("snapshot") or {}


def _combined_state(node):
    snapshot = _refresh_node(node)
    cfg = node["config"]
    state = {
        **snapshot,
        "id": node["id"],
        "status": node["status"],
        "error": node.get("error") or snapshot.get("error"),
        "consensus": cfg["consensus"],
        "node_mode": "malicious" if cfg["malicious"] else "normal",
        "room_id": cfg["room_id"],
        "signalling_url": cfg["signalling_url"],
        "activity": list(node["activity"]),
    }
    return state


def _validate_config(data):
    host = str(data.get("host", "127.0.0.1")).strip() or "127.0.0.1"
    name = str(data.get("name", "")).strip()
    room_id = str(data.get("room_id", "")).strip()
    signalling_url = str(data.get("signalling_url", "ws://127.0.0.1:8765")).strip()
    consensus = str(data.get("consensus", "pos")).lower().strip()
    try:
        port = int(data.get("p2p_port", 0))
    except (TypeError, ValueError):
        port = 0

    if not name:
        raise ValueError("node name is required")
    if not 1 <= port <= 65535:
        raise ValueError("invalid P2P port")
    if consensus not in {"pos", "pow", "poa"}:
        raise ValueError("unsupported consensus")
    if not room_id:
        raise ValueError("room ID is required")
    if not signalling_url.startswith(("ws://", "wss://")):
        raise ValueError("signalling URL must start with ws:// or wss://")

    with LOCK:
        for existing in NODES.values():
            cfg = existing["config"]
            if cfg["name"].lower() == name.lower() and existing["status"] != "stopped":
                raise ValueError(f"node name '{name}' is already running in this web control center")
            if cfg["p2p_port"] == port and existing["status"] != "stopped":
                raise ValueError(f"P2P port {port} is already used by node '{cfg['name']}'")

    return {
        "host": host,
        "p2p_port": port,
        "name": name,
        "room_id": room_id,
        "signalling_url": signalling_url,
        "consensus": consensus,
        "malicious": bool(data.get("malicious", False)),
        "staker": bool(data.get("staker", True)),
        "miner": bool(data.get("miner", True)),
        "load": bool(data.get("load", False)),
        "save": bool(data.get("save", False)),
    }


def create_node(data):
    config = _validate_config(data)
    node_id = _make_node_id()
    commands = MP.Queue()
    responses = MP.Queue()
    process = MP.Process(target=node_process_main, args=(config, commands, responses), daemon=True)
    node = {
        "id": node_id,
        "config": config,
        "commands": commands,
        "responses": responses,
        "process": process,
        "request_lock": threading.Lock(),
        "status": "starting",
        "error": None,
        "snapshot": {},
        "last_snapshot": None,
        "activity": deque(maxlen=80),
    }
    add_activity(node, "Starting node process", "info", f"{config['host']}:{config['p2p_port']}")

    with LOCK:
        NODES[node_id] = node
    process.start()
    return node


def stop_node(node):
    if node["status"] == "stopped":
        return
    try:
        if node["process"].is_alive():
            _node_request(node, "stop", timeout=4)
            node["process"].join(timeout=2)
            if node["process"].is_alive():
                node["process"].terminate()
                node["process"].join(timeout=2)
    finally:
        node["status"] = "stopped"
        add_activity(node, "Node stopped", "warning")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    with LOCK:
        running = sum(1 for n in NODES.values() if n["process"].is_alive())
    return jsonify({"ok": True, "status": "running" if running else "stopped", "nodes": running})


@app.get("/api/nodes")
def list_nodes():
    with LOCK:
        items = [_node_public(n) for n in NODES.values()]
    return jsonify({"nodes": items})


@app.post("/api/nodes")
def api_create_node():
    try:
        node = create_node(request.get_json(silent=True) or {})
        return jsonify({"ok": True, "node": _node_public(node)}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/state")
def state():
    node_id = request.args.get("node_id", "").strip()
    with LOCK:
        if not node_id and NODES:
            node_id = next(iter(NODES))
        node = NODES.get(node_id)
    if node is None:
        return jsonify({"status": "stopped", "nodes": []})

    data = _combined_state(node)
    with LOCK:
        data["nodes"] = [_node_public(n) for n in NODES.values()]
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return jsonify(data)


@app.post("/api/nodes/<node_id>/transaction")
def node_transaction(node_id):
    with LOCK:
        node = NODES.get(node_id)
    if not node:
        return jsonify({"error": "node not found"}), 404
    data = request.get_json(silent=True) or {}
    try:
        receiver = str(data.get("receiver", "")).strip()
        amount = float(data.get("amount", 0))
        if not receiver:
            raise ValueError("receiver is required")
        if amount <= 0:
            raise ValueError("amount must be positive")
        result = _node_request(node, "transaction", timeout=12, receiver=receiver, amount=amount)
        tx_id = result.get("tx_id", "")
        add_activity(node, "Transaction broadcast", "success", f"Receiver: {receiver} · Amount: {amount:g}" + (f" · TX {tx_id}" if tx_id else ""))
        return jsonify({"ok": True, "message": "transaction broadcast", "tx_id": tx_id})
    except Exception as exc:
        add_activity(node, "Transaction rejected", "error", str(exc))
        return jsonify({"error": str(exc)}), 400


@app.post("/api/nodes/<node_id>/stake")
def node_stake(node_id):
    with LOCK:
        node = NODES.get(node_id)
    if not node:
        return jsonify({"error": "node not found"}), 404
    try:
        amount = int((request.get_json(silent=True) or {}).get("amount", 0))
        if amount <= 0:
            raise ValueError("stake amount must be positive")
        if node["config"]["consensus"] != "pos":
            raise ValueError("PoS staking is available only in PoS mode")
        result = _node_request(node, "stake", timeout=12, amount=amount)
        delay = result.get("delay")
        detail = f"Amount: {amount}" + (f" · VRF attempt in about {delay}s" if delay is not None else "")
        add_activity(node, "Stake announced", "success", detail)
        return jsonify({"ok": True, "message": "stake announced", "delay": delay})
    except Exception as exc:
        add_activity(node, "Stake rejected", "error", str(exc))
        return jsonify({"error": str(exc)}), 400


@app.post("/api/nodes/<node_id>/sync")
def node_sync(node_id):
    with LOCK:
        node = NODES.get(node_id)
    if not node:
        return jsonify({"error": "node not found"}), 404
    try:
        result = _node_request(node, "sync", timeout=14)
        if result.get("ok"):
            add_activity(node, "Blockchain synchronized", "success")
            return jsonify({"ok": True, "message": "blockchain synchronized"})
        return jsonify({"error": result.get("message", "not synchronized")}), 409
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/nodes/<node_id>/stop")
def node_stop(node_id):
    with LOCK:
        node = NODES.get(node_id)
    if not node:
        return jsonify({"error": "node not found"}), 404
    stop_node(node)
    return jsonify({"ok": True})


# Backward-compatible routes used by the earlier single-node UI.
@app.post("/api/start")
def legacy_start():
    return api_create_node()


@app.post("/api/transaction")
def legacy_transaction():
    with LOCK:
        running = [n for n in NODES.values() if n["status"] == "running"]
    if not running:
        return jsonify({"error": "no running node"}), 409
    request_payload = request.get_json(silent=True) or {}
    node = running[0]
    try:
        receiver = str(request_payload.get("receiver", "")).strip()
        amount = float(request_payload.get("amount", 0))
        _node_request(node, "transaction", receiver=receiver, amount=amount)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/stake")
def legacy_stake():
    with LOCK:
        running = [n for n in NODES.values() if n["status"] == "running"]
    if not running:
        return jsonify({"error": "no running node"}), 409
    try:
        amount = int((request.get_json(silent=True) or {}).get("amount", 0))
        _node_request(running[0], "stake", amount=amount)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/stop")
def legacy_stop():
    with LOCK:
        running = [n for n in NODES.values() if n["status"] == "running"]
    if running:
        stop_node(running[0])
    return jsonify({"ok": True})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Blockchain simulation web interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
