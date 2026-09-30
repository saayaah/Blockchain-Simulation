import json, hashlib, uuid, base64
from typing import List,Dict
from datetime import datetime, timedelta
from ecdsa import SigningKey, SECP256k1, VerifyingKey, BadSignatureError
from shared_blockchain_structures import (
    Transaction,
    BaseBlock,
    CommonChain,
    Wallet,
    txs_to_json_digestable_form,
    valid_chain_length,
    transaction_exists_in_block_list
)
GAS_PRICE = 0.001 # coin per gas unit
MAX_OUTPUT=2**256

class Stake:
    def __init__(self, staker:str, amt:int, ts=None):
        self.id=str(uuid.uuid4())
        self.staker=staker
        self.amt=amt
        self.sign:bytes=None

        self.ts=ts or datetime.now().timestamp()

    def to_dict(self):
        return {
            "id":self.id,
            "staker":self.staker,
            "amt":self.amt,
            "ts":self.ts
        }

    def __str__(self):
        return json.dumps(self.to_dict())
    
class Block(BaseBlock):
    def __init__(self, prevHash:str, transactions:List[Transaction], ts=None, id=None):
        super().__init__(prevHash, transactions, ts, id)

        self.creator: str=""
        self.staked_amt=0
        
        self.stakers:List[Stake]=[]  # needs to be replaced everywhere with stakes
        self.seed:str=""
        self.vrf_proof:bytes=None
        self.sign: bytes=None
        self.is_valid:bool=True
        self.slash_creator=False

    def to_dict(self):
        return {
            "id":self.id,
            "prevHash":self.prevHash,
            "transactions":txs_to_json_digestable_form(self.transactions),
            "ts":self.ts,
            "creator":self.creator,
            "staked_amt":self.staked_amt,
            "files":self.files
        }
    
    def to_dict_with_stakers(self):
        block_dict=self.to_dict()
        
        stakes_dict_list:List[Dict]=[]
        for stake in self.stakers:
            stake_dict=stake.to_dict()
            if(stake.sign):
                stake_dict["sign"]=base64.b64encode(stake.sign).decode()
            stakes_dict_list.append(stake_dict)

        block_dict["stakers"]=stakes_dict_list
        if(self.vrf_proof and self.seed):
            block_dict["vrf_proof_b64"]=base64.b64encode(self.vrf_proof).decode()
            block_dict["seed"]=self.seed
        return block_dict


    def __str__(self):
        return json.dumps(self.to_dict())
    
    def is_equal(self, other):
        same = True

        if len(self.transactions) != len(other.transactions):
            return False

        tx_len = len(self.transactions)
        for i in range(tx_len):
            if self.transactions[i] != other.transactions[i]:
                return False

        return (
            self.id == other.id and
            self.ts == other.ts and
            self.prevHash == other.prevHash and
            self.hash == other.hash and
            self.sign == other.sign and
            self.creator == other.creator
        )

    @property ## Now you can access hash like this myblock.hash
    def hash(self):
        block_str=json.dumps(self.to_dict())
        return hashlib.sha256(block_str.encode()).hexdigest()


def calc_balance_block_list(block_list:List[Block], publicKey, i, mem_pool:List[Transaction]=None, currStakes:List[Stake]=None):
    bal=0
    valid_chain_len=valid_chain_length(i)

    for i in range(valid_chain_len):
        if block_list[i].slash_creator and block_list[i].creator==publicKey:
            bal-=block_list[i].staked_amt
        if not block_list[i].is_valid:
            continue
        
        for transaction in (block_list[i]).transactions:
            if transaction.sender==publicKey:
                if transaction.receiver == "deploy" or transaction.receiver == "invoke":
                    bal-=transaction.payload[-1]
                else:
                    bal-=transaction.payload
            elif transaction.receiver==publicKey:
                bal+=transaction.payload
        if block_list[i].creator==publicKey:
            bal+=6 #Miner reward
    
    for transaction in mem_pool:
        if transaction.sender==publicKey:
            if transaction.receiver == "deploy" or transaction.receiver == "invoke":
                bal-=transaction.payload[-1]
            else:
                bal-=transaction.payload

    if currStakes:
        for stake in currStakes:
            if stake.staker==publicKey:
                bal-=stake.amt
    # Since these transactions are not part of the chain we don't add
    # the money they gained yet because it could be invalid, but we subtract
    # the amount they have given to prevent double spending before the
    # transactions are added to the chain
    return bal

