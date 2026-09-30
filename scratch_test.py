import requests
import time

BASE_URL = "http://127.0.0.1:8000/api"

def create_node(name, port, malicious=False, staker=True):
    data = {
        "name": name,
        "p2p_port": port,
        "room_id": "testroom3",
        "consensus": "pos",
        "malicious": malicious,
        "staker": staker
    }
    r = requests.post(f"{BASE_URL}/nodes", json=data)
    r.raise_for_status()
    return r.json()["node"]["id"]

def stake(node_id, amount):
    requests.post(f"{BASE_URL}/nodes/{node_id}/stake", json={"amount": amount})

def send_tx(node_id, receiver, amount):
    requests.post(f"{BASE_URL}/nodes/{node_id}/transaction", json={"receiver": receiver, "amount": amount})

def get_state(node_id):
    return requests.get(f"{BASE_URL}/state", params={"node_id": node_id}).json()

print("Creating honest node...")
node1 = create_node("honest_alpha", 5020)

print("Creating malicious node...")
node_mal = create_node("malicious_beta", 5021, malicious=True)

time.sleep(10) # Wait for discovery

print("Giving mal transaction...")
send_tx(node1, "malicious_beta", 100) # Give mal some balance to stake

time.sleep(5)

print("Staking on malicious node to trigger attack...")
stake(node_mal, 50)
send_tx(node_mal, "honest_alpha", 10) # mal sends something

time.sleep(15) # wait for blocks

state_1 = get_state(node1)
state_mal = get_state(node_mal)

print("Honest node 1 activities:")
slashed_found = False
for act in state_1.get("activity", []):
    print(act["time"], act["level"], act["message"], act.get("detail", ""))
    if "SLASHED" in act["message"]:
        slashed_found = True

print("Malicious node activities:")
for act in state_mal.get("activity", []):
    print(act["time"], act["level"], act["message"], act.get("detail", ""))

if slashed_found:
    print("SUCCESS: Web malicious node is working and was blocked by the honest node.")
else:
    print("FAILURE: Web malicious node did not cause a slashing event.")
