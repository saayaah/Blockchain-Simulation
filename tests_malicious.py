"""Regression tests for PoS equivocation/slashing evidence."""
import asyncio

from consensus.pos.blockchain_structures import Wallet, Block, Chain
from consensus.pos.p2p import Peer as HonestPeer
from consensus.pos.mal_node import Peer as MaliciousPeer


async def exercise(peer_cls):
    Chain.instance = None
    wallet = Wallet()
    chain = Chain(publicKey=wallet.public_key_pem, privatekey=wallet.private_key)

    block1 = Block(chain.lastBlock.hash, [])
    block1.creator = wallet.public_key_pem
    block1.sign = wallet.private_key.sign(str(block1).encode())
    chain.chain.append(block1)

    block2 = Block(block1.prevHash, [
        # Different transaction content makes this a genuinely conflicting
        # block at the same position/parent.
    ])
    block2.creator = wallet.public_key_pem
    block2.id = "equivocation-test"
    block2.sign = wallet.private_key.sign(str(block2).encode())

    peer = object.__new__(peer_cls)
    broadcasted = []
    async def capture(pkt):
        broadcasted.append(pkt)
    peer.broadcast_message = capture

    await peer.verify_and_slash(block1, block2, 1, [chain.chain[0], block2])

    assert chain.chain[1].is_valid is False
    assert chain.chain[1].slash_creator is True
    assert len(broadcasted) == 1
    assert broadcasted[0]["type"] == "slash_announcement"


def main():
    asyncio.run(exercise(HonestPeer))
    asyncio.run(exercise(MaliciousPeer))
    print("Malicious equivocation/slashing tests: PASS")


if __name__ == "__main__":
    main()
