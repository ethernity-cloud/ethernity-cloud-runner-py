import os
import time
from datetime import datetime
from typing import Any, Literal, Union

from eth_account import Account
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import TimeExhausted, TransactionNotFound

from .contract.abi.bloxbergAbi import contract as bloxbergAbi
from .contract.abi.polygonAbi import contract as polygonAbi
from .contract.operation.bloxbergProtocolContract import BloxbergProtocolContract
from .contract.operation.imageRegistryContract import ImageRegistryContract
from .contract.operation.polygonProtocolContract import PolygonProtocolContract
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

try:
    from dotenv import load_dotenv

    load_dotenv(".env" if os.path.exists(".env") else ".env.config")
except ImportError as e:
    pass


ipfs_address = os.environ.get("IPFS_ADDRESS", "")
if not ipfs_address:
    ipfs_address = "http://ipfs.ethernity.cloud:5001/api/v0"
ipfs_token = os.environ.get("IPFS_TOKEN", "")

LAST_BLOCKS = 20
VERSION = "v3"
NETWORK = os.environ.get("BLOCKCHAIN_NETWORK", None)

if len(os.environ.get("PRIVATE_KEY", "")) < 10:
    raise Exception("PRIVATE_KEY is not set in .env file")

SIGNER_ACCOUNT = Account().from_key(os.environ.get("PRIVATE_KEY"))

ipfsClient = Any