def weight_of_chain(block_list:List[Block]):
    total_weight=0
    for block in block_list:
        for stake in block.stakers:
            total_weight+=stake.amt
    return total_weight

class Chain(CommonChain):
    instance = None #Class Variable

    def __init__(self, publicKey:str=None, privatekey=None, blockList: List[Block]=None):
        """
            If we are the first node, we mine the genesis block for ouself
            otherwise we receive blockList from the bootstrap node and
            we assign that to be the chain
        """
        if Chain.instance is not None:
            return

        if publicKey and not blockList:
            genesis_block=Block(None, [Transaction(50,"Genesis",publicKey)])
            genesis_block.creator=publicKey
            genesis_block.sign=privatekey.sign(str(genesis_block).encode())
            super().__init__(genesis_block=genesis_block)
                
        elif blockList and not publicKey:
            super().__init__(block_list=blockList)

        else:
            raise ValueError("Invalid arguments")

        Chain.instance = self


    def to_block_dict_list(self):
        block_dict_list=[]
        for block in self.chain:
            block_dict=block.to_dict_with_stakers()
            if block.sign:
                block_dict["sign"]=base64.b64encode(block.sign).decode()
                
            block_dict_list.append(block_dict)
        
        return block_dict_list
    
    def rewrite(self, blockList:List[Block]):
        # The incoming chain must be valid before it can replace
        # the current mission chain, even if its stake weight is higher.
        if weight_of_chain(self.chain) >= weight_of_chain(blockList):
            return

        if not isvalidChain(blockList):
            print("\nRejected invalid blockchain received from network\n")
            return

        Chain.instance.chain = blockList.copy()   
    
    def isValidBlock(self, block: Block, expected_stakers: Dict[str, int]=None):
        """Validate a PoS block, including its validator stake and VRF proof.

        The validator must be one of the stakes committed in the block and
        ``staked_amt`` must exactly match that validator's stake.  This prevents
        a node from claiming a larger effective stake than it actually locked.
        """
        if block is None or self.lastBlock.hash != block.prevHash:
            return False

        # A block must carry a complete, self-consistent stake snapshot.
        if not block.creator or not block.stakers or block.staked_amt <= 0:
            return False

        stake_by_key = {}
        total_stake = 0
        for stake in block.stakers:
            if not stake.staker or stake.staker in stake_by_key:
                return False
            if not isinstance(stake.amt, (int, float)) or stake.amt <= 0 or not stake.sign:
                return False
            try:
                vk = VerifyingKey.from_pem(stake.staker)
                vk.verify(stake.sign, str(stake).encode())
            except (BadSignatureError, ValueError, TypeError):
                return False
            stake_by_key[stake.staker] = stake
            total_stake += stake.amt

        creator_stake = stake_by_key.get(block.creator)
        if creator_stake is None or block.staked_amt != creator_stake.amt:
            return False
        if total_stake <= 0 or block.staked_amt > total_stake:
            return False

        # When a live node validates a freshly broadcast block, compare the
        # committed snapshot with the stake announcements it observed for the
        # current epoch. This prevents a validator from silently omitting
        # competing stakes to turn a low-probability lottery into a guaranteed
        # win. Historical chain validation remains self-contained.
        if expected_stakers is not None:
            normalized = {key: stake.amt for key, stake in stake_by_key.items()}
            if normalized != {key: int(value) for key, value in expected_stakers.items()}:
                return False

        # The VRF proof is a signature over the deterministic epoch seed.
        if not block.vrf_proof or block.seed != self.epoch_seed():
            return False
        try:
            creator_vk = VerifyingKey.from_pem(block.creator)
            creator_vk.verify(block.vrf_proof, block.seed.encode())
        except (BadSignatureError, ValueError, TypeError):
            return False

        vrf_output = int(hashlib.sha256(block.vrf_proof).hexdigest(), 16)
        threshold = (block.staked_amt / total_stake) * MAX_OUTPUT
        # Winner condition is strictly less than the threshold, as specified
        # by the PoS protocol.
        if(vrf_output>=threshold):
            return False

        mem_pool = []
        for transaction in block.transactions:
            if transaction_exists_in_block_list(self.chain, transaction, len(self.chain)):
                return False
            try:
                vk_tx = VerifyingKey.from_pem(transaction.sender)
                vk_tx.verify(transaction.sign, str(transaction).encode())
            except (BadSignatureError, ValueError, TypeError):
                return False

            amount = transaction.payload[-1] if transaction.receiver in ("deploy", "invoke") else transaction.payload
            if amount <= 0 or amount > self.calc_balance(transaction.sender, mem_pool, block.stakers):
                return False
            mem_pool.append(transaction)

        # Stakes are also balance locks. Process them sequentially so the same
        # account cannot stake the same coins twice in one block.
        current_stakes = []
        for stake in block.stakers:
            if stake.amt > self.calc_balance(stake.staker, mem_pool, current_stakes):
                return False
            current_stakes.append(stake)

        return True

    def calc_balance(self, publicKey, pending_transactions:List[Transaction]=None, current_stakes:List[Stake]=None):
        bal=0
        valid_chain_len=valid_chain_length(len(self.chain))

        for i in range(valid_chain_len):
            if Chain.instance.chain[i].slash_creator and Chain.instance.chain[i].creator==publicKey:
                bal-=Chain.instance.chain[i].staked_amt
            if not Chain.instance.chain[i].is_valid:
                continue
            
            for transaction in (Chain.instance.chain[i]).transactions:
                if transaction.sender==publicKey:
                    if transaction.receiver == "deploy" or transaction.receiver == "invoke":
                        bal-=transaction.payload[-1]
                    else:
                        bal-=transaction.payload
                elif transaction.receiver==publicKey:
                    bal+=transaction.payload
            if Chain.instance.chain[i].creator==publicKey:
                bal+=6 #Miner reward

        if valid_chain_len<len(self.chain):
            for i in range(valid_chain_len, len(self.chain)):
                currBlock=Chain.instance.chain[i]
                for transaction in currBlock.transactions:
                    if transaction.sender==publicKey:
                        if transaction.receiver == "deploy" or transaction.receiver == "invoke":
                            bal-=transaction.payload[-1]
                        else:
                            bal-=transaction.payload
        
        if current_stakes:
            for stake in current_stakes:
                if stake.staker==publicKey:
                    bal-=stake.amt

        # Since these transactions are not part of the chain we don't add
        # the money they gained yet because it could be invalid, but we subtract
        # the amount they have given to prevent double spending before the
        # transactions are added to the chain
        if pending_transactions:
            for transaction in pending_transactions:
                if transaction.sender==publicKey:
                    if transaction.receiver == "deploy" or transaction.receiver == "invoke":
                        bal-=transaction.payload[-1]
                    else:
                        bal-=transaction.payload
        return bal

    def epoch_seed(self):
        bal=0
        last_finalized_block_hash=self.chain[valid_chain_length(len(self.chain))-1].hash
        return last_finalized_block_hash

    def checkEquivalence(self, block_list:List[Block]):
        """
            Returns -1 if there is no divergence, returns index of divergence if there is any
        """
        min_len=min(len(self.chain), len(block_list))
        for i in range(min_len):
            if(not self.chain[i].is_equal(block_list[i])):
                return i
        return -1

