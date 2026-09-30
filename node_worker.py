"""Isolated blockchain peer worker used by the web control center.

Each browser-created node runs in its own process. This is important because
some of the original consensus implementations keep process-local state such
as Chain.instance. Keeping one real peer per process lets multiple browser-
created nodes coexist without sharing blockchain state.
"""

import asyncio
import base64
import os
import queue
import traceback
from datetime import datetime, timedelta

from signalling_client import SignallingClient
from start_peer import build_peer


async def _idle_input_handler(self):
    """Replace the original terminal menu when a peer is web-controlled."""
    await asyncio.Event().wait()


def _block_json(block):
    data = {}
    try:
        data.update(block.to_dict())
    except Exception:
        pass
    data.update({
        "hash": getattr(block, "hash", ""),
        "creator": getattr(block, "creator", ""),
        "staked_amt": getattr(block, "staked_amt", 0),
        "is_valid": getattr(block, "is_valid", True),
        "slash_creator": getattr(block, "slash_creator", False),
        "seed": getattr(block, "seed", ""),
    })
    proof = getattr(block, "vrf_proof", None)
    data["vrf_proof"] = base64.b64encode(proof).decode("ascii") if proof else ""
    data["stakers"] = []
    for stake in getattr(block, "stakers", []) or []:
        data["stakers"].append({
            "staker": getattr(stake, "staker", ""),
            "amount": getattr(stake, "amt", 0),
            "id": getattr(stake, "id", ""),
            "timestamp": getattr(stake, "ts", 0),
        })
    return data


def _snapshot(peer, chain_sync, error=None):
    chain = getattr(peer, "chain", None)
    if chain is None:
        # Some consensus implementations expose the chain through the class.
        chain = getattr(peer.__class__, "chain", None)

    blocks = []
    if chain is not None and getattr(chain, "chain", None) is not None:
        blocks = [_block_json(b) for b in chain.chain[-50:]]

    known = getattr(peer, "known_peers", {}) or {}
    peers = [
        {"host": h, "port": p, "name": n, "public_key": pk}
        for (h, p), (n, pk) in known.items()
    ]

    mempool_objects = getattr(peer, "mem_pool", []) or []
    mempool = [
        {
            "id": getattr(tx, "id", ""),
            "sender": getattr(tx, "sender", ""),
            "receiver": getattr(tx, "receiver", ""),
            "payload": getattr(tx, "payload", ""),
            "timestamp": getattr(tx, "ts", 0),
        }
        for tx in mempool_objects
    ]

    balance = None
    if chain is not None:
        try:
            balance = chain.calc_balance(
                peer.wallet.public_key_pem,
                mempool_objects,
                list(getattr(peer, "current_stakes", set()) or set()),
            )
        except Exception:
            balance = None

    return {
        "name": peer.name,
        "host": peer.host,
        "port": peer.port,
        "public_key": peer.wallet.public_key_pem,
        "balance": balance,
        "staked_amount": getattr(peer, "staked_amt", 0),
        "current_stakers": getattr(peer, "current_stakers", {}) or {},
        "known_peers": peers,
        "outbound_peers": [list(p) for p in getattr(peer, "outbound_peers", set())],
        "mempool": mempool,
        "chain_length": len(chain.chain) if chain is not None else 0,
        "blocks": blocks,
        "slashed_blocks": [
            i for i, block in enumerate(chain.chain)
            if getattr(block, "slash_creator", False)
        ] if chain is not None and getattr(chain, "chain", None) is not None else [],
        "equivocation_detected": any(
            getattr(block, "slash_creator", False) for block in chain.chain
        ) if chain is not None and getattr(chain, "chain", None) is not None else False,
        "chain_sync": chain_sync,
        "error": error,
    }


async def _request_chain(peer):
    if not hasattr(peer, "broadcast_message"):
        return
    packet = {"type": "chain_request", "id": __import__("uuid").uuid4().hex}
    try:
        peer.seen_message_ids.add(packet["id"])
    except Exception:
        pass
    await peer.broadcast_message(packet)


