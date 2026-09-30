"""Room-based signalling server for the blockchain simulation.

The signalling server is only a rendezvous service. It does not relay blockchain
messages; after discovery, nodes connect directly to each other's websocket
ports. Rooms are identified by a caller-supplied room ID.
"""
import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, Set

import websockets

LOG = logging.getLogger("signalling")


@dataclass(eq=False)
class Client:
    websocket: object
    node: dict
    room_id: str


class SignallingServer:
    def __init__(self):
        self.rooms: Dict[str, Set[Client]] = {}
        self.lock = asyncio.Lock()

    @staticmethod
    def _public_node(node: dict) -> dict:
        return {
            "host": node["host"],
            "port": int(node["port"]),
            "name": node["name"],
            "public_key": node["public_key"],
        }

    async def handler(self, websocket):
        client = None
        try:
            raw = await websocket.recv()
            msg = json.loads(raw)
            if msg.get("type") != "register":
                await websocket.send(json.dumps({"type": "error", "error": "first message must be register"}))
                return

            room_id = str(msg.get("room_id", "")).strip()
            node = msg.get("node") or {}
            required = {"host", "port", "name", "public_key"}
            if not room_id or not required.issubset(node):
                await websocket.send(json.dumps({"type": "error", "error": "room_id and complete node info are required"}))
                return

            client = Client(websocket, self._public_node(node), room_id)
            async with self.lock:
                room = self.rooms.setdefault(room_id, set())
                peers = [c.node for c in room]
                room.add(client)

            await websocket.send(json.dumps({"type": "room_peers", "room_id": room_id, "peers": peers}))
            LOG.info("%s joined room %s", node["name"], room_id)

            joined = {"type": "peer_joined", "room_id": room_id, "peer": client.node}
            await self.broadcast(room_id, joined, exclude=client)

            async for raw in websocket:
                # Signalling is intentionally limited to membership messages.
                # Unknown messages are ignored rather than becoming a relay path.
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))

        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception:
            LOG.exception("Signalling client error")
        finally:
            if client is not None:
                async with self.lock:
                    room = self.rooms.get(client.room_id)
                    if room:
                        room.discard(client)
                        if not room:
                            self.rooms.pop(client.room_id, None)
                await self.broadcast(client.room_id, {"type": "peer_left", "peer": client.node}, exclude=client)
                LOG.info("%s left room %s", client.node["name"], client.room_id)

    async def broadcast(self, room_id: str, message: dict, exclude=None):
        async with self.lock:
            clients = list(self.rooms.get(room_id, set()))
        data = json.dumps(message)
        stale = []
        for client in clients:
            if client is exclude:
                continue
            try:
                await client.websocket.send(data)
            except Exception:
                stale.append(client)
        if stale:
            async with self.lock:
                room = self.rooms.get(room_id, set())
                for client in stale:
                    room.discard(client)

    async def run(self, host: str, port: int):
        async with websockets.serve(self.handler, host, port):
            LOG.info("Signalling server listening on ws://%s:%d", host, port)
            await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description="Blockchain room signalling server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(SignallingServer().run(args.host, args.port))


if __name__ == "__main__":
    main()