def transaction_exists_in_block_list(blockList:List[Block], transaction_tc:Transaction, idx):
    for i in range(idx):
        currBlock = blockList[i]
        for transaction in currBlock.transactions:
            if transaction.id == transaction_tc.id:
                return True
    return False

def isvalidChain(blockList:List[Block]):
    EPOCH_TIME = 60  # Add this constant or pass it as a parameter
    
    for i in range(len(blockList)):
        currBlock=blockList[i]
        vk=VerifyingKey.from_pem(currBlock.creator)
        try:
            vk.verify(currBlock.sign, str(currBlock).encode())
        except BadSignatureError:
            return False
        
        if(i<=0):
            continue

        # Timestamp validation
        try:
            # Convert Unix timestamp to datetime
            if isinstance(currBlock.ts, (int, float)):
                block_time = datetime.fromtimestamp(currBlock.ts/1000)
            elif isinstance(currBlock.ts, str):
                block_time = datetime.fromisoformat(currBlock.ts)
            elif isinstance(currBlock.ts, datetime):
                block_time = currBlock.ts
            else:
                print("\nInvalid Block timestamp format\n")
                return False

            # Get previous block time
            prev_block_ts = blockList[i-1].ts
            if isinstance(prev_block_ts, (int, float)):
                prev_block_time = datetime.fromtimestamp(prev_block_ts/1000)
            elif isinstance(prev_block_ts, str):
                prev_block_time = datetime.fromisoformat(prev_block_ts)
            elif isinstance(prev_block_ts, datetime):
                prev_block_time = prev_block_ts
            else:
                print("\nInvalid previous block timestamp format\n")
                return False

            # Check block isn't from the future (allow some tolerance for clock skew)
            current_time = datetime.now()
            if block_time > current_time + timedelta(seconds=10):
                print(f"\nBlock {i} timestamp in future\n")
                return False

            # Check blocks are in chronological order
            if block_time < prev_block_time:
                print(f"\nBlock {i} timestamp before previous block\n")
                return False

            # Historical chains may contain blocks created in quick succession
            # during simulation. Live block-creation timing is enforced by the
            # consensus scheduler; chain replay must not reject an otherwise
            # valid received chain solely because timestamps are close.
        except (ValueError, AttributeError, TypeError, OSError) as e:
            print(f"\nTimestamp validation error on block {i}: {e}\n")
            return False

        try:
            vk.verify(currBlock.vrf_proof, currBlock.seed.encode())
        except BadSignatureError:
            print("\nInvalid signature on vrf_proof\n")
            return False
        
        if(str(currBlock.seed)!=str(blockList[valid_chain_length(i)-1].hash)):
            print("\nInvalid Seed\n")
            return False

        total_stake=0
        stake_by_key={}
        for stake in currBlock.stakers:
            if not stake.staker or stake.staker in stake_by_key:
                return False
            if stake.amt<=0 or not stake.sign:
                return False
            try:
                vk=VerifyingKey.from_pem(stake.staker)
                vk.verify(stake.sign, str(stake).encode())
            except (BadSignatureError, ValueError, TypeError):
                return False
            stake_by_key[stake.staker]=stake
            total_stake+=stake.amt

        if total_stake<=0:
            return False

        # Critical PoS invariant: the block creator must actually own the
        # selected stake, and staked_amt cannot be forged independently.
        creator_stake=stake_by_key.get(currBlock.creator)
        if creator_stake is None or currBlock.staked_amt != creator_stake.amt:
            return False
        if currBlock.staked_amt<=0 or currBlock.staked_amt>total_stake:
            return False

        if not currBlock.vrf_proof or currBlock.seed != blockList[valid_chain_length(i)-1].hash:
            return False
        try:
            creator_vk=VerifyingKey.from_pem(currBlock.creator)
            creator_vk.verify(currBlock.vrf_proof, currBlock.seed.encode())
        except (BadSignatureError, ValueError, TypeError):
            return False

        vrf_output_int=int(hashlib.sha256(currBlock.vrf_proof).hexdigest(), 16)
        threshold=(currBlock.staked_amt/total_stake)*MAX_OUTPUT
        if vrf_output_int>=threshold:
            return False

        mem_pool=[]
        for transaction in blockList[i].transactions:
            if(transaction_exists_in_block_list(blockList, transaction, i)):
                print("Duplicate transaction(s)")
                return False
            
            sign=transaction.sign
            vk_tx=VerifyingKey.from_pem(transaction.sender)

            try:
                vk_tx.verify(sign, str(transaction).encode())
            except BadSignatureError:
                print("\nInvalid signature on transaction\n")
                return False

            amount = 0
            if(transaction.receiver == "deploy" or transaction.receiver == "invoke"):
                amount = transaction.payload[-1]
            else:
                amount = transaction.payload
            if(calc_balance_block_list(blockList, transaction.sender, i, mem_pool, currBlock.stakers) < amount or amount<=0):
                return False
            mem_pool.append(transaction)
        
        # we use a currStakes list because if we just pass currBlock.stakers then the stake 
        # which we are processing will already be there
        currStakes=[]
        for stake in currBlock.stakers:
            if stake.amt>calc_balance_block_list(blockList, stake.staker, i, mem_pool, currStakes):
                return False
            currStakes.append(stake)

        
        if(calc_balance_block_list(blockList, blockList[i].creator, i, mem_pool)<0):
            return False
        
        if (blockList[i].prevHash!=blockList[i-1].hash):
            return False

    return True

