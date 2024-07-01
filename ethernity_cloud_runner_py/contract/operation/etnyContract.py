from web3 import Web3
from ...enums import ECNetworkByChainIdDictionary
from ...contract.abi.etnyAbi import contract
from eth_account.messages import encode_defunct
from web3.middleware.geth_poa import geth_poa_middleware
from typing import Any


class EtnyContract:
    def __init__(self, network_address, signer) -> None:
        self.provider = Web3(Web3.HTTPProvider("https://core.bloxberg.org"))
        self.provider.enable_unstable_package_management_api()
        self.provider.middleware_onion.inject(geth_poa_middleware, layer=0)
        self.signer = signer
        self.etny_contract = self.provider.eth.contract(
            address=network_address, abi=contract["abi"]
        )
        self.etny_contract_with_provider = self.provider.eth.contract(
            address=network_address, abi=contract["abi"]
        )

    def initialize(self):
        self.current_wallet = self.get_current_wallet()

    def contract_address(self):
        return contract["address"]

    def getOrder(self, orderId: int) -> Any:
        return self.etny_contract.functions.getOrder(orderId).call()

    def get_signer(self):
        return self.signer

    def get_contract(self):
        return self.etny_contract

    def get_provider(self):
        return self.provider

    def get_current_wallet(self):
        # return self.current_wallet
        return self.signer

    def _get_current_wallet(self):
        try:
            accounts = self.provider.eth.accounts
            return accounts[0]
        except Exception as e:
            print(e)
            return None

    def get_balance(self):
        try:
            address = self.signer.address
            balance = self.etny_contract.functions.balanceOf(address).call()
            return Web3.from_wei(balance, "ether")
        except Exception as e:
            print(e)
            return 0

    def get_network_name(self):
        network = self.provider.eth.chain_id
        return ECNetworkByChainIdDictionary[network]

    def sign_message(self, message):
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        return self.provider.eth.account.sign_message(
            encode_defunct(text=message), self.signer._private_key
        )
