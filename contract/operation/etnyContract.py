from web3 import Web3
from enums import ECNetworkByChainIdDictionary
from contract.abi.etnyAbi import contract
from eth_account.messages import encode_defunct


class EtnyContract:
    def __init__(self, network_address):
        self.provider = Web3(Web3.HTTPProvider(network_address))
        self.signer = self.provider.eth.default_account
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

    def get_signer(self):
        return self.signer

    def get_contract(self):
        return self.etny_contract

    def get_provider(self):
        return self.provider

    def get_current_wallet(self):
        return self.current_wallet

    def _get_current_wallet(self):
        try:
            accounts = self.provider.eth.accounts
            return accounts[0]
        except Exception as e:
            print(e)
            return None

    def get_balance(self):
        try:
            address = self.signer
            balance = self.etny_contract.functions.balanceOf(address).call()
            return Web3.from_wei(balance, "ether")
        except Exception as e:
            print(e)
            return 0

    def get_network_name(self):
        network = self.provider.eth.chain_id
        return ECNetworkByChainIdDictionary[network]

    def sign_message(self, message):
        return self.provider.eth.account.sign_message(encode_defunct(text=message))
