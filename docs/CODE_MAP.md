# Code Map — Where Each Demo Step Happens

| Demo step | Main code | What happens |
|---|---|---|
| Browser creates node | `web_interface.py` | Creates a separate worker process for each real peer. |
| Worker starts peer | `node_worker.py` | Builds the actual PoS/PoW/PoA peer and joins the signalling room. |
| Peer discovery | `signalling_client.py`, `signalling_server.py` | Same-room nodes discover endpoints; signalling does not carry blockchain data. |
| Direct P2P | `consensus/pos/p2p.py` | WebSocket peer connections carry transactions, stakes, blocks and chain requests. |
| Transaction button | `web/static/app.js` → `/api/nodes/<id>/transaction` | Browser calls the real peer's transaction method. |
| Transaction mempool | `consensus/pos/p2p.py` | Received transaction is validated and placed in the mempool. |
| Stake button | `web/static/app.js` → `/api/nodes/<id>/stake` | Browser calls the real peer's stake-announcement method. |
| Web PoS scheduling | `node_worker.py` | After a web stake announcement, schedules the same `create_blocks()` epoch attempt used by the terminal flow. |
| VRF | `consensus/pos/p2p.py` | Epoch seed, signed VRF proof, threshold and validator selection are evaluated. |
| Block creation | `consensus/pos/p2p.py:create_blocks()` | Selected validator creates, signs and broadcasts the block. |
| Block validation | `consensus/pos/p2p.py` + `consensus/pos/blockchain_structures.py` | Peers validate block signatures, VRF/stake data, transactions and chain rules. |
| Malicious block test | `consensus/pos/mal_node.py` | Malicious PoS peer exercises competing-block/fork handling when selected. |
| Live dashboard | `web/static/app.js` + `web/templates/index.html` | Polls real worker state and shows propagation, mempool, stake, blocks and activity. |
| Backend activity | `web_interface.py` + `node_worker.py` | Converts worker events/state changes into the live activity feed. |
