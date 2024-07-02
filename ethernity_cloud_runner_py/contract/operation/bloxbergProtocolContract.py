from typing import Any

from eth_account.messages import encode_defunct
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.middleware.geth_poa import geth_poa_middleware
from web3.types import TxParams

from ..abi.bloxbergAbi import contract as bloxbergAbi


class BloxbergProtocolContract:
    def __init__(self, network_address: Address, signer: Any) -> None:
        self.network_address = network_address
        self.provider = Web3(Web3.HTTPProvider("https://bloxberg.ethernity.cloud"))
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
            "gas": 10000000,  # type: ignore
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

    def add_do_request(
        self,
        image_metadata: str,
        payload_metadata: str,
        input_metadata: str,
        node_address: Address,
        resources: dict,
        gas_limit: int | None = None,
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
        self.ethernity_contract.caller()._getOrder(order_id)
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
        return self.provider.eth.account.sign_message(
            encode_defunct(text=message), self.signer._private_key
        )
