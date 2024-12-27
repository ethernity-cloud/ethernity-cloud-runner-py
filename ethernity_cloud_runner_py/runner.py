import os
import time
import threading
from queue import Queue
from typing import Union, List
from datetime import datetime
from typing import Any, Literal, Union

from eth_account import Account
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import TimeExhausted, TransactionNotFound

from .contract.abi.bloxbergAbi import contract as bloxbergAbi
from .contract.abi.polygonProtocolAbi import contract as polygonAbi
from .contract.abi.ECLDAbi import contract as ECLDAbi
from .contract.operation.bloxbergProtocolContract import BloxbergProtocolContract
from .contract.operation.imageRegistryContract import ImageRegistryContract
from .contract.operation.polygonProtocolContract import PolygonProtocolContract
from .enums import ECNetworkByChainId
from binascii import hexlify
from nacl.public import Box, PrivateKey, PublicKey

# from .crypto import decrypt_with_private_key, encrypt_with_certificate, sha256
from .crypto import decrypt_nacl, encrypt, sha256
from .enums import (
    ZERO_CHECKSUM,
    ECAddress,
    ECError,
    ECEvent,
    ECOrderTaskStatus,
    ECStatus,
    ECNetworkEnvToEnum,
    ECLog,
    ECRunner,
)
from .ipfs import IPFSClient
from .utils import (
    format_date,
    generate_random_hex_of_size,
    is_address,
    is_null_or_empty,
    parse_transaction_bytes_ut,
    generate_wallet,
)

LAST_BLOCKS = 20
TRUSTEDZONE_VERSION = "v3"

