# Assignment Requirements and Implementation Map

## Problem statement

The project is a simplified blockchain network simulation. The required work is:

1. Identify and fix intentional bugs in Proof of Stake consensus.
2. Add/extend a signalling server with room IDs, create/join network behaviour and peer discovery without predefined bootstrap configuration.
3. Provide a web interface exposing core functionality and meaningful visibility into the blockchain and participating nodes.
4. Support malicious-node testing so network resilience and consensus validation can be demonstrated.

## Implementation map

| Requirement | Implementation |
|---|---|
| PoS bug fixing | `consensus/pos/blockchain_structures.py`, `consensus/pos/p2p.py` and PoS regression tests |
| VRF validation | Deterministic epoch seed + proof validation + strict threshold comparison |
| Duplicate transaction protection | Chain/block validation |
| Signalling | `signalling_server.py` + `signalling_client.py` |
| Room discovery | Room ID registration and peer discovery |
| Direct P2P | Consensus peer websocket connections |
| Multiple web peers | `web_interface.py` + `node_worker.py` using one OS process per node |
| Transactions | Browser transaction form + real peer transaction creation/broadcast |
| PoS staking | Browser stake form + real peer stake announcement |
| PoS scheduling | Web worker schedules `create_blocks()` after stake, matching terminal PoS flow |
| Blockchain visibility | Explorer with blocks, hashes, creator, stake, VRF data and validation |
| Node visibility | Node cards, active-node selector, peer list and status |
| Live propagation | Transaction propagation panel + polling + activity log |
| Malicious mode | Existing PoS malicious peer selected through browser checkbox |
| Regression testing | `tests_pos.py` |
| Project preflight | `verify_project.py` |

## Demo acceptance checklist

- [ ] Signalling server starts on port 8765.
- [ ] Web interface starts on port 8000.
- [ ] Two browser-created PoS nodes can join the same room.
- [ ] Each node sees the other as a peer.
- [ ] A transaction reaches the receiving node's mempool.
- [ ] A PoS stake is visible as an active staker.
- [ ] The web worker schedules the block attempt.
- [ ] VRF/block creation is visible in activity.
- [ ] A valid block is broadcast and synchronized.
- [ ] The transaction leaves the mempool after inclusion.
- [x] Malicious mode can be enabled for a third PoS node.
- [x] Same-validator conflicting blocks are detected as equivocation before historical chain validation.
- [x] Valid slashing evidence marks the conflicting block invalid and broadcasts a slash announcement.
- [ ] `tests_pos.py` passes on the target machine.