class EthernityCloudRunner:
    def __init__(self, network_address: Address = ECAddress.BLOXBERG.TESTNET_ADDRESS) -> None:  # type: ignore
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
        self.network_address = network_address
        self.enclave_image_ipfs_hash = ""
        self.enclave_public_key = ""
        self.enclave_docker_compose_ipfs_hash = ""
        self.trustedZoneImage = ""
        # for configurations with contract addresses
        if NETWORK is not None:
            network_address = ECNetworkEnvToEnum.get(
                NETWORK.lower(), ECAddress.BLOXBERG.TESTNET_ADDRESS
            )

        if network_address in [
            ECAddress.BLOXBERG.TESTNET_ADDRESS,
            ECAddress.BLOXBERG.MAINNET_ADDRESS,
        ]:
            self.protocol_contract = BloxbergProtocolContract(
                network_address, SIGNER_ACCOUNT
            )
            self.protocol_abi = bloxbergAbi.get("abi")
        elif network_address == ECAddress.POLYGON.MAINNET_ADDRESS:
            self.protocol_contract = PolygonProtocolContract(
                ECAddress.POLYGON.MAINNET_PROTOCOL_ADDRESS, SIGNER_ACCOUNT, True  # type: ignore
            )
            self.protocol_abi = polygonAbi.get("abi")
        elif network_address == ECAddress.POLYGON.TESTNET_ADDRESS:
            self.protocol_contract = PolygonProtocolContract(
                ECAddress.POLYGON.TESTNET_PROTOCOL_ADDRESS, SIGNER_ACCOUNT, False  # type: ignore
            )
            self.protocol_abi = polygonAbi.get("abi")

        self.token_contract = self.protocol_contract.ethernity_contract

        self.initialize_storage(ipfs_address, ipfs_token)

    def is_mainnet(self) -> bool:
        return self.network_address in [
            ECAddress.BLOXBERG.MAINNET_ADDRESS,
            ECAddress.POLYGON.MAINNET_ADDRESS,
        ]

    def dispatch_ec_event(
        self,
        message: Any,
        status: str = ECStatus.DEFAULT,
        event_type: str = ECEvent.TASK_PROGRESS,
    ) -> None:
        # Custom event dispatching logic
        print(f"Event: {event_type}, Message: {message}, Status: {status}")

    def get_enclave_details(self) -> None:
        details = self.image_registry_contract.get_enclave_details_v3(
            self.runner_type, VERSION, self.trustedZoneImage
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

    def get_reason(
        self, contract: Contract, tx_hash: str
    ) -> Literal["Transaction hash not found"]:
        tx = contract.get_provider().get_transaction(tx_hash)  # type: ignore
        if not tx:
            print("tx not found")
            return "Transaction hash not found"
        del tx.gas_price
        code = contract.get_provider().call(tx, tx.block_number)  # type: ignore
        reason = Web3.to_utf8_string(f"0x{code[138:]}")  # type: ignore
        print(reason)
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

        print(tx_receipt)
        return not (not tx_receipt and tx_receipt.status == 0)

    def check_web3_connection(self) -> Literal[False]:
        try:
            # self.token_contract.get_provider().send("eth_requestAccounts", [])
            self.protocol_contract.get_provider()
            wallet_address = self.protocol_contract.get_current_wallet()
            return wallet_address is not None and wallet_address != ""
        except Exception as e:
            return False

    def hex_to_bytes(self, hex_str: str) -> bytes:
        return bytes.fromhex(hex_str[2:] if hex_str[:2] == "0x" else hex_str)

    def bytes_to_hex(self, bytes_str: bytes) -> str:
        return "0x" + hexlify(bytes_str).decode("utf-8")

    def get_current_wallet_public_key(self) -> HexStr:
        return self.bytes_to_hex(
            PrivateKey.from_seed(
                self.hex_to_bytes(os.environ.get("PRIVATE_KEY", ""))
            ).public_key._public_key
        )

    def get_v3_image_metadata(self, challenge_hash: str) -> str:
        base64_encrypted_challenge = encrypt(challenge_hash, self.enclave_public_key)
        challenge_ipfs_hash = ipfsClient.upload_to_ipfs(base64_encrypted_challenge)
        public_key = self.get_current_wallet_public_key()
        return f"{VERSION}:{self.enclave_image_ipfs_hash}:{self.runner_type if not self.trustedZoneImage else self.trustedZoneImage}:{self.enclave_docker_compose_ipfs_hash}:{challenge_ipfs_hash}:{public_key}"

    def get_v3_code_metadata(self, code: str) -> str:
        script_checksum = sha256(code)
        base64_encrypted_script = encrypt(code.encode("utf-8"), self.enclave_public_key)
        self.script_hash = ipfsClient.upload_to_ipfs(base64_encrypted_script)
        script_checksum = self.protocol_contract.sign_message(script_checksum)
        return f"{VERSION}:{self.script_hash}:{script_checksum.signature.hex()}"

    def get_v3_input_metadata(self) -> str:
        file_set_checksum = self.protocol_contract.sign_message(ZERO_CHECKSUM)
        return f"{VERSION}::{file_set_checksum.signature.hex()}"

    def create_do_request(
        self,
        image_metadata: str,
        code_metadata: str,
        input_metadata: str,
        node_address: Address,
        gas_limit: None = None,
    ) -> bool:
        try:
            __provider = self.protocol_contract.get_provider()
            self.dispatch_ec_event(
                f"Submitting transaction for DO request on {format_date()}."
            )
            transaction_hash = self.protocol_contract.add_do_request(
                image_metadata,
                code_metadata,
                input_metadata,
                node_address,
                self.resources,
            )

            self.do_hash = transaction_hash
            receipt = None
            for i in range(100):
                try:
                    self.dispatch_ec_event(
                        f"Waiting for transaction {transaction_hash} to be processed..."
                    )

                    is_processed = self.wait_for_transaction_to_be_processed(
                        self.protocol_contract, transaction_hash
                    )
                    receipt = __provider.eth.wait_for_transaction_receipt(
                        transaction_hash
                    )
                    processed_logs = (
                        self.token_contract.events._addDORequestEV().process_receipt(
                            receipt
                        )
                    )
                    self.do_request = processed_logs[0].args._rowNumber
                except KeyError:
                    time.sleep(1)
                    continue
                except Exception as e:
                    print(e)
                    raise
                else:
                    print(
                        f"{datetime.now()} - Request {self.do_request} created successfully!",
                        "message",
                    )
                    self.do_hash = transaction_hash
                    break

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
            raise ValueError(ECError.PARSE_ERROR)

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
            raise ValueError(ECError.PARSE_ERROR)

    def get_result_from_order(self, order_id: int) -> Any:
        decrypted_data = {}
        try:
            # stuck here
            order_result = self.protocol_contract.get_result_from_order(order_id)
            # self.protocol_contract.ethernity_contract.caller(
            #     transaction={"from": SIGNER_ACCOUNT.address}
            # )._getResultFromOrder(order_id)
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
                self.challenge_hash.decode("utf-8"),  # type: ignore
                transaction_result["enclave_challenge"],
            )
            if not wallet or wallet != transaction_result["from"]:
                return {
                    "success": False,
                    "message": "Integrity check failed, signer wallet address is wrong.",
                }
            ipfs_result = ipfsClient.get_file_content(
                parsed_order_result["result_ipfs_hash"]
            )
            current_wallet_address = self.protocol_contract.get_current_wallet()
            # decrypted_data = decrypt_with_private_key(
            decrypted_data = decrypt_nacl(os.environ.get("PRIVATE_KEY"), ipfs_result)
            if not decrypted_data["success"]:
                return {
                    "success": False,
                    "message": "Could not decrypt the order result.",
                }

            self.dispatch_ec_event(f"Result value: {decrypted_data['data']}")
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
                "contract_address": self.protocol_contract.contract_address(),
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

    def process_task(self, code: str) -> bool:
        # self.listen_for_add_do_request_event()
        self.challenge_hash = generate_random_hex_of_size(20).encode("utf-8")
        image_metadata = self.get_v3_image_metadata(self.challenge_hash)
        code_metadata = self.get_v3_code_metadata(code)
        input_metadata = self.get_v3_input_metadata()
        do_sent_successfully = self.create_do_request(
            image_metadata, code_metadata, input_metadata, self.node_address, None
        )
        if do_sent_successfully:
            self._wait_for_processor()
            return True

        return False

    def _wait_for_processor(self) -> None:
        print(str(datetime.now()) + f" - Waiting for Ethernity network...", "message")
        while True:
            try:
                order = self.find_order(self.do_request)
            except Exception as e:
                print("--------", str(e))
            if order is not None:
                print("")
                print(f"{datetime.now()} - Connected!", "info")
                if self.approve_order(order):
                    break

                if self.get_result_from_order(order):
                    break
                time.sleep(5)
            else:
                time.sleep(5)

    def find_order(self, doreq: int) -> Union[int, None]:
        count = self.token_contract.functions._getOrdersCount().call()
        for i in range(count - 1, count - 5, -1):
            order = self.token_contract.caller()._getOrder(i)
            # if order[2] == doreq and order[4] == 0:
            if order[2] == doreq:
                return i
        return None

    def approve_order(self, order: int) -> bool:
        transaction_hash = self.protocol_contract.approve_order(order)

        receipt = None
        for i in range(100):
            try:
                receipt = self.protocol_contract.get_provider().eth.wait_for_transaction_receipt(
                    transaction_hash
                )
                self.node_address = self.protocol_contract.get_order(order)[1]
            except KeyError:
                time.sleep(1)
                continue
            except TimeExhausted:
                raise
            except Exception as e:
                print("erorr = ", e)
                raise
            else:
                print(
                    f"{datetime.now()} - Order {order} approved successfully!", "info"
                )
                print(f"{datetime.now()} - TX Hash: {transaction_hash}", "message")
                break

        if receipt is None:
            print(
                f"{datetime.now()} - Unable to approve order, please check connectivity with bloxberg node",
                "warning",
            )
            return True

        return False

    def reset(self) -> None:
        self.order_number = -1
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
        contract = self.protocol_contract.get_contract()
        # contract.remove_all_listeners()

    def is_node_operator_address(self, node_address: str) -> bool:
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

    def initialize_storage(self, ipfs_address: str, token: str = "") -> None:
        global ipfsClient
        ipfsClient = IPFSClient(ipfs_address, token)

    def run(
        self,
        runner_type: str,
        code: str,
        node_address: str,
        resources: Union[dict, None] = None,
        trustedZoneImage: str = "",
    ) -> None:
        if resources is None:
            self.resources = {
                "taskPrice": 10,
                "cpu": 1,
                "memory": 1,
                "storage": 40,
                "bandwidth": 1,
                "duration": 1,
                "validators": 1,
            }
            resources = self.resources
        else:
            self.resources = resources
        if trustedZoneImage:
            self.trustedZoneImage = trustedZoneImage
        try:
            balance = self.protocol_contract.get_balance()
            balance = int(balance)

            if balance < resources["taskPrice"]:
                self.dispatch_ec_event(
                    f"Your wallet balance ({balance}/{resources['taskPrice']}) is insufficient to cover the requested task price. The task has been declined.",
                    ECStatus.ERROR,
                )
                return

            self.node_address = node_address

            is_node_operator_address = self.is_node_operator_address(node_address)
            if is_node_operator_address:
                self.runner_type = runner_type
                self.cleanup()
                self.dispatch_ec_event("Started processing task...")
                self.image_registry_contract = ImageRegistryContract(
                    self.network_address,
                    (
                        self.runner_type
                        if not self.trustedZoneImage
                        else self.trustedZoneImage
                    ),
                    SIGNER_ACCOUNT,
                )
                connected = self.check_web3_connection()
                if connected:
                    self.get_enclave_details()
                    if self.network_address in [
                        ECAddress.POLYGON.MAINNET_ADDRESS,
                        ECAddress.POLYGON.TESTNET_ADDRESS,
                    ]:
                        self.dispatch_ec_event(
                            "Checking for the allowance on the current wallet..."
                        )
                        passed_allowance = self.token_contract.check_and_set_allowance(
                            self.protocol_contract.contract_address(),
                            "100",
                            str(resources["taskPrice"]),
                        )
                        if not passed_allowance:
                            self.dispatch_ec_event(
                                "Unable to set allowance.", ECStatus.ERROR
                            )
                            return
                        self.dispatch_ec_event("Allowance checking completed.")

                    can_process_task = self.process_task(code)
                    if not can_process_task:
                        self.dispatch_ec_event(
                            "Unable to proceed with the task; exiting.", ECStatus.ERROR
                        )
                else:
                    self.dispatch_ec_event(
                        "Unable to connect to MetaMask", ECStatus.ERROR
                    )
        except Exception as e:
            self.dispatch_ec_event(e, ECStatus.ERROR)
