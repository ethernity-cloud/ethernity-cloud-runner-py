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
from ...enums import ECNetworkByChainIdDictionary, ECNetworkRPCDictionary


class PolygonProtocolContract:
    def __init__(
        self, token_address: Address, protocol_address: Address, signer: Any, chain_id: int = 8559
    ) -> None:
        self.chain_id = chain_id
        self.token_address = token_address
        self.protocol_address = protocol_address
        self.max_fee_per_gas = 200
        self.max_priority_fee_per_gas = 35
        _rpc_url = ECNetworkRPCDictionary[token_address]
        self.provider = Web3(Web3.HTTPProvider(_rpc_url))

        self.provider.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        self.signer = signer
        self.protocol_contract = self.provider.eth.contract(
            address=protocol_address, abi=polygonAbi["abi"]
        )
        self.token_contract = self.provider.eth.contract(
            address=token_address, abi=ECLDAbi["abi"]
        )

    def get_token_address(self) -> Address:
        return self.token_address

    def get_protocol_address(self) -> Address:
        return self.protocol_address

    def __transaction_object(self, gas) -> TxParams:
        nonce = self.provider.eth.get_transaction_count(self.signer.address)
        max_fee_per_gas = self.provider.to_wei(self.max_fee_per_gas, 'gwei')
        max_priority_fee_per_gas = self.provider.to_wei(self.max_priority_fee_per_gas, 'gwei')

        return {
            "from": self.signer.address,
            "chainId": self.chain_id,
            "nonce": nonce,
            "gas": gas,
            "maxFeePerGas" : max_fee_per_gas,
            "maxPriorityFeePerGas": max_priority_fee_per_gas,
        }

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

    def check_and_set_allowance(
        self, task_price: str
    ) -> bool:
        task_price_amount = Web3.to_wei(task_price, "ether")
        current_wallet_address = self.signer.address
        allowance = self.token_contract.functions.allowance(
            current_wallet_address, self.protocol_address
        ).call()
        if allowance < task_price_amount:
            try:
                tx = self.token_contract.functions.approve(
                    self.protocol_address, int(task_price_amount)
                ).build_transaction(self.__transaction_object(100000))

                signed_tx = self.provider.eth.account.sign_transaction(
                    tx, private_key=self.signer._private_key
                )

                self.provider.eth.send_raw_transaction(signed_tx.raw_transaction)

                receipt = self.provider.to_hex(
                    self.provider.keccak(signed_tx.raw_transaction)
                )

                self.provider.eth.wait_for_transaction_receipt(receipt)

                allowance = self.protocol_contract.functions.allowance(
                    current_wallet_address, self.protocol_address
                ).call()
            except Exception as e:
                return False
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

    def get_network_name(self) -> Any:
        network = self.provider.eth.chain_id
        return ECNetworkByChainIdDictionary[network]
