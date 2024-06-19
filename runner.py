import time
from web3 import Web3
from ipfs import IPFSClient
from utils import generate_random_hex_of_size, format_date, is_address, is_null_or_empty
from crypto import encrypt_with_certificate, decrypt_with_private_key, sha256
from enums import (
    ECEvent,
    ECStatus,
    ECOrderTaskStatus,
    ZERO_CHECKSUM,
    ECAddress,
    ECError,
    ECNetworkName,
    ECNetworkNameDictionary,
    ECNetworkName1Dictionary,
)
from contract.operation.etnyContract import EtnyContract
from contract.operation.ecldContract import EcldContract
from contract.operation.imageRegistryContract import ImageRegistryContract
from contract.operation.polygonProtocolContract import PolygonProtocolContract
from contract.operation.bloxbergProtocolContract import BloxbergProtocolContract
import contract.abi.etnyAbi as contractBloxberg
import contract.abi.polygonProtocolAbi as protocolContractPolygon

LAST_BLOCKS = 20
VERSION = "v3"


class EthernityCloudRunner:
    def __init__(self, network_address=ECAddress.BLOXBERG.TESTNET_ADDRESS):
        self.node_address = ""
        self.challenge_hash = ""
        self.order_number = -1
        self.do_hash = None
        self.do_request_id = -1
        self.do_request = -1
        self.script_hash = ""
        self.file_set_hash = ""
        self.interval = None
        self.order_placed_timer = None
        self.task_has_been_picked_for_approval = False
        self.get_result_from_order_repeats = 1
        self.runner_type = None
        self.network_address = network_address
        self.resource = 0
        self.enclave_image_ipfs_hash = ""
        self.enclave_public_key = ""
        self.enclave_docker_compose_ipfs_hash = ""
        self.token_contract = None
        self.protocol_contract = None
        self.protocol_abi = None
        self.image_registry_contract = ImageRegistryContract(self.network_address)

        if network_address in [
            ECAddress.BLOXBERG.TESTNET_ADDRESS,
            ECAddress.BLOXBERG.MAINNET_ADDRESS,
        ]:
            self.token_contract = EtnyContract(network_address)
            self.protocol_contract = BloxbergProtocolContract(network_address)
            self.protocol_abi = contractBloxberg.contract.get("abi")
        elif network_address == ECAddress.POLYGON.MAINNET_ADDRESS:
            self.token_contract = EcldContract(network_address)
            self.protocol_contract = PolygonProtocolContract(
                ECAddress.POLYGON.MAINNET_PROTOCOL_ADDRESS
            )
            self.protocol_abi = protocolContractPolygon.contract.get("abi")
        elif network_address == ECAddress.POLYGON.TESTNET_ADDRESS:
            self.token_contract = EcldContract(network_address)
            self.protocol_contract = PolygonProtocolContract(
                ECAddress.POLYGON.TESTNET_PROTOCOL_ADDRESS
            )
            self.protocol_abi = protocolContractPolygon.contract.get("abi")

    def is_mainnet(self):
        return self.network_address in [
            ECAddress.BLOXBERG.MAINNET_ADDRESS,
            ECAddress.POLYGON.MAINNET_ADDRESS,
        ]

    def dispatch_ec_event(
        self, message, status=ECStatus.DEFAULT, event_type=ECEvent.TASK_PROGRESS
    ):
        # Custom event dispatching logic
        print(f"Event: {event_type}, Message: {message}, Status: {status}")

    def get_enclave_details(self):
        details = self.image_registry_contract.get_enclave_details_v3(
            self.runner_type, VERSION
        )
        if details:
            (
                self.enclave_image_ipfs_hash,
                self.enclave_public_key,
                self.enclave_docker_compose_ipfs_hash,
            ) = details
            self.dispatch_ec_event(
                f"ENCLAVE_IMAGE_IPFS_HASH:{self.enclave_image_ipfs_hash}"
            )
            self.dispatch_ec_event(f"ENCLAVE_PUBLIC_KEY:{self.enclave_public_key}")
            self.dispatch_ec_event(
                f"ENCLAVE_DOCKER_COMPOSE_IPFS_HASH:{self.enclave_docker_compose_ipfs_hash}"
            )

    def get_tokens_from_faucet(self):
        if self.token_contract is None:
            return {"success": False, "message": "Token contract is not initialized."}
        account = self.token_contract.get_current_wallet()
        balance = self.token_contract.get_balance()
        if int(balance) <= 100:
            tx = self.token_contract.get_faucet_tokens(account)
            transaction_hash = tx.hash
            is_processed = self.wait_for_transaction_to_be_processed(
                self.token_contract, transaction_hash
            )
            if not is_processed:
                return {
                    "success": False,
                    "message": "Unable to create request, please check connectivity with Bloxberg node.",
                }
            return {"success": True}
        return {"success": True}

    def get_reason(self, contract, tx_hash):
        tx = contract.get_provider().get_transaction(tx_hash)
        if not tx:
            print("tx not found")
            return "Transaction hash not found"
        del tx.gas_price
        code = contract.get_provider().call(tx, tx.block_number)
        reason = Web3.to_utf8_string(f"0x{code[138:]}")
        print(reason)
        return reason.strip()

    def wait_for_transaction_to_be_processed(self, contract, transaction_hash):
        contract.get_provider().wait_for_transaction(transaction_hash)
        tx_receipt = contract.get_provider().get_transaction_receipt(transaction_hash)
        print(tx_receipt)
        return not (not tx_receipt and tx_receipt.status == 0)

    def handle_metamask_connection(self):
        try:
            self.token_contract.get_provider().send("eth_requestAccounts", [])
            wallet_address = self.token_contract.get_current_wallet()
            return wallet_address is not None and wallet_address != ""
        except Exception as e:
            return False

    def listen_for_add_do_request_event(self):
        interval_repeats = 0
        add_do_request_ev_passed = False
        order_placed_ev_passed = False
        order_closed_ev_passed = False

        protocol_contract = self.protocol_contract.get_contract()

        def message_interval():
            nonlocal interval_repeats
            if interval_repeats % 2 == 0:
                self.dispatch_ec_event(
                    f"\\ Waiting for the task to be processed by {self.node_address} ..."
                )
            else:
                self.dispatch_ec_event(
                    f"/ Waiting for the task to be processed by {self.node_address} ..."
                )
            interval_repeats += 1

        def order_approved():
            nonlocal order_placed_ev_passed
            order_placed_ev_passed = True
            protocol_contract.off("_orderPlacedEV", order_placed_ev)
            if not self.node_address:
                self.approve_order(self.order_number)
            self.dispatch_ec_event(
                f"Order {self.order_number} was placed and approved."
            )
            self.dispatch_ec_event(
                f"Order {self.order_number} was placed and approved.",
                ECStatus.DEFAULT,
                ECEvent.TASK_ORDER_PLACED,
            )
            self.interval = time.setInterval(message_interval, 1000)

        def add_do_request_ev(_from, _do_request):
            wallet_address = self.token_contract.get_provider().send(
                "eth_requestAccounts", []
            )[0]
            if (
                wallet_address
                and _from.lower() == wallet_address.lower()
                and not add_do_request_ev_passed
            ):
                self.do_request = _do_request.to_number()
                self.dispatch_ec_event(
                    f"Task was picked up and DO Request {self.do_request} was created."
                )
                add_do_request_ev_passed = True
                protocol_contract.off("_addDORequestEV", add_do_request_ev)
                self.dispatch_ec_event(
                    f"Task was picked up and DO Request {self.do_request} was created.",
                    ECStatus.DEFAULT,
                    ECEvent.TASK_CREATED,
                )
                if self.order_number != -1 and self.do_request == self.do_request_id:
                    order_approved()
                self.order_placed_timer = time.setInterval(lambda: None, 60 * 1000)

        def order_placed_ev(order_number, do_request_id):
            self.task_has_been_picked_for_approval = True
            if (
                do_request_id.to_number() == self.do_request
                and not order_placed_ev_passed
                and self.do_request != -1
            ):
                self.order_number = order_number.to_number()
                self.do_request_id = do_request_id.to_number()
                order_approved()
            elif self.do_request == -1:
                self.order_number = order_number.to_number()
                self.do_request_id = do_request_id.to_number()

        def order_closed_ev(order_number):
            if (
                self.order_number == order_number.to_number()
                and not order_closed_ev_passed
                and self.order_number != -1
            ):
                self.interval.cancel()
                order_closed_ev_passed = True
                protocol_contract.off("_orderClosedEV", order_closed_ev)
                parsed_order_result = self.get_result_from_order(order_number)
                if not parsed_order_result["success"]:
                    self.dispatch_ec_event(
                        parsed_order_result["message"], ECStatus.ERROR
                    )
                else:
                    self.dispatch_ec_event(
                        {
                            "result": parsed_order_result["result"],
                            "result_hash": parsed_order_result["result_hash"],
                            "result_value": parsed_order_result["result_value"],
                            "result_value_timestamp": parsed_order_result[
                                "result_timestamp"
                            ],
                            "result_task_code": parsed_order_result["result_task_code"],
                        },
                        ECStatus.SUCCESS,
                        ECEvent.TASK_COMPLETED,
                    )

        protocol_contract.on("_addDORequestEV", add_do_request_ev)
        protocol_contract.on("_orderPlacedEV", order_placed_ev)
        protocol_contract.on("_orderClosedEV", order_closed_ev)

    def approve_order(self, order_id):
        tx = self.protocol_contract.approve_order(order_id)
        is_processed = self.wait_for_transaction_to_be_processed(
            self.protocol_contract, tx.hash
        )
        if not is_processed:
            reason = self.get_reason(self.protocol_contract, tx.hash)
            self.dispatch_ec_event(f"Unable to approve order. {reason}", ECStatus.ERROR)
            return
        self.dispatch_ec_event("Order successfully approved!", ECStatus.SUCCESS)
        self.dispatch_ec_event(f"TX hash: {tx.hash}")
        self.node_address = self.protocol_contract.get_order(order_id).dproc

    def get_current_wallet_public_key(self):
        account = self.token_contract.get_current_wallet()
        key_b64 = self.ethereum.request(
            {"method": "eth_getEncryptionPublicKey", "params": [account]}
        )
        return Web3.to_hex(Web3.to_bytes(key_b64))

    def get_v3_image_metadata(self, challenge_hash):
        base64_encrypted_challenge = encrypt_with_certificate(
            challenge_hash, self.enclave_public_key
        )
        challenge_ipfs_hash = ipfsClient.upload_to_ipfs(base64_encrypted_challenge)
        public_key = self.get_current_wallet_public_key()
        return f"{VERSION}:{self.enclave_image_ipfs_hash}:{self.runner_type}:{self.enclave_docker_compose_ipfs_hash}:{challenge_ipfs_hash}:{public_key}"

    def get_v3_code_metadata(self, code):
        script_checksum = sha256(code)
        base64_encrypted_script = encrypt_with_certificate(
            code, self.enclave_public_key
        )
        self.script_hash = ipfsClient.upload_to_ipfs(base64_encrypted_script)
        script_checksum = self.token_contract.sign_message(script_checksum)
        return f"{VERSION}:{self.script_hash}:{script_checksum}"

    def get_v3_input_metadata(self):
        file_set_checksum = self.token_contract.sign_message(ZERO_CHECKSUM)
        return f"{VERSION}::{file_set_checksum}"

    def create_do_request(
        self, image_metadata, code_metadata, input_metadata, node_address, gas_limit
    ):
        try:
            self.dispatch_ec_event(
                f"Submitting transaction for DO request on {format_date()}."
            )
            tx = self.protocol_contract.add_do_request(
                image_metadata,
                code_metadata,
                input_metadata,
                node_address,
                self.resource,
                gas_limit,
            )
            transaction_hash = tx.hash
            self.do_hash = transaction_hash
            self.dispatch_ec_event(
                f"Waiting for transaction {transaction_hash} to be processed..."
            )
            is_processed = self.wait_for_transaction_to_be_processed(
                self.protocol_contract, transaction_hash
            )
            if not is_processed:
                reason = self.get_reason(self.protocol_contract, transaction_hash)
                self.dispatch_ec_event(f"Unable to create DO request. {reason}")
                return False
            self.dispatch_ec_event(f"Transaction {transaction_hash} was confirmed.")
            return True
        except Exception as e:
            print(e)
            if (
                "cannot estimate gas; transaction may fail or may require manual gas limit"
                in str(e)
            ):
                return self.create_do_request(
                    image_metadata, code_metadata, input_metadata, node_address, 5000000
                )
            return False

    def parse_order_result(self, result):
        try:
            arr = result.split(":")
            t_bytes = arr[1] if arr[1].startswith("0x") else f"0x{arr[1]}"
            return {
                "version": arr[0],
                "transaction_bytes": t_bytes,
                "result_ipfs_hash": arr[2],
            }
        except Exception:
            raise ValueError(ECError.PARSE_ERROR)

    def parse_transaction_bytes(self, bytes):
        try:
            result = parse_transaction_bytes(self.protocol_abi, bytes)
            arr = result["result"].split(":")
            return {
                "version": arr[0],
                "from": result["from"],
                "task_code": arr[1],
                "task_code_string": ECOrderTaskStatus[arr[1]],
                "checksum": arr[2],
                "enclave_challenge": arr[3],
            }
        except Exception:
            raise ValueError(ECError.PARSE_ERROR)

    def get_result_from_order(self, order_id):
        try:
            order_result = self.protocol_contract.get_result_from_order(order_id)
            self.dispatch_ec_event(
                f"Task with order number {order_id} was successfully processed at {format_date()}."
            )
            parsed_order_result = self.parse_order_result(order_result)
            self.dispatch_ec_event(
                f"Result IPFS hash: {parsed_order_result['result_ipfs_hash']}"
            )
            transaction_result = self.parse_transaction_bytes(
                parsed_order_result["transaction_bytes"]
            )
            wallet = generate_wallet(
                self.challenge_hash, transaction_result["enclave_challenge"]
            )
            if not wallet or wallet != transaction_result["from"]:
                return {
                    "success": False,
                    "message": "Integrity check failed, signer wallet address is wrong.",
                }
            ipfs_result = ipfsClient.get_from_ipfs(
                parsed_order_result["result_ipfs_hash"]
            )
            current_wallet_address = self.token_contract.get_current_wallet()
            decrypted_data = decrypt_with_private_key(
                ipfs_result, current_wallet_address
            )
            if not decrypted_data["success"]:
                return {
                    "success": False,
                    "message": "Could not decrypt the order result.",
                }
            self.dispatch_ec_event(f"Result value: {decrypted_data['data']}")
            ipfs_result_checksum = sha256(decrypted_data["data"])
            if ipfs_result_checksum != transaction_result["checksum"]:
                return {
                    "success": False,
                    "message": "Integrity check failed, checksum of the order result is wrong.",
                }
            transaction = self.protocol_contract.get_provider().get_transaction(
                self.do_hash
            )
            block = self.protocol_contract.get_provider().get_block(
                transaction.block_number
            )
            block_timestamp = block.timestamp
            end_block_number = self.protocol_contract.get_provider().get_block_number()
            start_block_number = end_block_number - LAST_BLOCKS
            result_transaction_hash = None
            result_block_timestamp = None
            for i in range(end_block_number, start_block_number - 1, -1):
                block = (
                    self.protocol_contract.get_provider().get_block_with_transactions(i)
                )
                if not block or not block.transactions:
                    continue
                for transaction in block.transactions:
                    if (
                        transaction.to == self.protocol_contract.contract_address()
                        and transaction.data
                    ):
                        result_transaction_hash = transaction.hash
                        result_block_timestamp = block.timestamp
            return {
                "success": True,
                "contract_address": self.token_contract.contract_address(),
                "input_transaction_hash": self.do_hash,
                "output_transaction_hash": result_transaction_hash,
                "order_id": order_id,
                "image_hash": f"{self.enclave_image_ipfs_hash}:{self.runner_type}",
                "script_hash": self.script_hash,
                "file_set_hash": self.file_set_hash,
                "public_timestamp": block_timestamp,
                "result_hash": parsed_order_result["result_ipfs_hash"],
                "result_task_code": transaction_result["task_code_string"],
                "result_value": ipfs_result,
                "result_timestamp": result_block_timestamp,
                "result": decrypted_data["data"],
            }
        except Exception as ex:
            print(ex)
            if str(ex) == ECError.PARSE_ERROR:
                return {
                    "success": False,
                    "message": "Ethernity parsing transaction error.",
                }
            if str(ex) == ECError.IPFS_DOWNLOAD_ERROR:
                return {
                    "success": False,
                    "message": "Ethernity IPFS download result error.",
                }
            time.sleep(5)
            self.get_result_from_order_repeats += 1
            return self.get_result_from_order(order_id)

    def process_task(self, code):
        self.listen_for_add_do_request_event()
        self.challenge_hash = generate_random_hex_of_size(20)
        image_metadata = self.get_v3_image_metadata(self.challenge_hash)
        code_metadata = self.get_v3_code_metadata(code)
        input_metadata = self.get_v3_input_metadata()
        return self.create_do_request(
            image_metadata, code_metadata, input_metadata, self.node_address, None
        )

    def reset(self):
        self.order_number = -1
        self.do_hash = None
        self.do_request_id = -1
        self.do_request = -1
        self.script_hash = ""
        self.file_set_hash = ""
        self.interval = None
        self.get_result_from_order_repeats = 1
        self.task_has_been_picked_for_approval = False

    def cleanup(self):
        self.reset()
        contract = self.protocol_contract.get_contract()
        contract.remove_all_listeners()

    def is_node_operator_address(self, node_address):
        if is_null_or_empty(node_address):
            return True
        if is_address(node_address):
            is_node = self.protocol_contract.is_node_operator(node_address)
            if not is_node:
                self.dispatch_ec_event(
                    "Introduced address is not a valid node operator address.",
                    ECStatus.ERROR,
                )
                return False
            return True
        self.dispatch_ec_event(
            "Introduced address is not a valid wallet address.", ECStatus.ERROR
        )
        return False

    def initialize_storage(
        self, ipfs_address: str, protocol: str = "", port: int = None, token: str = ""
    ) -> None:
        global ipfsClient
        ipfsClient = IPFSClient(ipfs_address, protocol, port, token)
