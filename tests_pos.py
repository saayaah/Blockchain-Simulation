"""Regression tests for PoS consensus invariants."""
from consensus.pos.blockchain_structures import Wallet, Stake, Block, Chain, isvalidChain


def setup():
    Chain.instance = None
    w = Wallet()
    chain = Chain(publicKey=w.public_key_pem, privatekey=w.private_key)
    return w, chain


def valid_block(wallet, chain, stake_amount=10):
    stake = Stake(wallet.public_key_pem, stake_amount)
    stake.sign = wallet.private_key.sign(str(stake).encode())
    block = Block(chain.lastBlock.hash, [])
    block.creator = wallet.public_key_pem
    block.staked_amt = stake_amount
    block.stakers = [stake]
    block.seed = chain.epoch_seed()
    block.vrf_proof = wallet.private_key.sign(block.seed.encode())
    block.sign = wallet.private_key.sign(str(block).encode())
    return block


def test_valid_block():
    w, chain = setup()
    block = valid_block(w, chain)
    assert chain.isValidBlock(block, {w.public_key_pem: 10})


def test_selected_stake_cannot_exceed_creator_stake():
    w, chain = setup()
    block = valid_block(w, chain, 10)
    block.staked_amt = 11
    block.sign = w.private_key.sign(str(block).encode())
    assert not chain.isValidBlock(block, {w.public_key_pem: 10})


def test_creator_must_be_staker():
    w, chain = setup()
    other = Wallet()
    stake = Stake(other.public_key_pem, 10)
    stake.sign = other.private_key.sign(str(stake).encode())
    block = Block(chain.lastBlock.hash, [])
    block.creator = w.public_key_pem
    block.staked_amt = 10
    block.stakers = [stake]
    block.seed = chain.epoch_seed()
    block.vrf_proof = w.private_key.sign(block.seed.encode())
    block.sign = w.private_key.sign(str(block).encode())
    assert not chain.isValidBlock(block, {w.public_key_pem: 10})


def test_strict_vrf_threshold():
    w, chain = setup()
    block = valid_block(w, chain, 10)
    # A forged zero-length proof cannot be a valid signature, and a proof that
    # does not verify against the creator/seed must be rejected.
    block.vrf_proof = w.private_key.sign(b"wrong seed")
    block.sign = w.private_key.sign(str(block).encode())
    assert not chain.isValidBlock(block, {w.public_key_pem: 10})


def test_competing_stake_cannot_be_omitted_from_live_snapshot():
    w, chain = setup()
    other = Wallet()
    block = valid_block(w, chain, 10)
    # The local epoch registry knows another validator has 100 coins staked.
    # A block that omits that validator must not be accepted as a 100% lottery.
    assert not chain.isValidBlock(block, {w.public_key_pem: 10, other.public_key_pem: 100})


if __name__ == "__main__":
    test_valid_block()
    test_selected_stake_cannot_exceed_creator_stake()
    test_creator_must_be_staker()
    test_strict_vrf_threshold()
    test_competing_stake_cannot_be_omitted_from_live_snapshot()
    print("PoS regression tests: PASS")