async def _sync_chain(peer, seconds=10):
    for _ in range(seconds):
        if getattr(peer, "chain", None) is not None:
            return "synced"
        try:
            await _request_chain(peer)
        except Exception:
            pass
        await asyncio.sleep(1)
    return "synced" if getattr(peer, "chain", None) is not None else "not synchronized"


async def _run(config, command_queue, response_queue):
    peer = None
    signal_client = None
    peer_task = None
    watch_task = None
    chain_sync = "starting"
    error = None
    stopping = False

    try:
        peer = build_peer(
            config["host"],
            config["p2p_port"],
            config["name"],
            config["consensus"],
            config["malicious"],
            config["staker"],
            config["miner"],
            "y" if config["load"] else "n",
            "y" if config["save"] else "n",
        )

        # Prevent the original interactive terminal menu from competing with
        # the browser. The consensus background tasks remain unchanged.
        peer.user_input_handler = _idle_input_handler.__get__(peer, type(peer))

        peers = []
        if config["room_id"]:
            signal_client = SignallingClient(config["signalling_url"], config["room_id"], peer)
            peers = await signal_client.register()

            existing_names = {
                str(p.get("name", "")).strip().lower()
                for p in getattr(signal_client, "last_peers", [])
            }
            if peer.name.lower() in existing_names:
                raise RuntimeError(
                    f"Node name '{peer.name}' is already used in room '{config['room_id']}'."
                )

        initial_peer = peers[0] if peers else None
        bootstrap_host, bootstrap_port = initial_peer if initial_peer else (None, None)

        peer_task = asyncio.create_task(peer.start(bootstrap_host, bootstrap_port))
        if signal_client:
            watch_task = asyncio.create_task(signal_client.watch())

        # The first peer is the bootstrap source discovered through the
        # signalling server. Ask for its chain immediately and wait briefly
        # for the result so the dashboard reflects real synchronization state.
        if initial_peer is None:
            chain_sync = "synced"
        else:
            chain_sync = await _sync_chain(peer, seconds=15)

        response_queue.put({
            "type": "started",
            "state": _snapshot(peer, chain_sync),
            "discovered": len(peers),
        })

        while not peer_task.done():
            # Commands are deliberately handled by the same asyncio loop as
            # the peer so calls such as transaction/stake remain thread-safe.
            try:
                command = await asyncio.to_thread(command_queue.get, True, 0.20)
            except queue.Empty:
                continue

            request_id = command.get("id", "")
            action = command.get("action")

            try:
                if action == "state":
                    response_queue.put({
                        "id": request_id,
                        "ok": True,
                        "state": _snapshot(peer, chain_sync, error),
                    })

                elif action == "sync":
                    chain_sync = await _sync_chain(peer, seconds=10)
                    response_queue.put({"id": request_id, "ok": chain_sync == "synced", "message": chain_sync})

                elif action == "transaction":
                    receiver = str(command.get("receiver", "")).strip()
                    amount = float(command.get("amount", 0))
                    if not receiver or amount <= 0:
                        raise ValueError("receiver and positive amount are required")
                    if getattr(peer, "chain", None) is None:
                        chain_sync = await _sync_chain(peer, seconds=10)
                    receiver_key = getattr(peer, "name_to_public_key_dict", {}).get(receiver.lower(), receiver)
                    created = await peer.create_and_broadcast_tx(receiver_key, amount)
                    response_queue.put({
                        "id": request_id,
                        "ok": True,
                        "message": "transaction broadcast",
                        "tx_id": getattr(created, "id", ""),
                        "sender": getattr(created, "sender", getattr(peer.wallet, "public_key_pem", "")),
                        "receiver": getattr(created, "receiver", receiver_key),
                        "amount": getattr(created, "payload", amount),
                    })

                elif action == "stake":
                    amount = int(command.get("amount", 0))
                    if amount <= 0:
                        raise ValueError("stake amount must be positive")
                    if not hasattr(peer, "send_stake_announcements"):
                        raise ValueError("this node does not support PoS staking")
                    if getattr(peer, "staked_amt", 0) > 0:
                        raise ValueError("a stake is already active for this epoch")

                    # Match the original terminal PoS flow: announcing a stake
                    # also schedules the epoch's block-creation attempt.
                    # The consensus implementation itself remains unchanged.
                    now = datetime.now()
                    last_epoch = getattr(peer, "last_epoch_end_ts", now)
                    elapsed = max(0, int((now - last_epoch).total_seconds()))
                    epoch_time = 60
                    try:
                        from consensus.pos.p2p import EPOCH_TIME as POS_EPOCH_TIME
                        epoch_time = POS_EPOCH_TIME
                    except Exception:
                        pass

                    # Mirror the original terminal PoS epoch handling. If the
                    # previous epoch is fully expired, start a fresh epoch
                    # before registering the new stake. Without this reset,
                    # time_left can become 0 and the background epoch task can
                    # clear the newly registered stake at the same moment the
                    # VRF attempt runs.
                    if elapsed > int(epoch_time * 7 / 6):
                        peer.last_epoch_end_ts = now
                        peer.staked_amt = 0
                        async with peer.curr_stakers_condition:
                            peer.current_stakers.clear()
                            peer.current_stakes.clear()
                        elapsed = 0
                    elif elapsed > int(epoch_time * 5 / 6):
                        raise ValueError(
                            f"stake registration period closed; try again in the next epoch (about {epoch_time - elapsed}s)"
                        )

                    time_left = max(0, epoch_time - elapsed)

                    await peer.send_stake_announcements(amount)
                    response_queue.put({
                        "id": request_id,
                        "ok": True,
                        "message": "stake announced; PoS block attempt scheduled",
                        "event": "stake_scheduled",
                        "delay": time_left,
                    })

                    async def scheduled_block_attempt(delay):
                        response_queue.put({
                            "type": "activity",
                            "level": "info",
                            "message": "PoS block attempt scheduled",
                            "detail": f"VRF evaluation in about {delay}s",
                        })
                        await asyncio.sleep(delay)
                        before = 0
                        try:
                            before = len(peer.chain.chain)
                        except Exception:
                            pass
                        response_queue.put({
                            "type": "activity",
                            "level": "info",
                            "message": "PoS / VRF evaluation started",
                            "detail": "Checking the active stake set and pending transactions",
                        })
                        await peer.create_blocks(0)
                        after = before
                        try:
                            after = len(peer.chain.chain)
                        except Exception:
                            pass
                        if after > before:
                            response_queue.put({
                                "type": "activity",
                                "level": "success",
                                "message": f"Block #{after - 1} created",
                                "detail": "PoS validator won the VRF selection and broadcast the block",
                            })
                        else:
                            response_queue.put({
                                "type": "activity",
                                "level": "warning",
                                "message": "No block created this epoch",
                                "detail": "The validator did not win the VRF selection or no transaction was eligible",
                            })

                    asyncio.create_task(scheduled_block_attempt(time_left))

                elif action == "stop":
                    stopping = True
                    response_queue.put({"id": request_id, "ok": True, "message": "stopping"})
                    break

                else:
                    raise ValueError(f"unknown node command: {action}")

            except Exception as exc:
                response_queue.put({"id": request_id, "ok": False, "error": str(exc)})

        if peer_task and not peer_task.done():
            peer_task.cancel()
            await asyncio.gather(peer_task, return_exceptions=True)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        response_queue.put({"type": "error", "error": error})
        response_queue.put({
            "type": "fatal_state",
            "state": _snapshot(peer, chain_sync, error) if peer else {"error": error},
        })
    finally:
        if watch_task:
            watch_task.cancel()
            await asyncio.gather(watch_task, return_exceptions=True)
        if signal_client:
            try:
                await signal_client.close()
            except Exception:
                pass
        if peer and getattr(peer, "daemon_process", None):
            try:
                peer.stop_daemon()
            except Exception:
                pass
        response_queue.put({
            "type": "stopped",
            "state": _snapshot(peer, chain_sync, error) if peer else {"error": error},
            "requested": stopping,
        })


def node_process_main(config, command_queue, response_queue):
    """Process entry point. Safe for Windows multiprocessing spawn."""
    asyncio.run(_run(config, command_queue, response_queue))
