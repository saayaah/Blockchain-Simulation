"""Client for the room-based signalling service."""
import asyncio
import json
import websockets


class SignallingClient:
    def __init__(self, server_url: str, room_id: str, peer):
        self.server_url = server_url.rstrip("/")
        self.room_id = room_id.strip()
        self.peer = peer
        self.websocket = None
        self.last_peers = []

    def _registration(self):
        return {
            "type": "register",
            "room_id": self.room_id,
            "node": {
                "host": self.peer.host,
                "port": self.peer.port,
                "name": self.peer.name,
                "public_key": self.peer.wallet.public_key_pem,
            },
        }

    @staticmethod
    def _endpoint(node):
        try:
            return node.get("host"), int(node.get("port"))
        except (TypeError, ValueError, AttributeError):
            return None, None

    async def register(self):
        self.websocket = await websockets.connect(self.server_url)
        await self.websocket.send(json.dumps(self._registration()))
        msg = json.loads(await self.websocket.recv())
        if msg.get("type") == "error":
            await self.websocket.close()
            raise RuntimeError(msg.get("error", "signalling registration failed"))
        if msg.get("type") != "room_peers":
            await self.websocket.close()
            raise RuntimeError("unexpected signalling response")
        self.last_peers = list(msg.get("peers", []))
        return [self._endpoint(p) for p in self.last_peers if self._endpoint(p)[0] and self._endpoint(p)[1]]

    async def watch(self):
        try:
            async for raw in self.websocket:
                msg = json.loads(raw)
                if msg.get("type") == "peer_joined":
                    peer = msg.get("peer") or {}
                    host, port = self._endpoint(peer)
                    if host and port:
                        await self.peer.connect_to_peer(host, port)
                elif msg.get("type") == "peer_left":
                    peer = msg.get("peer") or {}
                    host, port = self._endpoint(peer)
                    if host and port:
                        self.peer.known_peers.pop((host, port), None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Signalling connection closed: {exc}")

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
