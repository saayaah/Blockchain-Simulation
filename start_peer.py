import argparse
import asyncio

from consensus.poa.p2p import Peer as PoAPeer
from consensus.pos.p2p import Peer as PoSPeer
from consensus.pow.p2p import Peer as PoWPeer
from consensus.poa.mal_node import Peer as PoaMalPeer
from consensus.pos.mal_node import Peer as PosMalPeer
from consensus.pow.mal_node import Peer as PowMalPeer
from signalling_client import SignallingClient


def build_peer(host, port, name, consensus, malicious, staker, miner,
               activate_disk_load, activate_disk_save):
    consensus = consensus.lower().strip() or "pow"
    if consensus == "poa":
        return PoaMalPeer(host, port, name, activate_disk_load, activate_disk_save) if malicious else PoAPeer(host, port, name, activate_disk_load, activate_disk_save)
    if consensus == "pos":
        if malicious:
            return PosMalPeer(host, port, name, True, activate_disk_load, activate_disk_save)
        return PoSPeer(host, port, name, staker, activate_disk_load, activate_disk_save)
    return PowMalPeer(host, port, name, True, activate_disk_load, activate_disk_save) if malicious else PoWPeer(host, port, name, miner, activate_disk_load, activate_disk_save)


async def run_peer(peer, room_id=None, signalling_url="ws://127.0.0.1:8765", bootstrap_host=None, bootstrap_port=None):
    signal_client = None
    watch_task = None

    if room_id:
        signal_client = SignallingClient(signalling_url, room_id, peer)
        peers = await signal_client.register()
        if peers and not (bootstrap_host and bootstrap_port):
            bootstrap_host, bootstrap_port = peers[0]

    peer_task = asyncio.create_task(peer.start(bootstrap_host, bootstrap_port))

    # Keep the room membership live while the peer runs. New members are
    # connected directly; the signalling service never carries blockchain data.
    if signal_client:
        watch_task = asyncio.create_task(signal_client.watch())

    try:
        await peer_task
    finally:
        if watch_task:
            watch_task.cancel()
            await asyncio.gather(watch_task, return_exceptions=True)
        if signal_client:
            await signal_client.close()


def start_peer():
    parser = argparse.ArgumentParser(description="Blockchain simulation peer")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--consensus", choices=["poa", "pos", "pow"], default=None)
    parser.add_argument("--room", default=None, help="Room ID for signalling-based discovery")
    parser.add_argument("--signalling", default="ws://127.0.0.1:8765")
    parser.add_argument("--bootstrap-host", default=None, help="Legacy bootstrap fallback")
    parser.add_argument("--bootstrap-port", type=int, default=None)
    parser.add_argument("--load", choices=["y", "n"], default=None)
    parser.add_argument("--save", choices=["y", "n"], default=None)
    parser.add_argument("--malicious", action="store_true")
    parser.add_argument("--staker", choices=["y", "n"], default=None)
    parser.add_argument("--miner", choices=["y", "n"], default=None)
    args = parser.parse_args()

    host = args.host or input("Enter Host [127.0.0.1]: ").strip() or "127.0.0.1"
    port = args.port or int(input("Enter Port: "))
    name = args.name or input("Enter Name: ").strip()
    consensus = args.consensus or (input("Enter Consensus[poa/pos/pow] (default: pow): ").strip().lower() or "pow")
    load = args.load or (input("Load saved data if any? (y/n): ").strip().lower() or "n")
    save = args.save or (input("Continuously backup data to disk? (y/n): ").strip().lower() or "n")

    malicious = args.malicious
    if not args.malicious:
        malicious = input("Malicious? (y/n): ").strip().lower() == "y"

    staker = True
    miner = True
    if consensus == "pos" and not malicious:
        staker = (args.staker or (input("Staker? (y/n, default y): ").strip().lower() or "y")) == "y"
    if consensus == "pow" and not malicious:
        miner = (args.miner or (input("Miner? (y/n, default y): ").strip().lower() or "y")) == "y"

    room_id = args.room
    if room_id is None:
        room_id = input("Room ID (leave blank for legacy bootstrap mode): ").strip()

    bootstrap_host = args.bootstrap_host
    bootstrap_port = args.bootstrap_port
    if not room_id and bootstrap_host is None:
        action = input("Enter 'create' for a standalone network or 'connect' for legacy bootstrap: ").strip().lower() or "create"
        if action == "connect":
            bootstrap_host = input("Enter bootstrap host: ").strip()
            bootstrap_port = int(input("Enter bootstrap port: "))

    peer = build_peer(host, port, name, consensus, malicious, staker, miner, load, save)

    try:
        asyncio.run(run_peer(peer, room_id or None, args.signalling, bootstrap_host, bootstrap_port))
    except KeyboardInterrupt:
        print("\nShutting Down...")


if __name__ == "__main__":
    start_peer()
