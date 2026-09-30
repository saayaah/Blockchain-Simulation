# 5-Minute Demo Runbook

## Start

```powershell
cd "C:\Users\adils\Downloads\Blockchain-Simulation-submission-readymade"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Terminal 1:

```powershell
python signalling_server.py --host 127.0.0.1 --port 8765
```

Terminal 2:

```powershell
python web_interface.py --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Demo

1. Click **+ Create / Join Node**.
2. Create `webnode` on `5003`, room `demo-room`, PoS, staker ON.
3. Click **+ Create / Join Node** again.
4. Create `bob` on `5004`, same room, PoS, staker OFF.
5. Select `webnode`.
6. Send `10` to `bob`.
7. Switch to Bob and show **Peer received** / mempool.
8. Switch back to webnode and stake `10`.
9. Point at the live flow: **Stake → PoS/VRF → Create block → Validate + sync**.
10. Wait for block height `1 → 2`.
11. Switch to Bob and show the same block and the transaction in the explorer.
12. Create `evil` on `5005` with **Malicious simulation ON** for the separate malicious-node demonstration.
13. Give Evil a transaction and stake. When Evil wins VRF, it creates two competing blocks.
14. Wait for Alice/Bob to exchange chains. Confirm `EQUIVOCATION DETECTED — BLOCK SLASHED` in Live Activity and `SLASHED — EQUIVOCATION` in the explorer.

## What to explain

- Signalling discovers peers but does not carry blockchain data.
- P2P WebSockets carry transactions, blocks and chain messages.
- PoS uses stake plus a VRF-derived threshold to select a validator.
- A block contains the previous hash, transactions, creator, selected stake and VRF information.
- Peers validate the received block before accepting it.
- The malicious mode deliberately exercises the network's validation/fork handling. The key evidence is that the same validator signed two different blocks at the same position; honest peers verify both signatures and slash the validator.

## Clean shutdown

Use **Stop Selected Node** for browser-created nodes, then stop the signalling/web terminals with `Ctrl+C`.

If orphaned Python processes remain:

```powershell
taskkill /F /IM python.exe
```
