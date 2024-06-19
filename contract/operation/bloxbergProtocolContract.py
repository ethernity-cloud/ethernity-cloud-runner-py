from web3 import Web3
from contract.abi.etnyAbi import contract as etny_contract_abi
from eth_account.messages import encode_defunct


class BloxbergProtocolContract:
    def __init__(self, network_address):
        self.provider = Web3(Web3.HTTPProvider(network_address))
        self.signer = self.provider.eth.default_account
        self.etny_contract = self.provider.eth.contract(
            address=network_address, abi=etny_contract_abi["abi"]
        )
        self.etny_contract_with_provider = self.provider.eth.contract(
            address=network_address, abi=etny_contract_abi["abi"]
        )

    def contract_address(self):
        return etny_contract_abi["address"]

    def get_signer(self):
        return self.signer

    def get_contract(self):
        return self.etny_contract

    def get_provider(self):
        return self.provider

    def add_do_request(
        self, image_metadata, payload_metadata, input_metadata, node_address, resources
    ):
        cpu = resources.get("cpu", 1)
        memory = resources.get("memory", 1)
        storage = resources.get("storage", 40)
        bandwidth = resources.get("bandwidth", 1)
        duration = resources.get("duration", 1)
        validators = resources.get("validators", 1)
        task_price = resources.get("task_price", 10)
        return self.etny_contract.functions._addDORequest(
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
        ).transact()

    def get_order(self, order_id):
        return self.etny_contract.functions._getOrder(order_id).call()

    def approve_order(self, order_id):
        return self.etny_contract.functions._approveOrder(order_id).transact()

    def get_result_from_order(self, order_id):
        return self.etny_contract.functions._getResultFromOrder(order_id).call()

    def is_node_operator(self, account):
        try:
            requests = (
                self.etny_contract_with_provider.functions._getMyDPRequests().call(
                    {"from": account}
                )
            )
            return len(requests) > 0
        except Exception as ex:
            print(ex)
            return False

    def sign_message(self, message):
        return self.provider.eth.account.sign_message(encode_defunct(text=message))
