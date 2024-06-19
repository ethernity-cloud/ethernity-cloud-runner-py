from web3 import Web3
from contract.abi.polygonProtocolAbi import contract
from eth_account.messages import encode_defunct
import os


class PolygonProtocolContract:
    def __init__(self, network_address):
        self.network_address = network_address
        self.provider = Web3(Web3.HTTPProvider(network_address))
        self.signer = self.provider.eth.default_account
        self.protocol_contract = self.provider.eth.contract(
            address=network_address, abi=contract["abi"]
        )
        self.protocol_contract_with_provider = self.provider.eth.contract(
            address=network_address, abi=contract["abi"]
        )

    def contract_address(self):
        return self.network_address

    def get_signer(self):
        return self.signer

    def get_contract(self):
        return self.protocol_contract

    def get_provider(self):
        return self.provider

    def get_eip1559_gas_options(self):
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
        image_metadata,
        payload_metadata,
        input_metadata,
        node_address,
        resources,
        gas_limit=None,
    ):
        cpu = resources.get("cpu", 1)
        memory = resources.get("memory", 1)
        storage = resources.get("storage", 40)
        bandwidth = resources.get("bandwidth", 1)
        duration = resources.get("duration", 1)
        validators = resources.get("validators", 1)
        task_price = resources.get("task_price", 10)
        if gas_limit:
            return self.protocol_contract.functions._addDORequest(
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
            ).transact({"gas": gas_limit})
        return self.protocol_contract.functions._addDORequest(
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
        )

    def get_order(self, order_id):
        return self.protocol_contract.functions._getOrder(order_id).call()

    def approve_order(self, order_id):
        return self.protocol_contract.functions._approveOrder(order_id).transact()

    def get_result_from_order(self, order_id):
        return self.protocol_contract.functions._getResultFromOrder(order_id).call()

    def get_faucet_tokens(self, account):
        return self.protocol_contract.functions.faucet().transact({"from": account})

    def is_node_operator(self, account):
        try:
            requests = self.protocol_contract_with_provider.functions._getMyDPRequests(
                {"from": account}
            ).call()
            return len(requests) > 0
        except Exception as ex:
            print(ex)
            return False

    def sign_message(self, message):
        return self.provider.eth.account.sign_message(encode_defunct(text=message))
