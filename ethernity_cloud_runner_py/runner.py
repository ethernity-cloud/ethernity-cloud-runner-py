import os
import re
import time
import threading
from queue import Queue
from typing import Union, List, Optional, Dict, Any, Literal
from datetime import datetime
from eth_account import Account
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import TimeExhausted, TransactionNotFound, Web3RPCError
from web3.logs import DISCARD
from .errors import install_web3_friendly_prefix_filter, raw_rpc_error_message
from .contract.abi.bloxbergAbi import contract as bloxbergAbi
from .contract.abi.polygonProtocolAbi import contract as polygonAbi
from .contract.abi.ECLDAbi import contract as ECLDAbi
from .contract.operation.imageRegistryContract import ImageRegistryContract
from .contract.operation.protocolContract import protocolContract
from .contract.operation.esrContract import ESRContract
from .state_cache import StateCache, parse_result_envelope
from binascii import hexlify
from nacl.public import Box, PrivateKey, PublicKey
from .crypto import decrypt_nacl, encrypt, sha256
from .enums import (
    ZERO_CHECKSUM,
    ECNetwork,
    ECError,
    ECEvent,
    ECOrderTaskStatus,
    ECStatus,
    ECLog,
    OPERATOR_FAULT_CODES,
    task_status_name,
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
import logging
import random
LAST_BLOCKS = 20
TRUSTEDZONE_VERSION = "v3"


class OperatorFaultError(Exception):
    """A failure attributed to the node operator, not the submitted task.

    Raised when the order times out with no on-chain result, when the
    operator's result is unparseable/unverifiable, or when the task code is in
    the operator-fault range (40-49). Because the DO request cannot be reused
    once an order was placed against it (the contract flips it to BOOKED with
    no reset path), the runner retries by submitting a NEW DO request; the
    escrow of the failed order is refunded by the validator."""


class EthernityCloudRunner:
    def __init__(self, network_name="BLOXBERG", network_type="TESTNET") -> None:
        install_web3_friendly_prefix_filter(suppress_codes=(-32000, -32010))
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.ERROR)  # Default to ERROR; set via set_log_level
        # LOCAL mode: run tasks against the SDK's local test API (`ecld-test
        # serve`) instead of the blockchain. Same runner surface — run(),
        # get_state(), get_result() — no wallet, no gas, no SGX. The endpoint
        # can be overridden with ECLD_LOCAL_ENDPOINT.
        self.local_mode = network_name.upper() == "LOCAL"
        if self.local_mode:
            self.local_endpoint = os.environ.get(
                "ECLD_LOCAL_ENDPOINT", "http://127.0.0.1:8745"
            ).rstrip("/")
            self.network_config = None
        else:
            network_class = getattr(ECNetwork, network_name.upper(), None)
            if network_class is None:
                raise ValueError(f"Invalid network name: {network_name}")

            self.network_config = getattr(network_class, network_type.upper(), None)
            if self.network_config is None:
                raise ValueError(f"Invalid network type: {network_type} for network {network_name}")
        self.private_key: str = ""
        self.signer: Optional[Account] = None
        self.node_address: str = ""
        self.challenge_hash: bytes = b""
        self.do_hash: Optional[str] = None
        self.do_request_id: int = -1
        self.do_request: int = -1
        self.order: Optional[Any] = None
        self.order_id: int = -1
        self.script_hash: str = ""
        self.file_set_hash: str = ""
        self.order_placed_timer: Optional[Any] = None  # Unused? Consider removing
        self.task_has_been_picked_for_approval: bool = False
        self.get_result_from_order_repeats: int = 1
        # Runner-managed ESR state cache. ON BY DEFAULT: esr_read serves
        # unchanged state after a free on-chain check, so repeat reads cost no
        # orders. The default backend is in-memory (no disk writes); call
        # enable_state_cache(file=...) for persistence, or disable_state_cache()
        # to turn it off entirely.
        self.state_cache: Optional[StateCache] = None
        self._state_cache_disabled: bool = False
        # enclave name -> ESR wallet, learned from result envelopes; lets
        # esr_read() resolve the wallet without an explicit argument and
        # self-heal across enclave identity rotation.
        self._esr_wallet_memo: Dict[str, str] = {}
        self.enclave_image_ipfs_hash: str = ""
        self.enclave_public_key: str = ""
        self.enclave_docker_compose_ipfs_hash: str = ""
        self.securelock_enclave: Optional[str] = None
        self.event_queue: Queue = Queue()  # Queue to store events
        self.processed_events: List[str] = []  # List to store processed events
        self.task_thread: Optional[threading.Thread] = None
        self.current_order_index: int = 0
        self.status: ECStatus = ECStatus.RUNNING
        self.progress: ECEvent = ECEvent.INIT
        self.last_error: Optional[str] = None
        self.result: Optional[Any] = None
        self.log_level: ECLog = ECLog.ERROR
        self.running: bool = False
        self.network_name: str = network_name.upper()
        self.network_type: str = network_type.upper()
        self.trustedZoneImage: str = "local" if self.local_mode else self.network_config.TRUSTEDZONE_IMAGE
        self.block_time: int = 1 if self.local_mode else self.network_config.BLOCK_TIME
        self.ipfs_client: Optional[IPFSClient] = None
        self.contract: Optional[protocolContract] = None
        self.protocol_abi: Optional[List] = None
        self.token_contract: Optional[Contract] = None
        self.protocol_contract: Optional[Contract] = None
        self.image_registry_contract: Optional[ImageRegistryContract] = None
        self.resources: Optional[Dict[str, int]] = None
        self.price: int = 0
        self.securelock_version: Optional[str] = None
    def set_network(self, network_name: str, network_type: str) -> None:
        """Set the network configuration."""
        self.network_name = network_name.upper()
        self.network_type = network_type.upper()
        network_class = getattr(ECNetwork, self.network_name, None)
        if network_class is None:
            raise ValueError(f"Invalid network name: {network_name}")
        self.network_config = getattr(network_class, self.network_type, None)
        if self.network_config is None:
            raise ValueError(f"Invalid network type: {network_type} for network {network_name}")
        self.trustedZoneImage = self.network_config.TRUSTEDZONE_IMAGE
    def set_private_key(self, private_key: str) -> None:
        """Set the private key and derive signer."""
        if not private_key.startswith("0x") or len(private_key) != 66:
            raise ValueError("Invalid private key format. Must be 64 hex chars prefixed with 0x.")
        self.private_key = private_key
        self.signer = Account.from_key(private_key)
    def connect(self) -> None:
        """Connect to the protocol contract."""
        if self.local_mode:
            self.logger.info(f"LOCAL mode: no blockchain connection; using {self.local_endpoint}")
            return
        if self.signer is None:
            raise RuntimeError("Private key must be set before connecting.")
        self.contract = protocolContract(
            self.signer, self.network_name, self.network_type, request_kwargs={'timeout': 10}
        )
        self.protocol_abi = polygonAbi.get("abi")
        self.token_contract = self.contract.token_contract
        self.protocol_contract = self.contract.protocol_contract
        provider = self.contract.get_provider()
        if not provider.is_connected():
            raise ConnectionError("Failed to connect to Web3 provider.")
    def set_log_level(self, level: str) -> None:
        """Set the logging level."""
        self.log_level = ECLog[level.upper()]
        self.logger.setLevel(self.log_level.value)  # Assuming ECLog has int values compatible with logging levels
    def is_mainnet(self) -> bool:
        """Check if the current network is mainnet."""
        return self.network_type == "MAINNET"
    def get_enclave_details(self) -> bool:
        """Fetch enclave details from the registry."""
        if not self.is_running():
            self.logger.warning("Runner stopped before fetching enclave details.")
            return False
        if self.image_registry_contract is None:
            raise RuntimeError("Image registry contract not initialized.")
        try:
            details = self.retry_operation(
                lambda: self.image_registry_contract.get_enclave_details_v3(
                    self.securelock_enclave, self.securelock_version, self.trustedZoneImage, TRUSTEDZONE_VERSION
                )
            )
            if not self.is_running():
                self.logger.warning("Runner stopped during enclave details fetch.")
                return False
            if details:
                self.enclave_image_ipfs_hash, self.enclave_public_key, self.enclave_docker_compose_ipfs_hash = details
                self.logger.info(f"ENCLAVE_IMAGE_IPFS_HASH: {self.enclave_image_ipfs_hash}")
                self.logger.debug(f"ENCLAVE_PUBLIC_KEY:\n{self.enclave_public_key}")
                self.logger.info(f"ENCLAVE_DOCKER_COMPOSE_IPFS_HASH: {self.enclave_docker_compose_ipfs_hash}")
                return True
            return False
        except Web3RPCError as e:
            self.logger.error(f"Error fetching enclave details: {raw_rpc_error_message(e)}")
            return False
    def get_reason(self, contract: Contract, tx_hash: str) -> str:
        """Get the revert reason for a failed transaction."""
        try:
            tx = contract.w3.eth.get_transaction(tx_hash)
            if not tx:
                return "Transaction not found"
            # Simulate call to get revert reason
            tx_dict = tx.copy()
            tx_dict.pop('gasPrice', None)  # Use pop to avoid KeyError
            code = contract.w3.eth.call(tx_dict, tx['blockNumber'])
            reason = Web3.to_text(hexstr=code[68:])  # Standard revert data offset
            return reason.strip()
        except Exception as e:
            self.logger.error(f"Error getting transaction reason: {e}")
            return "Unknown error"
    def poll_transaction(self, tx_hash: str, max_attempts: int = 10) -> Optional[Dict]:
        """Poll for transaction receipt with backoff."""
        provider = self.contract.get_provider().eth if self.contract else None
        if not provider:
            raise RuntimeError("No provider available.")
        initial_delay = self.block_time
        current_delay = initial_delay
        backoff_factor = 1.5
        self.logger.info(f"Submitting transaction {tx_hash}")
        for attempt in range(max_attempts):
            if self.is_running():
                try:
                    receipt = provider.get_transaction_receipt(tx_hash)
                    if receipt:
                        return receipt
                except TransactionNotFound:
                    pass
                self.logger.debug(f"Transaction {tx_hash} still processing, check attempt {attempt + 1}/{max_attempts}")
            else:
                self.logger.info("Transaction processing was cancelled")
                return None
            time.sleep(current_delay)
            current_delay = min(current_delay * backoff_factor, 60)  # Max 60s
        self.logger.error(f"Max attempts ({max_attempts}) reached for transaction {tx_hash}.")
        return None
    def wait_for_transaction_to_be_processed(self, contract: Contract, transaction_hash: str, max_attempts: int = 10) -> bool:
        """Wait for transaction to be mined and check status."""
        receipt = self.poll_transaction(transaction_hash, max_attempts)
        if receipt and receipt['status'] == 1:
            return True
        if receipt and receipt['status'] == 0:
            reason = self.get_reason(contract, transaction_hash)
            self.logger.error(f"Transaction failed: {reason}")
        return False
    def check_web3_connection(self) -> bool:
        """Check if Web3 is connected and wallet is set."""
        try:
            provider = self.contract.get_provider() if self.contract else None
            if not provider or not provider.is_connected():
                return False
            wallet_address = self.contract.get_current_wallet()
            return bool(wallet_address)
        except Web3RPCError as e:
            self.logger.error(f"Web3 connection check failed: {raw_rpc_error_message(e)}")
            return False
    def hex_to_bytes(self, hex_str: str) -> bytes:
        """Convert hex string to bytes."""
        return bytes.fromhex(hex_str[2:] if hex_str.startswith("0x") else hex_str)
    def bytes_to_hex(self, bytes_str: bytes) -> str:
        """Convert bytes to hex string."""
        return "0x" + hexlify(bytes_str).decode("utf-8")
    def get_current_wallet_public_key(self) -> HexStr:
        """Get public key from private key."""
        priv_key = PrivateKey.from_seed(self.hex_to_bytes(self.private_key)).public_key._public_key
        return self.bytes_to_hex(priv_key)
    def get_v3_image_metadata(self, challenge_hash: bytes) -> str:
        """Generate v3 image metadata."""
        if not self.ipfs_client:
            raise RuntimeError("IPFS client not initialized.")
        base64_encrypted_challenge = encrypt(challenge_hash, self.enclave_public_key)
        challenge_ipfs_hash = self.ipfs_client.upload_to_ipfs(base64_encrypted_challenge)
        if challenge_ipfs_hash is None:
            raise ValueError("Failed to upload challenge to IPFS.")
        self.logger.info(f"Uploaded challenge to IPFS: {challenge_ipfs_hash}")
        public_key = self.get_current_wallet_public_key()
        return f"{TRUSTEDZONE_VERSION}:{self.enclave_image_ipfs_hash}:{self.securelock_enclave if not self.trustedZoneImage else self.trustedZoneImage}:{self.enclave_docker_compose_ipfs_hash}:{challenge_ipfs_hash}:{public_key}"
    def get_v3_code_metadata(self, code: str) -> str:
        """Generate v3 code metadata."""
        if not self.ipfs_client:
            raise RuntimeError("IPFS client not initialized.")
        # as_hex=True is REQUIRED: sha256()'s default returns bytes, and
        # f-string interpolation of bytes writes the literal "b'...'" repr into
        # the on-chain metadata. The enclave then compares its computed hex
        # against that repr and every payload fails with
        # PAYLOAD_CHECKSUM_ERROR (orders 1817-1819 on bloxberg testnet).
        script_checksum = sha256(code, True)
        base64_encrypted_script = encrypt(code.encode("utf-8"), self.enclave_public_key)
        self.script_hash = self.ipfs_client.upload_to_ipfs(base64_encrypted_script)
        if self.script_hash is None:
            raise ValueError("Failed to upload encrypted code to IPFS.")
        self.logger.info(f"Uploaded encrypted code to IPFS: {self.script_hash}")
        # v4 request: emit the plain sha256 checksum (not a signature). The
        # DO-request is authenticated on-chain by the owner (tx sender), so the
        # enclave only needs the plain checksum to verify the payload content.
        # Refuse to submit anything that is not a plain 64-char hex digest --
        # a malformed checksum burns the client's gas on a task that can only
        # be rejected by the enclave.
        if not re.fullmatch(r"[0-9a-f]{64}", script_checksum):
            raise ValueError(
                f"payload checksum is not a plain sha256 hex digest: {script_checksum!r}"
            )
        return f"{TRUSTEDZONE_VERSION}:{self.script_hash}:{script_checksum}"
    def get_v3_input_metadata(self) -> str:
        """Generate v3 input metadata."""
        # v4 request: emit the plain ZERO_CHECKSUM for empty input (not a
        # signature). Matches the JS runner and the v4-only enclave validation.
        return f"{TRUSTEDZONE_VERSION}::{ZERO_CHECKSUM}"
    def create_do_request(self, image_metadata: str, code_metadata: str, input_metadata: str, node_address: Address) -> bool:
        """Create a DO request on the contract."""
        if not self.contract:
            raise RuntimeError("Contract not initialized.")
        self.logger.info("Submitting transaction for DO request")
        if node_address:
            node_address = Web3.to_checksum_address(node_address)
        else:
            node_address = '0x0000000000000000000000000000000000000000'
        def send_tx():
            return self.contract.add_do_request(image_metadata, code_metadata, input_metadata, node_address, self.resources)
        transaction_hash = self.retry_operation(send_tx, max_retries=50, backoff_factor=2)
        if not transaction_hash:
            return False
        self.do_hash = transaction_hash
        is_processed = self.wait_for_transaction_to_be_processed(self.contract, transaction_hash, max_attempts=100)
        if not is_processed:
            reason = self.get_reason(self.protocol_contract, transaction_hash)
            self.logger.error(f"Unable to create DO request: {reason}")
            return False
        receipt = self.contract.get_provider().eth.get_transaction_receipt(transaction_hash)
        # errors=DISCARD: a DO-request receipt carries other logs (ERC-20
        # Transfer, other protocol events) besides _addDORequestEV. web3's
        # default (WARN) prints a MismatchedABI warning for every non-matching
        # log while still returning the one we want -- pure noise. DISCARD drops
        # ONLY the non-matching logs; the _addDORequestEV event we depend on is
        # decoded identically. It never hides a failed tx (that is caught above
        # by is_processed) nor a missing event (handled explicitly below).
        processed_logs = self.protocol_contract.events._addDORequestEV().process_receipt(receipt, errors=DISCARD)
        if not processed_logs:
            # The tx succeeded but the receipt carries no _addDORequestEV event
            # -- we cannot know the DO request row number, so DO NOT proceed with
            # a wrong/unknown value. Fail cleanly instead of crashing or guessing.
            self.logger.error(
                f"DO request tx {transaction_hash} confirmed but emitted no "
                f"_addDORequestEV event; refusing to proceed without the request id.")
            return False
        self.do_request = processed_logs[0].args._rowNumber
        self.logger.info(f"{transaction_hash} confirmed!")
        self.logger.info(f"Request {self.do_request} was created successfully!")
        return True
    def parse_order_result(self, result: str) -> Dict[str, Any]:
        """Parse order result string."""
        try:
            arr = result.split(":")
            t_bytes = arr[1] if arr[1].startswith("0x") else f"0x{arr[1]}"
            return {
                "version": arr[0],
                "transaction_bytes": t_bytes,
                "result_ipfs_hash": arr[2],
            }
        except IndexError as e:
            raise ValueError(ECError.PARSE_ERROR.value) from e
    def parse_transaction_bytes(self, bytes_str: bytes) -> Dict[str, str]:
        """Parse transaction bytes."""
        try:
            result = parse_transaction_bytes_ut(self.protocol_abi, bytes_str)
            arr = result["result"].split(":")
            task_code_int = int(arr[1])
            return {
                "version": arr[0],
                "from": result["from"],
                "task_code": arr[1],
                "task_code_int": task_code_int,
                "task_code_string": task_status_name(task_code_int),
                "checksum": arr[2],
                "enclave_challenge": arr[3],
            }
        except (IndexError, ValueError) as e:
            raise ValueError(ECError.PARSE_ERROR.value) from e
    def _apply_envelope(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Decode the structured result envelope (legacy strings pass through).

        Keeps `value` as the legacy STRING view so string-treating dApps work
        against both old and new enclaves, and adds the typed accessors:
        result_type / result_data / result_esr / result_raw. When the state
        cache is enabled, every envelope's esr entries refresh it."""
        parsed = parse_result_envelope(result.get("value"))
        result["value"] = parsed["legacy"]
        result["result_type"] = parsed["type"]
        result["result_data"] = parsed["data"]
        result["result_esr"] = parsed["esr"]
        result["result_raw"] = parsed["raw"]
        esr = parsed["esr"]
        if isinstance(esr, dict) and esr.get("wallet"):
            wallet = esr["wallet"]
            if self.securelock_enclave:
                self._esr_wallet_memo[self.securelock_enclave] = wallet
            cache = self._get_state_cache()
            if cache is not None:
                for entry in esr.get("entries") or []:
                    try:
                        if "state" in entry:
                            cache.set(
                                wallet, entry["key"], entry.get("state"),
                                entry.get("version", 0), entry.get("cid"))
                    except Exception:
                        continue
        return result

    def get_result_from_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get and verify result from order.

        On failure this returns None and, when the failure is attributable to
        the node operator (timeout, unusable output, operator-fault task code),
        records the reason in self._fault so the caller can retry with a new
        DO request."""
        decrypted_data: Dict[str, Any] = {}
        max_retries = 10
        self._fault = None
        self.logger.info(f"Operator {self.order[1]} is processing task {order_id}")
        # An honest node holds an order at most its duration plus the node
        # agent's own result wait (~62 min); past that the operator is hung or
        # offline and the order will never leave PROCESSING on its own.
        duration_hours = (getattr(self, "resources", None) or {}).get("duration", 1)
        deadline = time.time() + duration_hours * 3600 + 900
        status = self.contract.get_status_from_order(order_id)
        while self.is_running() and status != 2:
            if time.time() > deadline:
                self._fault = (
                    f"order {order_id} was not completed within its duration "
                    f"(operator hung or offline)"
                )
                self.logger.error(self._fault)
                return None
            time.sleep(self.block_time)
            status = self.contract.get_status_from_order(order_id)
        if not self.is_running():
            self.logger.info(f"Task {order_id} was cancelled")
            return None
        self.logger.info(f"Task {order_id} was successfully processed.")
        order_result = self.retry_operation(lambda: self.contract.get_result_from_order(order_id), max_retries)
        try:
            parsed_order_result = self.parse_order_result(order_result)
            self.logger.info(f"Checking result hash: {parsed_order_result['result_ipfs_hash']}")
            transaction_result = self.parse_transaction_bytes(self.hex_to_bytes(parsed_order_result["transaction_bytes"]))
        except ValueError as e:
            self.logger.error(f"Error parsing: {e}")
            self.logger.error("Could not parse. The operator result is invalid, indicating a failure")
            self.logger.error("Tokens will be refunded after validation. Please try again.")
            self._fault = f"order {order_id}: operator result could not be parsed"
            return None
        task_code_int = transaction_result.get("task_code_int")
        if task_code_int in OPERATOR_FAULT_CODES:
            self._fault = (
                f"order {order_id} failed on the operator side: "
                f"{transaction_result['task_code_string']} ({task_code_int})"
            )
            self.logger.error(self._fault)
            self.logger.error("Tokens will be refunded after validation.")
            return None
        self.logger.info("Verifying ZK proof")
        if self.challenge_hash:
            wallet = generate_wallet(self.challenge_hash.decode("utf-8"), transaction_result["enclave_challenge"])
            if not wallet or wallet != transaction_result["from"]:
                self.logger.error("Integrity check failed, signer wallet address is wrong")
                self.logger.error("Tokens will be refunded after validation. Please try again.")
                self._fault = f"order {order_id}: result signer verification failed"
                return None
            self.logger.info("Verification successful!")
        self.logger.info(f"The result is signed by: {transaction_result['from']}")
        ipfs_result = self.retry_operation(
            lambda: self.ipfs_client.get_file_content(parsed_order_result['result_ipfs_hash']) if self.ipfs_client else None,
            max_retries
        )
        if ipfs_result is None:
            self.logger.error("Failed to download IPFS result after retries.")
            self._fault = f"order {order_id}: result could not be downloaded from IPFS"
            return None
        self.logger.info("Decrypting result")
        decrypted_data = decrypt_nacl(self.private_key, ipfs_result)
        if not decrypted_data["success"]:
            # Not marked as an operator fault: the most common cause is a wrong
            # client key, and auto-resubmitting would spend gas on every attempt
            # without changing the outcome.
            self.logger.error("Could not decrypt the task result.")
            return None
        self.logger.debug(f"Result value: {decrypted_data['data']}")
        ipfs_result_checksum = sha256(decrypted_data["data"], True)
        if ipfs_result_checksum != transaction_result["checksum"]:
            self.logger.error(f"Integrity check failed: {ipfs_result_checksum} != {transaction_result['checksum']}")
            self._fault = f"order {order_id}: result checksum verification failed"
            return None
        return self._apply_envelope({
            "success": True,
            "contract_address": self.contract.get_protocol_address(),
            "input_transaction_hash": self.do_hash,
            "output_transaction_hash": "",
            "order_id": order_id,
            "image_hash": f"{self.enclave_image_ipfs_hash}:{self.securelock_enclave}",
            "script_hash": self.script_hash,
            "file_set_hash": self.file_set_hash,
            "public_timestamp": 0,
            "result_hash": parsed_order_result["result_ipfs_hash"],
            "result_task_code": transaction_result["task_code_string"],
            "result_task_code_int": transaction_result["task_code_int"],
            "result_value": ipfs_result,
            "result_timestamp": 0,
            "value": decrypted_data["data"],
        })
    def create_task(self, code: str) -> bool:
        """Create a new task."""
        do_sent_successfully = False
        self.challenge_hash = generate_random_hex_of_size(20).encode("utf-8")
        image_metadata = self.get_v3_image_metadata(self.challenge_hash)
        code_metadata = self.get_v3_code_metadata(code)
        input_metadata = self.get_v3_input_metadata()
        self.current_order_index = self.protocol_contract.functions._getOrdersCount().call()
        do_sent_successfully = self.create_do_request(
            image_metadata, code_metadata, input_metadata, self.node_address
        )
        return do_sent_successfully
    def attach_task(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Attach to an existing task."""
        self.order_id = order_id
        self.order = self.protocol_contract.caller()._getOrder(self.order_id)
        self.do_request = self.order[2]  # Assuming request_id is at index 2
        result = self.get_result_from_order(self.order_id)
        return result if result else None
    def check_order_for_task(self) -> bool:
        """Check for order creation with backoff."""
        self.logger.info("Waiting for Ethernity CLOUD network...")
        initial_delay = self.block_time
        max_delay = 600
        backoff_factor = 2
        current_delay = initial_delay
        retry_count = 0
        while self.is_running():
            try:
                if self.find_order(self.do_request):
                    self.logger.info("Connected!")
                    return True
                retry_count = 0
                current_delay = initial_delay
                time.sleep(self.block_time)
            except Web3RPCError as e:
                error_code = e.code if hasattr(e, 'code') else 'Unknown'
                error_msg = raw_rpc_error_message(e) if hasattr(e, 'message') else str(e)
                self.logger.error(f"Web3RPCError: Code {error_code} - {error_msg}. Retrying after {current_delay} seconds...")
                time.sleep(current_delay)
                retry_count += 1
                current_delay = min(initial_delay * (backoff_factor ** retry_count), max_delay)
            except Exception as e:
                self.logger.error(f"Unexpected error: {type(e).__name__}: {str(e)}. Retrying after {current_delay} seconds...")
                time.sleep(current_delay)
                retry_count += 1
                current_delay = min(initial_delay * (backoff_factor ** retry_count), max_delay)
        return False
    def approve_task(self) -> bool:
        """Approve the task."""
        self.logger.info(f"Approving task {self.order_id}...")
        max_attempts = 100
        retry_count = 0
        while self.is_running() and retry_count < max_attempts:
            try:
                if self.approve_order():
                    return True
            except Web3RPCError as e:
                self.logger.error(f"Approval failed: {raw_rpc_error_message(e)}")
            time.sleep(self.block_time)
            retry_count += 1
        self.logger.error(f"Max attempts ({max_attempts}) reached for task approval.")
        return False
    def process_task(self) -> Optional[Dict[str, Any]]:
        """Process the task and get result."""
        result = self.get_result_from_order(self.order_id)
        return result if result else None
    def find_order(self, doreq: int) -> bool:
        """Find the order by request ID."""
        count = self.protocol_contract.functions._getOrdersCount().call()
        for i in range(count - 1, self.current_order_index - 1, -1):
            order = self.protocol_contract.caller()._getOrder(i)
            if order[2] == doreq:
                self.order = order
                self.order_id = i
                return True
        return False
    def approve_order(self) -> bool:
        """Approve the order."""
        if self.node_address != "":
            self.logger.info(f"Transaction is delegated to {self.node_address}, skipping approval")
            return True

        def send_tx():
            return self.contract.approve_order(self.order_id)

        transaction_hash = self.retry_operation(send_tx, max_retries=50, backoff_factor=2)
        receipt = self.wait_for_transaction_to_be_processed(self.contract, transaction_hash, max_attempts=100)
        if receipt and receipt['status'] == 1:
            self.node_address = self.contract.get_order(self.order_id)[1]
            self.logger.info(f"{transaction_hash} confirmed!")
            self.logger.info(f"Task {self.order_id} approved successfully!")
            return True
        self.logger.error(f"Approval failed for transaction {transaction_hash}.")
        return False
    def reset(self) -> None:
        """Reset state variables."""
        self.order = None
        self.order_id = -1
        self.do_hash = None
        self.do_request_id = -1
        self.do_request = -1
        self.script_hash = ""
        self.file_set_hash = ""
        self.get_result_from_order_repeats = 1
        self.task_has_been_picked_for_approval = False
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.reset()
    def is_node_operator_address(self, node_address: str) -> bool:
        """Check if address is a node operator."""
        if is_null_or_empty(node_address):
            return True
        if not is_address(node_address):
            self.logger.error("Introduced address is not a valid wallet address.")
            return False
        is_node = self.contract.is_node_operator(node_address)
        if not is_node:
            self.logger.error("The target address is not a valid node operator address")
        return is_node
    def set_storage_ipfs(self, ipfs_address: str, token: str = "") -> None:
        """Set IPFS client."""
        self.ipfs_client = IPFSClient(ipfs_address, token)
    def retry_operation(self, func: callable, max_retries: int = 10, delay: Optional[int] = None, backoff_factor: float = 1.5) -> Any:
        """Retry a function with exponential backoff."""
        delay = delay or self.block_time
        current_delay = delay
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                self.logger.warning(f"Retry {attempt + 1}/{max_retries}: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(current_delay)
                current_delay = min(current_delay * backoff_factor, 60)
        raise RuntimeError("Max retries exceeded")
    def run(
        self,
        resources: Optional[Dict[str, int]],
        securelock_enclave: str,
        securelock_version: str,
        code: str,
        node_address: str = "",
        trustedzone_enclave: str = "etny-pynithy-testnet",
        max_retries: int = 2,
        retry_delay: int = 30,
    ) -> None:
        """Run the task.

        max_retries: how many times to resubmit the task as a NEW DO request
        when it fails on the operator side (order timeout, unusable operator
        output, or an operator-fault task code 40-49). Failures caused by the
        submitted code itself are final results and are never retried.
        retry_delay: seconds to wait between resubmissions."""
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._fault = None
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
        self.result = None
        self.running = True
        self.processed_events = []
        self._populate_event_queue()
        self.task_thread = threading.Thread(
            target=self._process_events,
            args=(securelock_enclave, securelock_version, code, node_address, resources),
            daemon=True
        )
        self.task_thread.start()
    def _populate_event_queue(self) -> None:
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
    def _process_events(self, securelock_enclave: str, securelock_version: str, code: str, node_address: str, resources: Dict[str, int]) -> None:
        """Process events, resubmitting on operator-side failures."""
        attempt = 0
        try:
            while True:
                try:
                    self._run_attempt(securelock_enclave, securelock_version, code, node_address, resources)
                    return
                except OperatorFaultError as e:
                    attempt += 1
                    if attempt > getattr(self, "max_retries", 2):
                        self.progress = ECEvent.FINISHED
                        self.status = ECStatus.ERROR
                        self.last_error = f"Failed on the operator side after {attempt} attempt(s): {e}"
                        self.logger.error(self.last_error)
                        return
                    delay = getattr(self, "retry_delay", 30)
                    self.logger.warning(
                        f"Operator-side failure: {e}. Resubmitting as a new request "
                        f"(retry {attempt}/{getattr(self, 'max_retries', 2)}) in {delay}s..."
                    )
                    time.sleep(delay)
                    with self.event_queue.mutex:
                        self.event_queue.queue.clear()
                    self._populate_event_queue()
                except Exception as e:
                    self.progress = ECEvent.FINISHED
                    self.status = ECStatus.ERROR
                    self.last_error = str(e)
                    self.logger.error(f"Error: {self.last_error}")
                    return
        finally:
            self.running = False

    def _run_local_attempt(self, code: str) -> None:
        """LOCAL mode: run the task against the ecld-test API, no blockchain.

        Walks the same event queue so get_state() reports the same progress
        shape as a real run; the result dict mirrors get_result_from_order's."""
        import json
        import urllib.request

        while not self.event_queue.empty() and self.is_running():
            event = self.event_queue.get()
            if event == ECEvent.INIT:
                self.progress = ECEvent.INIT
                try:
                    with urllib.request.urlopen(self.local_endpoint + "/v1/health", timeout=5) as r:
                        info = json.loads(r.read())
                except Exception as e:
                    raise ConnectionError(
                        f"Local test API not reachable at {self.local_endpoint} — "
                        f"start it with 'ecld-test serve' in your project. ({e})"
                    )
                self.logger.info(f"LOCAL mode: backend functions {info.get('backend')}")
            elif event in (ECEvent.CREATED, ECEvent.ORDER_PLACED):
                self.progress = event  # no chain interaction locally
            elif event == ECEvent.IN_PROGRESS:
                self.progress = event
                body = json.dumps({"payload": code}).encode("utf-8")
                req = urllib.request.Request(
                    self.local_endpoint + "/v1/task", data=body,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=600) as r:
                    resp = json.loads(r.read())
                self.result = self._apply_envelope({
                    "success": resp["task_code"] == 0,
                    "contract_address": "LOCAL",
                    "input_transaction_hash": None,
                    "output_transaction_hash": None,
                    "order_id": -1,
                    "image_hash": "local",
                    "script_hash": "",
                    "file_set_hash": "",
                    "public_timestamp": 0,
                    "result_hash": resp["checksum"],
                    "result_task_code": resp["task_code_name"],
                    "result_task_code_int": resp["task_code"],
                    "result_value": resp["result"],
                    "result_timestamp": 0,
                    "value": resp["result"],
                })
            elif event == ECEvent.FINISHED:
                self.progress = ECEvent.FINISHED
                self.status = ECStatus.SUCCESS
                self.logger.info("Task completed (LOCAL mode).")
            self.processed_events.append(event.name)

    def _run_attempt(self, securelock_enclave: str, securelock_version: str, code: str, node_address: str, resources: Dict[str, int]) -> None:
        """One full submission attempt: INIT through FINISHED."""
        if self.local_mode:
            return self._run_local_attempt(code)
        while not self.event_queue.empty() and self.is_running():
            event = self.event_queue.get()
            if event == ECEvent.INIT:
                self.progress = ECEvent.INIT
                self.logger.info("Checking wallet balance...")
                balance = int(self.contract.get_balance())
                if balance < self.price:
                    if self.network_type != "MAINNET":
                        self.logger.info("Insufficient wallet balance, using testnet faucet...")
                        self.contract.faucet()
                    else:
                        raise ValueError(f"Insufficient wallet balance. Required: {self.price}, Available: {balance}")
                self.logger.info("Verifying node address...")
                self.node_address = node_address
                if not self.is_node_operator_address(node_address):
                    raise ValueError("Node address verification failed.")
                self.securelock_enclave = securelock_enclave
                self.securelock_version = securelock_version
                self.cleanup()
                image_to_check = self.securelock_enclave if not self.trustedZoneImage else self.trustedZoneImage
                self.logger.info(f"Checking image {image_to_check} in registry...")
                self.image_registry_contract = ImageRegistryContract(self.network_name, self.network_type, self.signer)
                if not self.check_web3_connection():
                    raise ConnectionError("Web3 connection failed.")
                if not self.get_enclave_details():
                    raise ValueError("Unable to find enclave in registry")
                if self.network_name != "BLOXBERG":
                    self.logger.info("Checking allowance on the current wallet...")
                    allowance = self.token_contract.functions.allowance(self.signer.address, self.contract.get_protocol_address()).call()
                    if allowance < self.price:
                        self.logger.info(f"Approving allowance for {self.price} {self.network_config.TOKEN_NAME}")
                        transaction_hash = self.contract.set_allowance(self.price)
                        receipt = self.poll_transaction(transaction_hash, max_attempts=100)
                        if not receipt or receipt['status'] != 1:
                            raise ValueError("Allowance approval failed.")
                        self.logger.info("Allowance approved")
                    self.logger.info("Allowance check completed.")
                if not self.create_task(code):
                    raise ValueError("Unable to create a DO request")
            elif event == ECEvent.CREATED:
                self.progress = event
                if not self.check_order_for_task():
                    raise ValueError("Could not find any available operator matching this task request.")
            elif event == ECEvent.ORDER_PLACED:
                self.progress = event
                if not self.approve_task():
                    raise ValueError("Task approval failed.")
            elif event == ECEvent.IN_PROGRESS:
                self.progress = event
                result = self.process_task()
                if not result:
                    fault = getattr(self, "_fault", None)
                    if fault:
                        raise OperatorFaultError(fault)
                    raise ValueError("Task processing failed.")
                self.result = result
            elif event == ECEvent.FINISHED:
                self.progress = ECEvent.FINISHED
                self.status = ECStatus.SUCCESS
                self.logger.info("Task completed successfully.")
            self.processed_events.append(event.name)
    def get_state(self) -> Dict[str, Any]:
        """Retrieve the current task status."""
        remaining_events = list(self.event_queue.queue)
        return {
            "status": self.status.name,
            "progress": self.progress.name,
            "last_error": self.last_error,
            "result": self.result,
            "processed_events": self.processed_events,
            "remaining_events": [e.name for e in remaining_events],
        }
    def is_running(self) -> bool:
        """Check if a task is currently running."""
        return self.running
    def get_result(self) -> Optional[Any]:
        """Retrieve the result of the task."""
        return self.result

    def _get_state_cache(self) -> Optional["StateCache"]:
        """The active state cache, creating the default (in-memory) one on first
        use. The cache is ON BY DEFAULT; returns None only after
        disable_state_cache()."""
        if self._state_cache_disabled:
            return None
        if self.state_cache is None:
            self.state_cache = StateCache()   # in-memory; no disk writes
        return self.state_cache

    def enable_state_cache(self, backend=None, file=None) -> "StateCache":
        """Configure the ESR state cache (it is already ON BY DEFAULT).

        Use this only to choose a backend or add persistence: `backend` is any
        dict-like store; `file` persists the cache as JSON across restarts.
        Every task result carrying an ESR attachment refreshes the cache, and
        esr_read() serves unchanged state from it after a free on-chain check
        -- zero orders, zero gas."""
        self._state_cache_disabled = False
        self.state_cache = StateCache(backend=backend, file=file)
        return self.state_cache

    def disable_state_cache(self) -> None:
        """Turn the ESR state cache OFF -- esr_read then always runs a task."""
        self._state_cache_disabled = True
        self.state_cache = None

    def esr_read(
        self,
        key: str,
        enclave_wallet: Optional[str] = None,
        read_code: Optional[str] = None,
        force: bool = False,
        trust_min_version: Optional[int] = None,
        securelock_enclave: Optional[str] = None,
        securelock_version: Optional[str] = None,
        node_address: str = "",
        resources: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Cache-gated ESR read.

        Serves the state from the cache while a FREE on-chain check
        (`getState` eth_call) confirms it is current; otherwise submits one
        state-fetch task (the SDK's built-in `esr_fetch`, or `read_code` if
        given) and refreshes the cache from its result envelope.

        Wallet resolution: explicit `enclave_wallet`, else the wallet learned
        from previous result envelopes for this enclave (self-healing across
        enclave identity rotation).

        Returns {state, version, cid, wallet, from_cache, checked_on_chain}.
        """
        enclave_name = securelock_enclave or self.securelock_enclave
        wallet = enclave_wallet or self._esr_wallet_memo.get(enclave_name or "")

        checked_on_chain = False
        cache = self._get_state_cache()
        if (not force) and cache is not None and wallet:
            entry = cache.get(wallet, key)
            if entry is not None:
                try:
                    from .contract.abi.esrAbi import contract as _esr_abi
                    _registry = (
                        _esr_abi.get(f"address_{self.network_name.lower()}_{self.network_type.lower()}")
                        or _esr_abi.get(f"address_{self.network_name.lower()}")
                    )
                    esr = ESRContract(
                        self.network_name, self.network_type,
                        registry_address=_registry,
                    )
                    onchain = esr.get_state(wallet, key)
                    checked_on_chain = True
                    fresh = False
                    # Prefer cid equality (content-addressed); fall back to
                    # version. trust_min_version covers the caller's own
                    # still-relaying commit: external writes only increase the
                    # version, so they still invalidate.
                    if entry.get("cid") and onchain.get("cid"):
                        fresh = entry["cid"] == onchain["cid"]
                    if not fresh:
                        fresh = int(onchain.get("version", -1)) == int(entry.get("version", -2))
                    if not fresh and trust_min_version is not None:
                        fresh = int(onchain.get("version", 0)) <= int(trust_min_version)
                    if fresh:
                        return {
                            "state": entry.get("state"),
                            "version": entry.get("version"),
                            "cid": entry.get("cid"),
                            "wallet": wallet,
                            "from_cache": True,
                            "checked_on_chain": True,
                        }
                except Exception as e:
                    # Fail safe: never serve a maybe-stale cache on an errored
                    # check -- fall through and run the read task.
                    self.logger.debug(f"esr_read free check failed ({e}); running task")
                    checked_on_chain = False

        # Miss / stale / forced: run one state-fetch task and cache its result.
        code = read_code or f"esr_fetch('{key}')"
        if enclave_name is None or securelock_version is None and self.securelock_version is None:
            if enclave_name is None:
                raise ValueError(
                    "esr_read needs securelock_enclave (no previous run to inherit from)")
        version = securelock_version or self.securelock_version
        self.run(
            resources or getattr(self, "resources", None),
            enclave_name,
            version,
            code,
            node_address=node_address or (self.node_address or ""),
        )
        result = self.get_result()
        if not result or not result.get("success"):
            raise RuntimeError(f"esr_read task failed for key '{key}'")
        esr_att = result.get("result_esr") or {}
        wallet = esr_att.get("wallet") or wallet
        entry = None
        for e in esr_att.get("entries") or []:
            if e.get("key") == key:
                entry = e
                break
        if entry is None:
            raise RuntimeError(
                f"esr_read: result carried no state for key '{key}' "
                f"(is the enclave built with ESR and the new result API?)")
        return {
            "state": entry.get("state"),
            "version": entry.get("version"),
            "cid": entry.get("cid"),
            "wallet": wallet,
            "from_cache": False,
            "checked_on_chain": checked_on_chain,
        }
    def close(self) -> None:
        """Close resources and stop the runner."""
        self.running = False
        if self.ipfs_client:
            try:
                self.ipfs_client.close()
                self.logger.debug("Closed IPFS client")
            except Exception:
                pass
            self.ipfs_client = None
        for attr in ['contract', 'image_registry_contract']:
            obj = getattr(self, attr, None)
            if obj:
                try:
                    provider = obj.get_provider()
                    if hasattr(provider, 'http') and provider.http:
                        provider.http.close()
                    if hasattr(provider, 'ws') and provider.ws:
                        provider.ws.close()
                except Exception:
                    pass
        if self.task_thread and self.task_thread.is_alive():
            self.logger.info("Stopping task thread...")
            self.task_thread.join(timeout=self.block_time * 2)
            if self.task_thread.is_alive():
                self.logger.error("Task thread did not terminate; potential stuck loop.")
                self.status = ECStatus.ERROR
        while not self.event_queue.empty():
            self.event_queue.get_nowait()
        self.event_queue = Queue()
        self.reset()
        self.processed_events = []
        self.result = None
        self.task_thread = None
        self.contract = None
        self.token_contract = None
        self.protocol_contract = None
        self.image_registry_contract = None
        self.signer = None
        self.private_key = ""
        self.status = ECStatus.SUCCESS
        self.logger.info("Runner resources closed successfully")