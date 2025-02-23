from decimal import Decimal
import os
from typing import Any

from eth_account.messages import encode_defunct
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import TxParams

from ..abi.polygonProtocolAbi import contract as polygonAbi
from ..abi.ECLDAbi import contract as ECLDAbi
from ...enums import ECNetwork


class protocolContract:
    def __init__(
        self, signer: Any, network_name="BLOXBERG", network_type="TESTNET"
    ) -> None:
        
        # Access the network class (e.g., ECNetwork.BLOXBERG)
        network_class = getattr(ECNetwork, network_name.upper())
        
        # Access the network type class within the network class (e.g., ECNetwork.BLOXBERG.TESTNET)
        self.network_config = getattr(network_class, network_type.upper())

        self.chain_id = self.network_config.CHAIN_ID
        self.token_address =  self.network_config.TOKEN_ADDRESS
        self.protocol_address = self.network_config.PROTOCOL_ADDRESS
        self.max_fee_per_gas = self.network_config.MAX_FEE_PER_GAS
        self.max_priority_fee_per_gas = self.network_config.MAX_PRIORITY_FEE_PER_GAS
        _rpc_url = self.network_config.RPC_URL
        self.provider = Web3(Web3.HTTPProvider(_rpc_url))

        if self.network_config.MIDDLEWARE == "POA":
            self.provider.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        self.signer = signer
        self.protocol_contract = self.provider.eth.contract(
            address=self.protocol_address, abi=polygonAbi["abi"]
        )
        self.token_contract = self.provider.eth.contract(
            address=self.token_address, abi=ECLDAbi["abi"]
        )

    def get_token_address(self) -> Address:
        return self.token_address

    def get_protocol_address(self) -> Address:
        return self.protocol_address

    def __transaction_object(self, gas) -> TxParams:

        nonce = self.provider.eth.get_transaction_count(self.signer.address)

        if self.network_config.EIP1559 == True:
            latest_block = self.provider.eth.get_block("latest")
            max_fee_per_gas = int(latest_block.baseFeePerGas * 1.1) + self.provider.to_wei(self.network_config.MAX_PRIORITY_FEE_PER_GAS, self.network_config.GAS_PRICE_MEASURE) # 10% increase in previous block gas price + priority fee

            if max_fee_per_gas > self.provider.to_wei(self.network_config.MAX_FEE_PER_GAS, self.network_config.GAS_PRICE_MEASURE):
                raise Exception("Network base fee is too high!")
        
            transaction_options = {
                "type": 2,
                "nonce": nonce,
                "chainId": self.chain_id,
                "from": self.signer.address,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': self.provider.to_wei(self.network_config.MAX_PRIORITY_FEE_PER_GAS, self.network_config.GAS_PRICE_MEASURE),
            }

        else:
            transaction_options = {
                "nonce": nonce,
                "chainId": self.chain_id,
                "from": self.signer.address,
                "gasPrice": self.provider.to_wei(self.network_config.GAS_PRICE, self.network_config.GAS_PRICE_MEASURE),
                "gas": self.network_config.GAS_LIMIT,
            }

        return transaction_options

    def get_signer(self) -> Any:
        return self.signer

    def get_contract(self) -> Contract:
        return self.protocol_contract

    def get_provider(self) -> Web3:
        return self.provider

    def get_current_wallet(self) -> Any:
        return self.signer

    def get_balance(self) -> int:
        try:
            address = self.signer.address
            balance = self.token_contract.functions.balanceOf(address).call()
            return Web3.from_wei(balance, "ether")
        except Exception as e:
            print(e)
            return 0

    def set_allowance(
        self, task_price: int
    ) -> bool:
        task_price_amount = Web3.to_wei(task_price, "ether")
        try:
            tx = self.token_contract.functions.approve(
                self.protocol_address, task_price_amount
            ).build_transaction(self.__transaction_object(100000))

            signed_tx = self.provider.eth.account.sign_transaction(
                tx, private_key=self.signer._private_key
            )

            self.provider.eth.send_raw_transaction(signed_tx.raw_transaction)

            return self.provider.to_hex(self.provider.keccak(signed_tx.raw_transaction))
        except Exception as e:
            raise Exception(f"Unable to set allowance: {e}")
        
        return True

    def get_eip1559_gas_options(self) -> dict[str, int]:
        max_fee_per_gas = int(os.getenv("MAX_FEE_PER_GAS", 0)) * 10**9
        max_priority_fee_per_gas = int(os.getenv("MAX_PRIORITY_FEE_PER_GAS", 0)) * 10**9
        options = {
            "gas_limit": int(os.getenv("GAS_LIMIT", 200000)),
            "max_fee_per_gas": max_fee_per_gas,
            "max_priority_fee_per_gas": max_priority_fee_per_gas,
        }
        return options

    def add_do_request(
        self,
        image_metadata: str,
        payload_metadata: str,
        input_metadata: str,
        node_address: Address,
        resources: dict,
        gas_limit: None = None,
    ) -> HexStr:

        cpu = resources.get("cpu", 1)
        memory = resources.get("memory", 1)
        storage = resources.get("storage", 40)
        bandwidth = resources.get("bandwidth", 1)
        duration = resources.get("duration", 1)
        validators = resources.get("validators", 1)
        task_price = resources.get("taskPrice", 10)

        tx = self.protocol_contract.functions._addDORequest(
            cpu,
            memory,
            storage,
            bandwidth,
            duration,
            validators,
            task_price,
            image_metadata,
            payload_metadata,
            input_metadata,
            node_address,
        ).build_transaction(self.__transaction_object(1000000))

        signed_tx = self.provider.eth.account.sign_transaction(
            tx, private_key=self.signer._private_key
        )

        self.provider.eth.send_raw_transaction(signed_tx.raw_transaction)
        return self.provider.to_hex(self.provider.keccak(signed_tx.raw_transaction))

    def get_order(self, order_id: int) -> int:
        return self.protocol_contract.functions._getOrder(order_id).call()

    def approve_order(self, order_id: int) -> HexStr:
        # return self.protocol_contract.functions._approveOrder(order_id).transact()
        unicorn_txn = self.protocol_contract.functions._approveOrder(
            order_id
        ).build_transaction(self.__transaction_object(100000))

        signed_txn = self.provider.eth.account.sign_transaction(
            unicorn_txn, private_key=self.signer._private_key
        )
        self.provider.eth.send_raw_transaction(signed_txn.raw_transaction)
        return self.provider.to_hex(self.provider.keccak(signed_txn.raw_transaction))

    def get_result_from_order(self, order_id: int) -> Any:
        self.protocol_contract.caller()._getOrder(order_id)
        return self.protocol_contract.caller()._getResultFromOrder(order_id)

    def get_status_from_order(self, order_id: int) -> Any:
        return self.protocol_contract.caller()._getOrder(order_id)[4]

    def is_node_operator(self, account: str) -> bool:
        try:
            requests = self.protocol_contract.functions._getMyDPRequests().call(
                {"from": account}
            )
            return len(requests) > 0
        except Exception as ex:
            print(ex)
            return False

    def sign_message(self, message: str) -> Any:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        return self.provider.eth.account.sign_message(
            encode_defunct(text=message), self.signer._private_key
        )