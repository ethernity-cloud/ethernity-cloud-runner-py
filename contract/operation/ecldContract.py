from web3 import Web3
from enums import ECNetworkByChainIdDictionary
from contract.abi.ecldAbi import contract
from eth_account.messages import encode_defunct


class EcldContract:
    def __init__(self, network_address):
        self.provider = Web3(Web3.HTTPProvider(network_address))
        self.signer = self.provider.eth.default_account
        self.ecld_contract = self.provider.eth.contract(
            address=network_address, abi=contract["abi"]
        )
        self.ecld_contract_with_provider = self.provider.eth.contract(
            address=network_address, abi=contract["abi"]
        )
        self.current_wallet = None

    def initialize(self):
        self.current_wallet = self.get_current_wallet()

    def contract_address(self):
        return contract["address"]

    def get_signer(self):
        return self.signer

    def get_contract(self):
        return self.ecld_contract

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

    def get_network_name(self):
        network = self.provider.eth.chain_id
        return ECNetworkByChainIdDictionary[network]

    def check_and_set_allowance(self, protocol_address, amount, task_price):
        allowance_amount = Web3.to_wei(amount, "ether")
        task_price_amount = Web3.to_wei(task_price, "ether")
        current_wallet_address = self.signer
        allowance = self.ecld_contract.functions.allowance(
            current_wallet_address, protocol_address
        ).call()
        if allowance < task_price_amount:
            approve_tx = self.ecld_contract.functions.approve(
                protocol_address, allowance_amount
            ).transact()
            try:
                self.provider.eth.wait_for_transaction_receipt(approve_tx)
                allowance = self.ecld_contract.functions.allowance(
                    current_wallet_address, protocol_address
                ).call()
            except Exception as e:
                print(e)
                return False
        return True

    def approve(self, tokens):
        allowance_amount = Web3.to_wei(tokens, "ether")
        address = self.signer
        return self.ecld_contract.functions.approve(
            address, allowance_amount
        ).transact()

    def get_balance(self):
        try:
            address = self.signer
            balance = self.ecld_contract.functions.balanceOf(address).call()
            return Web3.from_wei(balance, "ether")
        except Exception as e:
            print(e)
            return 0

    def sign_message(self, message):
        return self.provider.eth.account.sign_message(encode_defunct(text=message))