class EthernityCloudRunner:
    def __init__(self, network_address: Address = ECAddress.BLOXBERG.TESTNET_ADDRESS) -> None:  # type: ignore
        self.private_key = ""
        self.node_address = ""
        self.challenge_hash = ""
        self.do_hash = None
        self.do_request_id = -1
        self.do_request = -1
        self.order = None
        self.order_id = -1
        self.script_hash = ""
        self.file_set_hash = ""
        self.interval = None
        self.order_placed_timer = None
        self.task_has_been_picked_for_approval = False
        self.get_result_from_order_repeats = 1
        self.network_address = network_address
        self.enclave_image_ipfs_hash = ""
        self.enclave_public_key = ""
        self.enclave_docker_compose_ipfs_hash = ""
        self.trustedZoneImage = ""
        
        self.event_queue = Queue()  # Queue to store events
        self.processed_events: List[str] = []  # List to store processed events
        self.task_thread = None
        self.current_order_index = 0
        self.status = ECStatus.RUNNING
        self.progress = ECEvent.INIT
        self.last_error = None
        self.log = []
        self.result = None
        self.log_level = ECLog.ERROR
        self.running = False
        self.network = "Bloxberg_Testnet"

    def set_network(self, network, type) -> None:
        self.network = network.lower()+ "_" + type.lower()
        self.trustedZoneImage = ECRunner()[network.upper()]["PYNITHY_RUNNER_"+type.upper()]
        self.network_address = getattr(getattr(ECAddress, network.upper(), None), f"{type.upper()}_ADDRESS", None)
        self.chain_id = ECNetworkByChainId[network.upper()][type.upper()]
        
    def set_private_key(self, private_key) -> None:
        self.private_key = private_key
        self.signer = Account.from_key(private_key)

    def connect(self) -> None:
        # for configurations with contract addresses
        network_address = ECNetworkEnvToEnum.get(
            self.network.lower(), ECAddress.BLOXBERG.TESTNET_ADDRESS
        )

        if network_address in [
            ECAddress.BLOXBERG.TESTNET_ADDRESS,
            ECAddress.BLOXBERG.MAINNET_ADDRESS,
        ]:
            self.protocol = BloxbergProtocolContract(
                network_address, self.signer
            )
            self.protocol_abi = bloxbergAbi.get("abi")
            self.token_contract = self.contract.token_contract
            self.protocol_contract = self.contract.protocol_contract

        elif network_address == ECAddress.POLYGON.MAINNET_ADDRESS:
            self.contract = PolygonProtocolContract(
                ECAddress.POLYGON.MAINNET_ADDRESS, ECAddress.POLYGON.MAINNET_PROTOCOL_ADDRESS, self.signer, self.chain_id  # type: ignore
            )
            self.protocol_abi = polygonAbi.get("abi")
            self.token_contract = self.contract.token_contract
            self.protocol_contract = self.contract.protocol_contract

        elif network_address == ECAddress.POLYGON.TESTNET_ADDRESS:
            self.contract = PolygonProtocolContract(
                ECAddress.POLYGON.TESTNET_ADDRESS, ECAddress.POLYGON.TESTNET_PROTOCOL_ADDRESS, self.signer, self.chain_id  # type: ignore
            )
            self.protocol_abi = polygonAbi.get("abi")
            self.token_contract = self.contract.token_contract
            self.protocol_contract = self.contract.protocol_contract

    def set_log_level(self, level):
        self.log_level = ECLog[level.upper()]

    def is_mainnet(self) -> bool:
        return self.network_address in [
            ECAddress.BLOXBERG.MAINNET_ADDRESS,
            ECAddress.POLYGON.MAINNET_ADDRESS,
        ]

    def log_append(
        self,
        message: Any,
        log_level: str = ECLog.INFO,
    ) -> None:
        status = self.status.name
        event_type = self.progress.name
        # Custom event dispatching logic
        if (self.log_level >= log_level):
            debug_details = ""
            if (self.log_level == ECLog.DEBUG):
                debug_details = "Event:",{event_type},"Status:",{status}
            self.log.append(f"[{log_level.name}] {datetime.now()} {message} {debug_details}")
                  

    def get_enclave_details(self) -> bool:
        details = self.image_registry_contract.get_enclave_details_v3(
            self.securelock_enclave, self.securelock_version, self.trustedZoneImage, TRUSTEDZONE_VERSION
        )
        if details:
            (
                self.enclave_image_ipfs_hash,
                self.enclave_public_key,
                self.enclave_docker_compose_ipfs_hash,
            ) = details

            print(self.enclave_public_key)
            self.log_append(
                f"ENCLAVE_IMAGE_IPFS_HASH: {self.enclave_image_ipfs_hash}"
            )
            self.log_append(f"ENCLAVE_PUBLIC_KEY:\n{self.enclave_public_key}",ECLog.DEBUG)
            self.log_append(
                f"ENCLAVE_DOCKER_COMPOSE_IPFS_HASH: {self.enclave_docker_compose_ipfs_hash}"
            )
            return True
        else:
            return False

    def get_reason(
        self, contract: Contract, tx_hash: str
    ) -> Literal["Transaction hash not found"]:
        tx = contract.get_provider().get_transaction(tx_hash)  # type: ignore
        if not tx:
            return "Transaction not found"
        del tx.gas_price
        code = contract.get_provider().call(tx, tx.block_number)  # type: ignore
        reason = Web3.to_utf8_string(f"0x{code[138:]}")  # type: ignore
        return reason.strip()

    def wait_for_transaction_to_be_processed(
        self, contract: Contract, transaction_hash: str, attempt: int = 0
    ) -> bool:
        while True and attempt < 10:
            try:
                contract.get_provider().eth.wait_for_transaction_receipt(transaction_hash)  # type: ignore
                tx_receipt = contract.get_provider().eth.get_transaction_receipt(transaction_hash)  # type: ignore
                if tx_receipt:
                    break
            except TransactionNotFound or TimeExhausted:
                # we need to sleep here to avoid spamming the node
                time.sleep(3)
                self.wait_for_transaction_to_be_processed(
                    contract, transaction_hash, attempt + 1
                )

        return not (not tx_receipt and tx_receipt.status == 0)

    def check_web3_connection(self) -> Literal[False]:
        try:
            # self.token_contract.get_provider().send("eth_requestAccounts", [])
            self.contract.get_provider()
            wallet_address = self.contract.get_current_wallet()
            return wallet_address is not None and wallet_address != ""
        except Exception as e:
            self.log_append(
                f"{e}", ECLog.ERROR
            )
        return False

    def hex_to_bytes(self, hex_str: str) -> bytes:
        return bytes.fromhex(hex_str[2:] if hex_str[:2] == "0x" else hex_str)

    def bytes_to_hex(self, bytes_str: bytes) -> str:
        return "0x" + hexlify(bytes_str).decode("utf-8")

    def get_current_wallet_public_key(self) -> HexStr:
        return self.bytes_to_hex(
            PrivateKey.from_seed(
                self.hex_to_bytes(self.private_key)
            ).public_key._public_key
        )

    def get_v3_image_metadata(self, challenge_hash: str) -> str:
        base64_encrypted_challenge = encrypt(challenge_hash, self.enclave_public_key)
        challenge_ipfs_hash = ipfsClient.upload_to_ipfs(base64_encrypted_challenge)
        if challenge_ipfs_hash != None:
            self.log_append(
                f"Uploaded challenge to IPFS: {challenge_ipfs_hash}"
            )
        public_key = self.get_current_wallet_public_key()
        return f"{TRUSTEDZONE_VERSION}:{self.enclave_image_ipfs_hash}:{self.securelock_enclave if not self.trustedZoneImage else self.trustedZoneImage}:{self.enclave_docker_compose_ipfs_hash}:{challenge_ipfs_hash}:{public_key}"

    def get_v3_code_metadata(self, code: str) -> str:
        script_checksum = sha256(code)
        base64_encrypted_script = encrypt(code.encode("utf-8"), self.enclave_public_key)
        self.script_hash = ipfsClient.upload_to_ipfs(base64_encrypted_script)
        if self.script_hash!= None:
            self.log_append(
                f"Uploaded encrypted code to IPFS: {self.script_hash}"
            )
        script_checksum = self.contract.sign_message(script_checksum)
        return f"{TRUSTEDZONE_VERSION}:{self.script_hash}:{script_checksum.signature.hex()}"

    def get_v3_input_metadata(self) -> str:
        file_set_checksum = self.contract.sign_message(ZERO_CHECKSUM)
        return f"{TRUSTEDZONE_VERSION}::{file_set_checksum.signature.hex()}"

    def create_do_request(
        self,
        image_metadata: str,
        code_metadata: str,
        input_metadata: str,
        node_address: Address,
        gas_limit: None = None,
    ) -> bool:
        try:
            __provider = self.contract.get_provider()
            self.log_append(
                f"Submitting transaction for DO request",
            )
            while True:
                try:
                    transaction_hash = self.contract.add_do_request(
                        image_metadata,
                        code_metadata,
                        input_metadata,
                        node_address,
                        self.resources,
                    )
                    break
                except Exception as e: 
                    self.log_append(
                        f"Unable to build transaction: {e}", ECLog.WARNING
                    )
                    time.sleep(1)


            self.do_hash = transaction_hash
            receipt = None
            for i in range(100):
                try:
                    self.log_append(
                        f"{transaction_hash} is pending..."
                    )

                    is_processed = self.wait_for_transaction_to_be_processed(
                        self.contract, transaction_hash
                    )
                    receipt = __provider.eth.wait_for_transaction_receipt(
                        transaction_hash
                    )
                    processed_logs = (
                        self.protocol_contract.events._addDORequestEV().process_receipt(
                            receipt
                        )
                    )
                    self.do_request = processed_logs[0].args._rowNumber
                except KeyError:
                    time.sleep(1)
                    continue
                except Exception as e:
                    self.log_append(
                        f"{e}", ECLog.ERROR
                    )
                    raise
                else:
                    self.log_append(
                        f"{transaction_hash} confirmed!"
                    )
                    self.log_append(
                        f"Request {self.do_request} was created successfully!"
                    )
                    self.do_hash = transaction_hash
                    break

            if not is_processed:
                reason = self.get_reason(self.protocol_contract, transaction_hash)
                self.log_append(
                        f"Unable to create DO request: {reason}"
                )
                return False

            return True
        except Exception as e:
            self.log_append(
                f"{e}", ECLog.ERROR
            )
            # TODO Calculate gas propely
            if (
                "cannot estimate gas; transaction may fail or may require manual gas limit"
                in str(e)
            ):
                return self.create_do_request(
                    image_metadata, code_metadata, input_metadata, node_address, 5000000
                )
            return False

    def parse_order_result(self, result: str) -> dict[str, Any]:
        try:
            arr = result.split(":")
            t_bytes = arr[1] if arr[1].startswith("0x") else f"0x{arr[1]}"
            return {
                "version": arr[0],
                "transaction_bytes": t_bytes,
                "result_ipfs_hash": arr[2],
            }
        except Exception:
            raise ValueError(ECError.PARSE_ERROR.value)

    def parse_transaction_bytes(self, bytes: bytes) -> dict[str, str]:
        try:
            result = parse_transaction_bytes_ut(self.protocol_abi, bytes)
            arr = result["result"].split(":")
            return {
                "version": arr[0],
                "from": result["from"],
                "task_code": arr[1],
                "task_code_string": ECOrderTaskStatus[int(arr[1])],
                "checksum": arr[2],
                "enclave_challenge": arr[3],
            }
        except Exception as ex:
            raise ValueError(ECError.PARSE_ERROR.value)

    def get_result_from_order(self, order_id: int) -> Any:
        decrypted_data = {}

        try:
            self.log_append(f"Operator {self.order[1]} is processing task {order_id}")

            while True:
                try:
                    while self.contract.get_status_from_order(order_id) == 1:
                        time.sleep(1)

                    order_result = self.contract.get_result_from_order(order_id)

                    self.log_append(
                        f"Task {order_id} was successfully processed."
                    )
                    break
                except Exception as e:
                    self.log_append(f"Checking order details: {e}", ECLog.WARNING)

            try:

                parsed_order_result = self.parse_order_result(order_result)

                self.log_append(
                        f"Checking result hash: {parsed_order_result['result_ipfs_hash']}"
                )

                transaction_result = self.parse_transaction_bytes(
                    parsed_order_result["transaction_bytes"]
                )
            except Exception as e:
                self.log_append(f"Error parsing transaction bytes: {e}", ECLog.ERROR)
                self.log_append(f"Could not parse transaction bytes. The operator result is invalid, indicating a failure", ECLog.ERROR)
                self.log_append(f"The tokens associated with the task will be refunded after automatic result validation", ECLog.ERROR)
                self.log_append(f"Please try again.", ECLog.ERROR)
                return False


            self.log_append(f"Verifying ZK proof")

            wallet = generate_wallet(
                self.challenge_hash.decode("utf-8"),  # type: ignore
                transaction_result["enclave_challenge"],
            )
            if not wallet or wallet != transaction_result["from"]:
                self.log_append(f"Integrity check failed, signer wallet address is wrong", ECLog.ERROR)
                self.log_append(f"The tokens associated with the task will be refunded after automatic result validation.",  ECLog.ERROR)
                self.log_append(f"Please try running the task again", ECLog.ERROR)
                return False

            self.log_append(f"Verification succesful!")
            self.log_append(f"The result is signed by: {wallet}")

            while True:
                try:
                    time.sleep(1)
                    self.log_append(f"Downloading {parsed_order_result['result_ipfs_hash']}")

                    ipfs_result = ipfsClient.get_file_content(
                        parsed_order_result["result_ipfs_hash"]
                    )
                    break
                except Exception as e:
                    self.log_append(f"Error downloading IPFS result: {e}", ECLog.WARNING)
                    self.log_append(f"Retrying")

            self.log_append(f"Decrypting result")

            decrypted_data = decrypt_nacl(self.private_key, ipfs_result)
            if not decrypted_data["success"]:
                self.log_append(f"Could not decrypt the order result.", ECLog.ERROR)


            self.log_append(f"Result value: {decrypted_data['data']}",ECLog.DEBUG)
            ipfs_result_checksum = sha256(decrypted_data["data"],True)
            if ipfs_result_checksum != transaction_result["checksum"]:
                self.log_append(f"Integrity check failed, checksum of the order result is wrong. {ipfs_result_checksum} != {transaction_result['checksum']}", ECLog.ERROR)
                return False
            
            result_transaction_hash = ""
            block_timestamp = 0
            result_block_timestamp = 0

            # self.log_append(
            #     f"Collecting result transaction hash..."
            # )
            # transaction = self.protocol_contract.get_provider().eth.get_transaction_receipt(
            #     self.do_hash
            # )
            # block = self.protocol_contract.get_provider().eth.get_block(
            #     transaction.blockNumber
            # )
            # block_timestamp = block.timestamp
            # end_block_number = self.protocol_contract.get_provider().eth.get_block_number()
            # start_block_number = end_block_number - LAST_BLOCKS
            # result_transaction_hash = None
            # result_block_timestamp = None
            # for i in range(end_block_number, start_block_number - 1, -1):
            #     block = (
            #         self.protocol_contract.get_provider().eth.get_block(i)
            #     )
            #     if not block or not block.transactions:
            #         continue
            #     # TODO: fix output transaction reporting
            #     for transaction in block.transactions:
            #         transaction_details = self.protocol_contract.get_provider().eth.get_transaction(transaction)
            #         if (
            #             transaction_details.to == self.protocol_contract.contract_address()
            #             transaction_details.from = self.order[1]
            #         ):
            #             result_transaction_hash = transaction
            #             result_block_timestamp = block.timestamp

            return {
                "success": True,
                "contract_address": self.contract.get_protocol_address(),
                "input_transaction_hash": self.do_hash,
                "output_transaction_hash": result_transaction_hash,
                "order_id": order_id,
                "image_hash": f"{self.enclave_image_ipfs_hash}:{self.securelock_enclave}",
                "script_hash": self.script_hash,
                "file_set_hash": self.file_set_hash,
                "public_timestamp": block_timestamp,
                "result_hash": parsed_order_result["result_ipfs_hash"],
                "result_task_code": transaction_result["task_code_string"],
                "result_value": ipfs_result,
                "result_timestamp": result_block_timestamp,
                "value": decrypted_data["data"],
            }
        except ValueError as e:
            self.log_append(
                f"{e}", ECLog.ERROR
            )

            if str(e) == ECError.PARSE_ERROR:
                error_message = ECError.PARSE_ERROR
                self.log_append(error_message)
                self.progress = ECEvent.FINISHED
                self.status = ECStatus.ERROR
                return False
            if str(e) == ECError.IPFS_DOWNLOAD_ERROR:
                self.log_append("Unable to download result from ipfs, trying again",ECLog.WARNING)
                time.sleep(5)


            if (self.get_result_from_order_repeats > 10):
                self.log_append("After multiple tries, the result cannot be downloaded", ECLog.ERROR)
                self.progress = ECEvent.FINISHED
                self.status = ECStatus.ERROR
                return False

            self.get_result_from_order_repeats += 1
            return self.get_result_from_order(order_id)


    def create_task(self, code: str) -> bool:
        # self.listen_for_add_do_request_event()
        self.challenge_hash = generate_random_hex_of_size(20).encode("utf-8")
        image_metadata = self.get_v3_image_metadata(self.challenge_hash)
        code_metadata = self.get_v3_code_metadata(code)
        input_metadata = self.get_v3_input_metadata()
        self.current_order_index = self.protocol_contract.functions._getOrdersCount().call()
        do_sent_successfully = self.create_do_request(
            image_metadata, code_metadata, input_metadata, self.node_address, None
        )
        if do_sent_successfully:
            return True
        return False
    
    
    def check_order_for_task(self) -> bool:
        self.log_append(
            f"Waiting for Ethernity CLOUD network..."
        )

        while True:
            try:
                if self.find_order(self.do_request):
                    self.log_append(
                        f"Connected!"
                    )
                    break
            except Exception as e:
                self.log_append(
                    f"{e}", ECLog.ERROR
                )
            time.sleep(1)
        return True
    
    def approve_task(self) -> bool:
        self.log_append(
            f"Approving task {self.order_id}..."
        )
        while True:
            try:
                if self.approve_order():
                    break
            except Exception as e:
                self.log_append(
                    f"{e}", ECLog.ERROR
                )
            time.sleep(1)

        return True



    def process_task(self) -> bool:
        result = self.get_result_from_order(self.order_id)
        if result:
            return result
        return False


    def find_order(self, doreq: int) -> bool:
        time.sleep(1)
        count = self.protocol_contract.functions._getOrdersCount().call()
        for i in range(count - 1, self.current_order_index - 1, -1):
            order = self.protocol_contract.caller()._getOrder(i)
            # if order[2] == doreq and order[4] == 0:
            if order[2] == doreq:
                self.order = order
                self.order_id = i
                return True
        return False

    def approve_order(self) -> bool:
        transaction_hash = self.contract.approve_order(self.order_id)

        if self.node_address != "":
            self.log_append(f"Transaction is delegated to {self.node_address}, skipping approval")
            return True

        receipt = None
        for i in range(100):
            try:
                self.log_append(
                        f"{transaction_hash} is pending..."
                )
                receipt = self.contract.get_provider().eth.wait_for_transaction_receipt(
                    transaction_hash
                )
                if receipt is not None:
                    self.node_address = self.contract.get_order(self.order_id)[1]
                    break
            except KeyError:
                time.sleep(1)
                continue
            except TimeExhausted:
                raise
            except Exception as e:
                self.log_append(
                    f"{e}", ECLog.WARNING
                )
            time.sleep(1)
            
        self.log_append(
            f"{transaction_hash} confirmed!"
        )

        self.log_append(
            f"Task {self.order_id} approved successfully!"
        )
        
        return True

    def reset(self) -> None:
        self.order = None
        self.order_id = -1
        self.do_hash = None
        self.do_request_id = -1
        self.do_request = -1
        self.script_hash = ""
        self.file_set_hash = ""
        self.interval = None
        self.get_result_from_order_repeats = 1
        self.task_has_been_picked_for_approval = False

    def cleanup(self) -> None:
        self.reset()

    def is_node_operator_address(self, node_address: str) -> bool:
        if is_null_or_empty(node_address):
            return True
        
        if is_address(node_address):
            is_node = self.contract.is_node_operator(node_address)
            if not is_node:
                self.log_append(
                    "The target address is not a valid node operator address",
                    ECLog.ERROR
                )
                return False
            return True
        self.log_append(
            "Introduced address is not a valid wallet address.", ECLog.ERROR
        )
        return False

    def set_storage_ipfs(self, ipfs_address: str, token: str = "") -> None:
        global ipfsClient
        ipfsClient = IPFSClient(ipfs_address, token)
    def run(
        self,
        resources: Union[dict, None],
        securelock_enclave: str,
        securelock_version: str,
        code: str,
        node_address: str = "",
        trustedzone_enclave: str = "etny-pynithy-testnet",
    ) -> None:
        if resources is None:
            resources = {
                "taskPrice": 10,
                "cpu": 1,
                "memory": 1,
                "storage": 40,
                "bandwidth": 1,
                "duration": 1,
                "validators": 1,
            }
        
        self.resources = resources
        self.price = resources['taskPrice']

        if self.running:
            raise RuntimeError("A task is already running.")

        self.status = ECStatus.RUNNING
        self.last_error = None
        self.log = []  # Clear log for the new task
        self.result = None
        self.running = True
        self.processed_events = []

        # Populate the event queue with initial events
        self._populate_event_queue()

        # Start task thread
        self.task_thread = threading.Thread(
            target=self._process_events,
            args=(securelock_enclave, securelock_version, code, node_address, resources),
            daemon=True
        )
        self.task_thread.start()

    def _populate_event_queue(self):
        """Populate the event queue with predefined events."""
        events = [
            ECEvent.INIT,
            ECEvent.CREATED,
            ECEvent.ORDER_PLACED,
            ECEvent.IN_PROGRESS,
            ECEvent.FINISHED,
        ]
        for event in events:
            self.event_queue.put(event)

    def _process_events(self, securelock_enclave, securelock_version, code, node_address, resources):
        """Process events from the queue."""
        try:
            while not self.event_queue.empty():
                event = self.event_queue.get()

                if event == ECEvent.INIT:
                    self.progress = ECEvent.INIT
                    self.log_append("Checking wallet balance...")
                    balance = self.contract.get_balance()
                    balance = int(balance)

                    if balance < self.price:
                        self.progress = ECEvent.FINISHED
                        self.status = ECStatus.ERROR
                        error_message = (
                            f"Insufficient wallet balance. Required: {self.price}, "
                            f"Available: {balance}"
                        )
                        self.last_error = error_message
                        self.log_append(error_message, ECLog.ERROR)
                        self.processed_events.append(event)
                        return
                    
                    self.log_append("Verifying node address...")
                    self.node_address = node_address

                    is_node_operator_address = self.is_node_operator_address(node_address)
                    if not is_node_operator_address:
                        self.progress = ECEvent.FINISHED
                        self.status = ECStatus.ERROR
                        error_message = "Node address verification failed."
                        self.last_error = error_message
                        self.log_append(error_message, ECLog.ERROR)
                        self.processed_events.append(event)
                        return
                    self.log_append("Checking image registry...")

                    self.securelock_enclave = securelock_enclave
                    self.securelock_version = securelock_version
                    self.cleanup()
   
                    self.image_registry_contract = ImageRegistryContract(
                        self.network_address,
                        (
                            self.securelock_enclave
                            if not self.trustedZoneImage
                            else self.trustedZoneImage
                        ),
                        self.signer,
                    )

                    connected = self.check_web3_connection()
                    
                    if connected:
                        if not self.get_enclave_details():
                            self.progress = ECEvent.FINISHED
                            self.status = ECStatus.ERROR
                            error_message = "Unable to find enclave in registry"
                            self.last_error = error_message
                            self.log_append(error_message, ECLog.ERROR)
                            self.processed_events.append(event)
                            return

                        if self.network_address in [
                            ECAddress.POLYGON.MAINNET_ADDRESS,
                            ECAddress.POLYGON.TESTNET_ADDRESS,
                        ]:
                            self.log_append(
                                "Checking allowance on the current wallet..."
                            )
                            while True:
                                try:
                                    passed_allowance = self.contract.check_and_set_allowance(
                                        str(self.price),
                                    )
                                    if passed_allowance == True:
                                        break
                                except Exception as e:
                                    self.log_append(f"Unable to set allowance on current wallet: {e}", ECLog.WARNING)
                                    self.log_append(f"Retrying...", ECLog.WARNING)

                            self.log_append("Allowance checking completed.")
                        if not self.create_task(code):
                            self.progress = ECEvent.FINISHED
                            self.status = ECStatus.ERROR
                            error_message = "Unable to create a DO request"
                            self.last_error = error_message
                            self.log_append(error_message, ECLog.ERROR)
                            self.processed_events.append(event)
                            return
        
                elif event == ECEvent.CREATED:
                    self.progress = event

                    if not self.check_order_for_task():
                        self.progress = ECEvent.FINISHED
                        self.status = ECStatus.ERROR
                        error_message = "Failed to get operator(s) to respond to task creation. Please adjust your request accordingly"
                        self.last_error = error_message
                        self.log_append(error_message,ECLog.ERROR)
                        self.processed_events.append(event)
                        return
                    
                elif event == ECEvent.ORDER_PLACED:
                    self.progress = event
                    if not self.approve_task():
                        self.progress = ECEvent.FINISHED
                        self.status = ECStatus.ERROR
                        error_message = "Task approval failed."
                        self.last_error = error_message
                        self.log_append(error_message,ECLog.ERROR)
                        self.processed_events.append(event)
                        return

                elif event == ECEvent.IN_PROGRESS:
                    self.progress = event

                    result = self.process_task()
                    if not result:
                        self.progress = ECEvent.FINISHED
                        self.status = ECStatus.ERROR
                        error_message = "Task processing failed."
                        self.last_error = error_message
                        self.log_append(error_message,ECLog.ERROR)
                        self.processed_events.append(event)
                        return
                    self.result = result

                elif event == ECEvent.FINISHED:
                    self.progress = ECEvent.FINISHED
                    self.status = ECStatus.SUCCESS
                    self.log_append("Task completed successfully.")

                # Mark the event as processed
                self.processed_events.append(event)

        except Exception as e:
            self.progress = ECEvent.FINISHED
            self.status = ECStatus.ERROR
            self.last_error = str(e)
            self.log_append(f"Error: {self.last_error}",ECLog.ERROR)
            return
        finally:
            self.running = False

    def get_state(self):
        """Retrieve the current task status, including events."""
        remaining_events = list(self.event_queue.queue)
        return {
            "status": self.status.name,
            "progress": self.progress.name,
            "last_error": self.last_error,
            "log": self.log,  # Renamed from 'outputs'
            "result": self.result,
            "processed_events": self.processed_events,
            "remaining_events": remaining_events,
        }

    def is_running(self):
        """Check if a task is currently running."""
        return self.running
    
    def get_result(self):
        """Retrieve the result of the task."""
        return self.result