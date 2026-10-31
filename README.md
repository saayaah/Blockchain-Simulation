\# Blockchain Consensus \& Security Simulation



\## Problem Statement



This project is a blockchain simulation that demonstrates how different consensus mechanisms work and how they handle malicious activity.



The system supports:



\* Proof of Work (PoW)

\* Proof of Stake (PoS)

\* Proof of Authority (PoA)

\* Peer-to-peer communication

\* Blockchain validation

\* Malicious node simulation

\* Equivocation detection

\* Transaction and block verification



The goal is to test how the blockchain network behaves during normal operations as well as during attacks such as invalid blocks, double spending, and conflicting transactions.



\## Improvements Made



We improved the project by:



\* Fixing runtime and dependency issues

\* Improving PoW, PoS, and PoA consensus logic

\* Improving block and transaction validation

\* Adding malicious node simulation

\* Adding equivocation detection

\* Improving peer-to-peer communication using WebSockets

\* Improving blockchain synchronization between nodes

\* Adding a signalling server for peer discovery

\* Improving the Flask web dashboard

\* Adding project verification checks

\* Adding automated tests for PoS and malicious activity

\* Improving stability and error handling



\## How to Run



\### 1. Install Dependencies



Install the required Python packages:



```bash

pip install -r requirements.txt

```



\### 2. Verify the Project



```bash

python verify\_project.py

```



\### 3. Start the Signalling Server



```bash

python signalling\_server.py

```



The signalling server runs on port `8765`.



\### 4. Start the Web Interface



Open another terminal and run:



```bash

python web\_interface.py --host 127.0.0.1 --port 8000

```



Open:



```text

http://127.0.0.1:8000

```



in your browser.



\### 5. Start a Blockchain Peer



Open another terminal and run:



```bash

python start\_peer.py

```



Follow the terminal prompts and select the consensus mechanism:



```text

pow

pos

poa

```



You can start multiple peers in separate terminals.



\## Run Tests



\### Proof of Stake Tests



```bash

python tests\_pos.py

```



\### Malicious Node Tests



```bash

python tests\_malicious.py

```



\## Tech Stack



\* Python

\* Flask

\* WebSockets

\* asyncio

\* ECDSA

\* Cryptography

\* HTML

\* CSS

\* JavaScript

Hackathon Project Team
1.Saya lakshmi
2.Midhun Raj
3.Akash R
4.Adhil Salah



