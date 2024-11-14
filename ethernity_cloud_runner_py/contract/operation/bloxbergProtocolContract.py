from decimal import Decimal
from typing import Any
import time
from eth_account.messages import encode_defunct
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.types import TxParams
from web3.middleware import geth_poa_middleware

from ethernity_cloud_runner_py.contract.abi.bloxbergAbi import contract as bloxbergAbi
from ethernity_cloud_runner_py.enums import (
    ECNetworkByChainIdDictionary,
    ECNetworkRPCDictionary,
)


class BloxbergProtocolContract:
    def __init__(self, network_address: Address, signer: Any) -> None:
        self.network_address = network_address
        self.provider = Web3(Web3.HTTPProvider(ECNetworkRPCDictionary[network_address]))
        self.provider.enable_unstable_package_management_api()
        self.provider.middleware_onion.inject(geth_poa_middleware, layer=0)

        self.signer = signer
        self.ethernity_contract = self.provider.eth.contract(  # type: ignore
            address=network_address, abi=bloxbergAbi["abi"]
        )

    def contract_address(self) -> Address:
        # return bloxbergAbi["address"]
        return self.network_address

    @property
    def __transaction_object(self) -> TxParams:
        nonce = self.provider.eth.get_transaction_count(self.signer.address)
        return {
            "gas": 1000000,  # type: ignore
            "chainId": 8995,
            "nonce": nonce,
            "gasPrice": self.provider.to_wei("1", "mwei"),  # type: ignore
        }

    def get_signer(self) -> Any:
        return self.signer

    def get_contract(self) -> Contract:
        return self.ethernity_contract

    def get_provider(self) -> Web3:
        return self.provider

    def get_current_wallet(self) -> Any:
        return self.signer

    def get_balance(self) -> int:
        try:
            address = self.signer.address
            balance = self.ethernity_contract.functions.balanceOf(address).call()
            return Web3.from_wei(balance, "ether")
        except Exception as e:
            print(e)
            return 0

def check_and_set_allowance(
        self, protocol_address: Address, amount: str, task_price: str
    ) -> bool:
        allowance_amount = Web3.to_wei(amount, "ether")
        task_price_amount = Web3.to_wei(task_price, "ether")
        current_wallet_address = self.signer.address
        allowance = self.ethernity_contract.functions.allowance(
            current_wallet_address, protocol_address
        ).call()
        if allowance < task_price_amount:
            tx = self.ethernity_contract.functions.approve(
                protocol_address, allowance_amount
            ).build_transaction(self.__transaction_object)
            signed_tx = self.provider.eth.account.sign_transaction(
                tx, private_key=self.signer._private_key
            )
            self.provider.eth.send_raw_transaction(signed_tx.rawTransaction)
            recept = self.provider.to_hex(self.provider.keccak(signed_tx.rawTransaction))
            try:
                self.provider.eth.wait_for_transaction_receipt(recept)
                allowance = self.ethernity_contract.functions.allowance(
                    current_wallet_address, protocol_address
                ).call()
            except Exception as e:
                print(e)
                return False
        return True

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
        task_price = resources.get("task_price", 10)
        tx = self.ethernity_contract.functions._addDORequest(
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
        ).build_transaction(self.__transaction_object)

        signed_tx = self.provider.eth.account.sign_transaction(
            tx, private_key=self.signer._private_key
        )
        self.provider.eth.send_raw_transaction(signed_tx.rawTransaction)
        return self.provider.to_hex(self.provider.keccak(signed_tx.rawTransaction))

    def get_order(self, order_id: int) -> int:
        return self.ethernity_contract.functions._getOrder(order_id).call()

    def approve_order(self, order_id: int) -> HexStr:
        # return self.ethernity_contract.functions._approveOrder(order_id).transact()
        unicorn_txn = self.ethernity_contract.functions._approveOrder(
            order_id
        ).build_transaction(self.__transaction_object)

        signed_txn = self.provider.eth.account.sign_transaction(
            unicorn_txn, private_key=self.signer._private_key
        )
        self.provider.eth.send_raw_transaction(signed_txn.rawTransaction)
        return self.provider.to_hex(self.provider.keccak(signed_txn.rawTransaction))

    def get_result_from_order(self, order_id: int) -> Any:
        i = 0
        status = self.ethernity_contract.caller()._getOrder(order_id)[4]
        while status == 1:
            print(
                f'{"*" if i % 2 == 0 else "#"} Waiting for transaction to be processed...'
            )
            i += 1
            time.sleep(5)
            status = self.ethernity_contract.caller()._getOrder(order_id)[4]
        return self.ethernity_contract.caller()._getResultFromOrder(order_id)

    def is_node_operator(self, account: str) -> bool:
        try:
            requests = self.ethernity_contract.functions._getMyDPRequests().call(
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
