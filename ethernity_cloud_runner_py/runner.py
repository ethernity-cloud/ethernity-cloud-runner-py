import os
import re
import time
import threading
import weakref
from contextlib import contextmanager
from queue import Empty, Queue
from typing import Union, List, Optional, Dict, Any, Literal
from datetime import datetime
import requests
from eth_account import Account
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import TimeExhausted, TransactionNotFound, Web3RPCError
from web3.logs import DISCARD
from .errors import (install_web3_friendly_prefix_filter, raw_rpc_error_message, provider_message, FeeCeilingError,
                     RunEndedError)
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
    UNSAFE_NETWORK_SUFFIX,
    UNSAFE_TRUSTEDZONE_SUFFIX,
    task_status_name,
    trustedzone_network,
)
import hashlib

from .ipfs import IPFSClient, INTAKE_NETWORKS, PUBLIC_INTAKE, StorageLimitError
from .utils import (
    format_date,
    generate_random_hex_of_size,
    is_address,
    is_null_or_empty,
    normalize_node_address,
    parse_transaction_bytes_ut,
    generate_wallet,
)
import logging
import random
LAST_BLOCKS = 20
TRUSTEDZONE_VERSION = "v3"
# How long check_order_for_task waits for a node to place an order on the DO
# request before cancel_unclaimed_request cancels it; set_order_wait changes it.
# A mainnet node defers a request by up to (registered nodes / 25) blocks to
# spread orders.
DEFAULT_ORDER_WAIT_SECONDS = 1800
# How often the chain is read while a transaction's receipt, the order a node
# places on the request, the order's close and the result blob are waited for:
# each is then seen within seconds of its block, and a wait costs the block
# time and nothing more. The reads are cheap (eth_getTransactionReceipt,
# eth_blockNumber and eth_getLogs over the blocks since the request in ranges
# of at most GET_LOGS_MAX_BLOCKS, one struct read).
CHAIN_POLL_SECONDS = 5
# The widest block range one eth_getLogs call asks for. The LitVM LiteForge
# RPC hosted by Zeeve (rpc.testnet.liteforge.zeeve.net) refuses a wider one:
# "eth_getLogs range exceeds 3000 blocks; split the range".
GET_LOGS_MAX_BLOCKS = 3000
# Blocks kept free below the limit by the scan's last range, whose toBlock is
# "latest": the head advances between the eth_blockNumber read that sized the
# ranges and the eth_getLogs call (LiteForge mines about one block a second).
GET_LOGS_TAIL_SLACK = 100
# How many times a read a DO request depends on (the wallet's token balance,
# the PoX's order count, the wallet's allowance for the protocol) is tried,
# and the seconds between the tries, before the read's failure fails the
# request (_read_before_request): one RPC request the provider drops does not
# refuse a request the chain would accept.
PRE_REQUEST_READ_ATTEMPTS = 3
PRE_REQUEST_READ_RETRY_SECONDS = 2
# How long connect(), run(), run_session(), attach_session(), set_network()
# and set_private_key() wait for a run that close() ended while its thread
# was at work (in a request to the RPC or the storage, or in a wait between
# two), before they raise RuntimeError (_await_closed_run). It is above one
# RPC request at its longest (rpc.RPC_REQUEST_MAX_SECONDS, 20 s) followed by
# one poll interval (CHAIN_POLL_SECONDS).
RUN_END_WAIT_SECONDS = 30
# The message of the RuntimeError of connect(), run(), run_session(),
# attach_session(), set_network() and set_private_key() when close() was
# called while the call waited for the runner: the call does nothing.
CLOSED_WHILE_WAITING = ("The runner was closed with close() while {call} waited for it: {call} did nothing. A closed "
                        "runner takes a key with set_private_key() and connect() again; another "
                        "EthernityCloudRunner serves meanwhile.")
# The message of the errors.RunEndedError raised in the thread of a run or of
# a session submission once close() has ended it: for a transaction it would
# send (_sender) and for the handle it would return (_hold_session).
RUN_ENDED = ("The runner was closed with close() while this run or session submission was in progress: it has "
             "ended, and nothing more of it is sent.")


def log_scan_ranges(from_block: int, head: int) -> list:
    """The (fromBlock, toBlock) pairs an eth_getLogs scan from `from_block`
    to the chain head `head` is split into: ranges of at most
    GET_LOGS_MAX_BLOCKS blocks, none past `head`, while more than
    GET_LOGS_MAX_BLOCKS - GET_LOGS_TAIL_SLACK blocks remain, then the rest,
    whose toBlock is "latest" so that the replica serving the call bounds it
    at its own head. A head below `from_block` (read from a replica behind the
    one the request was anchored on) gives the one open range."""
    ranges = []
    start = from_block
    while head - start + 1 > GET_LOGS_MAX_BLOCKS - GET_LOGS_TAIL_SLACK:
        end = min(start + GET_LOGS_MAX_BLOCKS - 1, head)
        ranges.append((start, end))
        start = end + 1
    ranges.append((start, "latest"))
    return ranges


class OperatorFaultError(Exception):
    """A failure attributed to the node operator, not the submitted task.

    Raised when the order times out with no on-chain result, when the
    operator's result is unparseable/unverifiable, or when the task code is an
    operator fault (OPERATOR_FAULT_CODES). Because the DO request cannot be reused
    once an order was placed against it (the contract flips it to BOOKED with
    no reset path), the runner retries by submitting a NEW DO request; the
    escrow of the failed order is refunded by the validator."""


# A node whose DP request advertises DP_STARTED_ROW_CAPABILITY in its metadata4
# adds an ORDER_STARTED_KEY row, 'v1:<order>:<block>', to that DP request when
# it begins running an order. An order of such a node with no row
# ORDER_START_WINDOW_BLOCKS blocks after it entered processing is treated as
# abandoned by its node (an operator fault) and resubmitted.
ORDER_STARTED_KEY = "etny-st"
ORDER_START_WINDOW_BLOCKS = 10
DP_STARTED_ROW_CAPABILITY = "startrow=v1"


def started_row_advertised(metadata4) -> bool:
    """Whether a DP request's metadata4 says its node adds started rows."""
    return DP_STARTED_ROW_CAPABILITY in str(metadata4 or "").split(";")


def started_row_order(value) -> Optional[int]:
    """The order id a started row names, or None for a value of another shape."""
    parts = str(value or "").strip().split(":")
    if len(parts) != 3 or parts[0] != "v1":
        return None
    try:
        int(parts[2])
        return int(parts[1])
    except ValueError:
        return None


def order_start_verdict(rows, order_id: int, block: int, window_end: int) -> str:
    """The verdict on an order's start from its DP request's (key, value)
    rows: 'started' when a started row names it, 'late' when `block` is past
    `window_end` without one, else 'waiting'."""
    if any(key == ORDER_STARTED_KEY and started_row_order(value) == order_id for key, value in rows):
        return "started"
    return "late" if block > window_end else "waiting"


class _Run:
    """One run() of a runner, or one run_session() or attach_session() call.
    `contract` is the protocol contract the runner held when it began, the
    one its transactions go through (EthernityCloudRunner._sender); `ended`
    is set once the thread that works for it has left it."""

    def __init__(self, contract: Optional[protocolContract]) -> None:
        self.contract = contract
        self.ended = threading.Event()


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
        self.do_request: int = -1
        self.order: Optional[Any] = None
        self.order_id: int = -1
        self.script_hash: str = ""
        self.file_set_hash: str = ""
        self.input_data: Optional[str] = None
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
        self.securelock_version: Optional[str] = None
        # The fee ceiling set_max_fee_per_gas gave, in gwei, which every
        # protocol contract the runner builds holds; None where it gave none.
        self.max_fee_per_gas: Optional[int] = None
        # Held by connect() and by run() while it starts its thread, by
        # run_session() and attach_session() for the whole call, and by
        # set_network() and set_private_key() while they build and assign.
        self._run_lock = threading.Lock()
        # Held by connect(), set_network() and set_private_key() while they
        # build and assign the runner's protocol contract, network and key,
        # and by close() while it retires the protocol contracts and drops the
        # contracts, the signer and the key: close() waits for a change in
        # progress and then ends what it left, and a change that waited for
        # close() does nothing (_closes).
        self._change_lock = threading.Lock()
        # How many times close() has dropped the runner's contracts and key,
        # counted as it lets the change lock go: a call that finds another
        # count than at its start began before a close() was done, and
        # raises CLOSED_WHILE_WAITING (_refuse_closed_since).
        self._closes = 0
        # The protocol contracts the runner built (_protocol_contract) that
        # are still referenced: close() retires each of them, and
        # set_max_fee_per_gas sets the ceiling of each.
        self._contracts = weakref.WeakSet()
        # The key under which the task being created queues its blobs for
        # the intake (create_task); None outside a task's creation.
        self._task_blobs: Optional[object] = None
        # The run in progress: the run() whose thread is at work, or the
        # run_session() or attach_session() call under way; None otherwise.
        self._run: Optional[_Run] = None
        # The run close() ended, until a later call has seen its thread leave
        # it (_await_closed_run).
        self._closed_run: Optional[_Run] = None
        # The session handles run_session() and attach_session() returned,
        # until close() detaches them.
        self._sessions: List[Any] = []
        # Held while a submission adds its handle to _sessions, while a
        # handle whose close(wait=True) returned is taken out of it, while
        # close() takes the run in progress and the handles, so a handle is
        # either added before close() and detached by it, or not added, and
        # while _contracts is changed or read.
        self._handles_lock = threading.Lock()
        # .run is the run the calling thread works for (_process_events,
        # _submission); unset in every other thread.
        self._calling = threading.local()
    def set_network(self, network_name: str, network_type: str) -> None:
        """Moves the runner to another network, whole. The names, the table
        entry, the default trustedzone and the block time become the
        network's. On a connected runner the protocol and token contracts are
        built again for the network, as connect() builds them, so that every
        later read and transaction goes to the network's contracts at its
        RPC. The image registry contract, the order with its request's
        challenge and block, the node, the enclave details and the ESR
        wallets learned on the network left are dropped, and an intake client
        is rebuilt under the network's key. The protocol contract of the
        network left is retired (protocolContract.retire): it sends nothing
        more. The key, a storage of the runner's own, the fee ceiling
        set_max_fee_per_gas gave, the resources and the last run's outcome
        stay, and the ESR state cache keeps each network's entries under that
        network. A call that raises changes nothing: ValueError for a name
        the table does not hold, RuntimeError while a run or a session is in
        progress or the thread of a run close() ended is still at work
        (_while_idle), RuntimeError (CLOSED_WHILE_WAITING) when close() was
        called while the call waited, ConnectionError when the network's
        provider does not answer a connected runner. A close() called while
        the call builds and assigns waits for it, and then ends what it
        assigned."""
        closes = self._closes
        name, kind = network_name.upper(), network_type.upper()
        network_class = getattr(ECNetwork, name, None)
        if network_class is None:
            raise ValueError(f"Invalid network name: {network_name}")
        network_config = getattr(network_class, kind, None)
        if network_config is None:
            raise ValueError(f"Invalid network type: {network_type} for network {network_name}")
        with self._while_idle("set_network()", f"Use another EthernityCloudRunner for {name} {kind}.", closes):
            contract = None
            if self.contract is not None:
                contract = self._protocol_contract(name, kind, self.signer)
                if not contract.get_provider().is_connected():
                    raise ConnectionError("Failed to connect to Web3 provider.")
            # An intake client posts under its network key, so one built for
            # the network left is built again for this one.
            ipfs_client = self.ipfs_client
            if ipfs_client is not None and ipfs_client.intake_url:
                ipfs_client = self._intake_client(ipfs_client.intake_url, f"{name.lower()}_{kind.lower()}")
            left = self.contract
            self.network_name, self.network_type, self.network_config = name, kind, network_config
            self.trustedZoneImage = network_config.TRUSTEDZONE_IMAGE
            self.block_time = network_config.BLOCK_TIME
            self.ipfs_client = ipfs_client
            if contract is not None:
                self._hold_contract(contract)
                left.retire(f"The runner was moved to {name} {kind} with set_network()")
            self.image_registry_contract = None
            self._drop_order()
            self.enclave_image_ipfs_hash = ""
            self.enclave_public_key = ""
            self.enclave_docker_compose_ipfs_hash = ""
            self._esr_wallet_memo = {}
    def set_private_key(self, private_key: str) -> None:
        """Gives the runner another wallet, whole. `private_key` is 64 hex
        digits prefixed with 0x. The key and the signer become the wallet's,
        and on a connected runner the protocol contract is built again for
        the runner's network with that signer, as connect() builds it, so
        that every later transaction is signed by the wallet and every read
        is made for it. What the wallet left had in hand is dropped: the
        image registry contract built with its signer, and its order with
        its request's challenge and block and its node; the protocol contract
        built with its signer is retired (protocolContract.retire) and sends
        nothing more. The network, the storage, the fee ceiling
        set_max_fee_per_gas gave, the resources, the enclave details, the ESR
        state cache and the last run's outcome stay. A call that raises
        changes nothing: ValueError for a string of another form and for the
        key zero, the error eth_account raises for a key it does not take,
        RuntimeError while a run or a session is in progress or the thread of
        a run close() ended is still at work (_while_idle), RuntimeError
        (CLOSED_WHILE_WAITING) when close() was called while the call waited.
        A close() called while the call builds and assigns waits for it, and
        then ends what it assigned. No message of the call holds the key."""
        closes = self._closes
        if not private_key.startswith("0x") or len(private_key) != 66:
            raise ValueError("Invalid private key format. Must be 64 hex chars prefixed with 0x.")
        if not private_key[2:].strip("0"):
            raise ValueError("Invalid private key: it is zero, and a secp256k1 private key is from 1 to the order "
                             "of the curve less 1.")
        signer = Account.from_key(private_key)
        with self._while_idle("set_private_key()", "Use another EthernityCloudRunner for another wallet.", closes):
            contract = None
            if self.contract is not None:
                contract = self._protocol_contract(self.network_name, self.network_type, signer)
            left = self.contract
            self.private_key = private_key
            self.signer = signer
            if contract is not None:
                self._hold_contract(contract)
                left.retire("The runner was given another wallet with set_private_key()")
            self.image_registry_contract = None
            self._drop_order()
    @contextmanager
    def _while_idle(self, call: str, instead: str, closes: int):
        """The runner's lock and its change lock, held for a change of its
        network or its wallet. connect(), run(), run_session() and
        attach_session() work under the runner's lock, so one that is
        starting holds it before is_running() says so; close() takes the
        change lock to end what the change assigned. RuntimeError naming
        `call` and `instead` when the runner's lock is held or something of
        the runner is in progress: a run whose thread is at work or a session
        submission (_run), a session handle the runner holds (_sessions), or
        the running flag. RuntimeError from _await_closed_run while the
        thread of a run close() ended is still at work, and
        CLOSED_WHILE_WAITING when close() was called since the call began,
        whose count of close() calls was `closes`."""
        in_progress = (
            f"A run or a session of this runner is in progress on {self.network_name} {self.network_type}: "
            f"{call} is refused until the run has ended or, after a session, the session is closed with "
            f"session.close(wait=True) or the runner with close(). {instead}")
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError(in_progress)
        try:
            self._refuse_closed_since(closes, call)
            self._await_closed_run(call)
            if self._run is not None or self._sessions or self.running:
                raise RuntimeError(in_progress)
            with self._change_lock:
                self._refuse_closed_since(closes, call)
                yield
        finally:
            self._run_lock.release()
    def _refuse_closed_since(self, closes: int, call: str) -> None:
        """RuntimeError (CLOSED_WHILE_WAITING) naming `call` when close() was
        called since the call began, whose count of close() calls was
        `closes`."""
        if self._closes != closes:
            raise RuntimeError(CLOSED_WHILE_WAITING.format(call=call))
    def _await_closed_run(self, call: str) -> None:
        """Waits for the thread of the run close() ended to leave it, for up
        to RUN_END_WAIT_SECONDS, and raises RuntimeError naming `call` when
        it has not by then. That thread sends no transaction (_sender);
        until it has left the run the runner takes no new network, wallet,
        connection, run or session."""
        run = self._closed_run
        if run is None:
            return
        if not run.ended.wait(RUN_END_WAIT_SECONDS):
            raise RuntimeError(
                f"The run this runner was closed during is still at work in its thread, which was waited for "
                f"{RUN_END_WAIT_SECONDS} s: {call} is refused until that thread has ended. The thread sends "
                "no transaction. Call again later, or use another EthernityCloudRunner.")
        self._closed_run = None
    @contextmanager
    def _submission(self):
        """A run_session() or attach_session() call as the runner's run in
        progress, worked for by the calling thread: yields its _Run, which
        close() ends. What the call raises once close() has ended it is
        raised as errors.RunEndedError, with the error of the step the call
        was in as its cause: a read through a contract close() dropped, or a
        wait close() stopped, which reports its step as failed. When the call
        is over the runner has no run in progress."""
        run = _Run(self.contract)
        self._run = run
        self._calling.run = run
        try:
            yield run
        except Exception as error:
            if self._run is not run and not isinstance(error, RunEndedError):
                raise RunEndedError(RUN_ENDED) from error
            raise
        finally:
            if self._run is run:
                self._run = None
            del self._calling.run
            run.ended.set()
    def _hold_session(self, run: _Run, session: Any) -> None:
        """Adds the handle the run_session() or attach_session() call `run`
        made to the runner's handles. errors.RunEndedError when close() ended
        that call: the handle is not added and the call does not return it."""
        with self._handles_lock:
            if self._run is not run:
                raise RunEndedError(RUN_ENDED)
            self._sessions.append(session)
    def _network_and_wallet(self) -> tuple:
        """(network name, network type, wallet address) of the runner; the
        address is None on a runner without a key."""
        signer = self.signer
        return self.network_name, self.network_type, signer.address if signer is not None else None
    def _ended_run(self) -> bool:
        """Whether the calling thread works for a run that is not the
        runner's run in progress: one close() ended."""
        run = getattr(self._calling, "run", None)
        return run is not None and run is not self._run
    def _sender(self) -> protocolContract:
        """The protocol contract a transaction of the calling thread goes
        through. The thread of a run, and the thread inside run_session() or
        attach_session(), sends through the contract the runner held when
        that run began, and only while it is the runner's run in progress:
        once close() has ended it, errors.RunEndedError is raised and nothing
        is sent. Any other thread (a direct call of check_allowance,
        create_do_request, approve_order or cancel_unclaimed_request) sends
        through the contract the runner holds."""
        run = getattr(self._calling, "run", None)
        if run is None:
            return self.contract
        if run is not self._run:
            raise RunEndedError(RUN_ENDED)
        return run.contract
    def _drop_order(self) -> None:
        """Forgets the order in hand: its ids and hashes (reset), its
        request's challenge, block and order count, and its node."""
        self.reset()
        self.challenge_hash = b""
        self.request_start_block = None
        self.current_order_index = 0
        self.node_address = ""
    def _protocol_contract(self, network_name: str, network_type: str, signer: Account) -> protocolContract:
        """The protocol contract of a network for `signer` and the fee
        ceiling set_max_fee_per_gas gave: what connect() builds for the
        runner's network and key, set_network() for the network it moves a
        connected runner to and set_private_key() for the wallet it gives
        one. Its provider is rpc.rpc_provider's. The contract is one of the
        runner's contracts (_contracts) from then on."""
        contract = protocolContract(signer, network_name, network_type, max_fee_per_gas=self.max_fee_per_gas)
        with self._handles_lock:
            self._contracts.add(contract)
            contract.max_fee_per_gas = self.max_fee_per_gas
        return contract
    def _hold_contract(self, contract: protocolContract) -> None:
        """Makes `contract` the one every read and transaction of the runner
        goes through, with its protocol and token contracts."""
        self.contract = contract
        self.protocol_abi = polygonAbi.get("abi")
        self.token_contract = contract.token_contract
        self.protocol_contract = contract.protocol_contract
    def connect(self) -> None:
        """Connect to the protocol contract of the runner's network with its
        key. The contract is built and held under the runner's lock, so a
        set_network() or a set_private_key() of another thread is taken
        before the call or refused during it, never in between, and under
        its change lock, so a close() called meanwhile waits for the call and
        then retires the contract it held. RuntimeError from
        _await_closed_run while the thread of a run close() ended is still
        at work, and CLOSED_WHILE_WAITING when close() was called while the
        call waited."""
        closes = self._closes
        if self.local_mode:
            self.logger.info(f"LOCAL mode: no blockchain connection; using {self.local_endpoint}")
            return
        with self._run_lock:
            self._refuse_closed_since(closes, "connect()")
            self._await_closed_run("connect()")
            with self._change_lock:
                self._refuse_closed_since(closes, "connect()")
                if self.signer is None:
                    raise RuntimeError("Private key must be set before connecting.")
                self._hold_contract(self._protocol_contract(self.network_name, self.network_type, self.signer))
                provider = self.contract.get_provider()
                if not provider.is_connected():
                    raise ConnectionError("Failed to connect to Web3 provider.")
    def set_order_wait(self, seconds: float) -> None:
        """How long a task waits for a node to place an order on its DO
        request before the request is cancelled and its escrow returned
        (default DEFAULT_ORDER_WAIT_SECONDS)."""
        self.order_wait_seconds = float(seconds)
    def set_max_fee_per_gas(self, gwei: int) -> None:
        """The fee ceiling of this runner's transactions on a network whose
        table entry says EIP1559: `gwei`, a positive whole number of gwei,
        taken ahead of the environment variable ECLD_MAX_FEE_PER_GAS and of
        the network's default (the entry's MAX_FEE_PER_GAS). A transaction
        whose maxFeePerGas is above the ceiling in force is not sent and
        raises errors.FeeCeilingError (protocolContract.fee_ceiling). Callable
        before connect() and after it: the ceiling is that of every protocol
        contract of the runner from the next send on, the one the runner
        holds, the one a run in progress began with and the one each session
        handle was made with (_contracts), and of every contract it builds
        later. Raises ValueError naming `gwei` for anything but an int above
        zero."""
        if isinstance(gwei, bool) or not isinstance(gwei, int) or gwei <= 0:
            raise ValueError(f"The fee ceiling is a positive whole number of gwei, given as an int, not {gwei!r}.")
        with self._handles_lock:
            self.max_fee_per_gas = gwei
            for contract in list(self._contracts):
                contract.max_fee_per_gas = gwei
        if self.contract is not None:
            self.contract.max_fee_per_gas = gwei
    def set_log_level(self, level: str) -> None:
        """Set the logging level."""
        self.log_level = ECLog[level.upper()]
        self.logger.setLevel(self.log_level.value)  # Assuming ECLog has int values compatible with logging levels
    def is_mainnet(self) -> bool:
        """Check if the current network is mainnet."""
        return self.network_type == "MAINNET"
    def is_unsafe(self) -> bool:
        """Whether this is an -unsafe network (a type ending in _UNSAFE): the
        chain and contracts of the network it is named after, with the
        trustedzones that run without a CAS."""
        return self.network_type.endswith(UNSAFE_NETWORK_SUFFIX)
    def escrow_needs_allowance(self) -> bool:
        """Whether the wallet approves the protocol on the token before a DO
        request: the request's escrow is pulled with transferFrom when the
        network's protocol address differs from its token address (the
        EthernityImplementationV2 PoX on a separate ERC-20). A protocol that
        is the token (the bloxberg mainnet PoX holds the ETNY balances, its
        copy of BLOXBERG TESTNET_POX10 the tE10 ones) takes the escrow from
        the caller's balance, and no allowance exists."""
        return self.network_config.PROTOCOL_ADDRESS.lower() != self.network_config.TOKEN_ADDRESS.lower()
    def _read_before_request(self, read: callable) -> Any:
        """A read a DO request depends on: `read` is tried
        PRE_REQUEST_READ_ATTEMPTS times, PRE_REQUEST_READ_RETRY_SECONDS apart,
        on any exception, and the last exception is raised after that."""
        return self.retry_operation(read, max_retries=PRE_REQUEST_READ_ATTEMPTS,
                                    delay=PRE_REQUEST_READ_RETRY_SECONDS, backoff_factor=1)
    def check_allowance(self) -> None:
        """The allowance step before a DO request, the same on every network
        whose protocol address differs from its token address
        (escrow_needs_allowance): the wallet's allowance for the protocol on
        the token is read (_read_before_request), and when it is below the
        request's escrow (protocolContract.request_escrow, the amount the PoX
        pulls with transferFrom) the protocol is approved for exactly the
        escrow and the approval is waited for; an allowance at or above the
        escrow is left as it is. Where the protocol is the token (BLOXBERG
        MAINNET and TESTNET_POX10) nothing is read or approved. Raises
        RuntimeError naming the token, the wallet, the protocol and the
        provider's message when no read answers, ValueError when the approval
        is not mined or reverts."""
        if not self.escrow_needs_allowance():
            return
        self.logger.info("Checking allowance on the current wallet...")
        escrow = protocolContract.request_escrow(self.resources)
        wallet = self.signer.address
        protocol = self.contract.get_protocol_address()
        try:
            allowance = self._read_before_request(
                lambda: self.token_contract.functions.allowance(wallet, protocol).call())
        except Exception as e:
            raise RuntimeError(
                f"could not read the {self.network_config.TOKEN_NAME} allowance of {wallet} "
                f"for {protocol} at {self.contract.get_token_address()}: {provider_message(e)}") from e
        if allowance < Web3.to_wei(escrow, "ether"):
            self.logger.info(f"Approving allowance for {escrow} {self.network_config.TOKEN_NAME}")
            transaction_hash = self._sender().set_allowance(escrow)
            receipt = self.poll_transaction(transaction_hash, max_attempts=100)
            if not receipt or receipt["status"] != 1:
                raise ValueError("Allowance approval failed.")
            self.logger.info("Allowance approved")
        self.logger.info("Allowance check completed.")
    def token_has_faucet(self) -> bool:
        """Whether a wallet below a request's escrow draws the token's
        faucet(): on every network but a MAINNET type and an entry whose
        TOKEN_FAUCET is False (BLOXBERG TESTNET_POX10, whose token has no
        faucet())."""
        return self.network_type != "MAINNET" and getattr(self.network_config, "TOKEN_FAUCET", True)
    def _check_balance(self) -> None:
        """The wallet's token balance against the request's escrow
        (protocolContract.request_escrow): a wallet below it draws the token's
        faucet where the token has one (token_has_faucet) and, on an entry
        that holds TOKEN_FAUCET_BELOW (POLYGON AMOY, AMOY_UNSAFE and
        AMOY_POX10, whose token is one), while the wallet holds less than
        that many tokens, the balance below which that faucet gives;
        elsewhere it raises ValueError and no transaction is sent. On
        a MAINNET type the message states the escrow and the balance; on a
        testnet it also names the token, why its faucet does not serve, the
        wallet and the amount a transfer has to bring. The balance is read
        with _read_before_request; the RuntimeError of a read no try answered
        (protocolContract.get_balance) is raised as it is, and no faucet is
        drawn on it."""
        self.logger.info("Checking wallet balance...")
        balance = int(self._read_before_request(self.contract.get_balance))
        escrow = protocolContract.request_escrow(self.resources)
        if balance >= escrow:
            return
        if self.network_type == "MAINNET":
            raise ValueError(f"Insufficient wallet balance. Required: {escrow}, Available: {balance}")
        token = self.network_config.TOKEN_NAME
        gives_below = getattr(self.network_config, "TOKEN_FAUCET_BELOW", None)
        if not self.token_has_faucet():
            faucet = "has no faucet"
        elif gives_below is not None and balance >= gives_below:
            faucet = f"has a faucet that gives to a wallet holding less than {gives_below} {token}"
        else:
            self.logger.info("Insufficient wallet balance, using testnet faucet...")
            self._sender().faucet()
            return
        raise ValueError(
            f"Insufficient wallet balance. Required: {escrow}, Available: {balance}. The token {token} "
            f"({self.network_config.TOKEN_ADDRESS}) of {self.network_name} {self.network_type} {faucet}: "
            f"the wallet {self.signer.address} needs a transfer of {escrow - balance} {token} or more before "
            "the request.")
    def _resolve_trustedzone(self, trustedzone_enclave: Optional[str]) -> str:
        """The trustedzone a task runs on: `trustedzone_enclave` when given,
        else the network's. A trustedzone an entry names in its TRUSTEDZONES
        (those of the testnet PoX 1.0 networks) runs on that network alone,
        and such a network runs no other. An -unsafe trustedzone runs without
        a CAS, and runs only on an -unsafe network, which runs no other. A
        trustedzone the network does not run raises ValueError; run() and
        run_session() ask before any read or transaction."""
        if self.local_mode:
            return "local"
        trustedzone = trustedzone_enclave or self.network_config.TRUSTEDZONE_IMAGE
        home = trustedzone_network(trustedzone)
        if home is not None and home != (self.network_name, self.network_type):
            raise ValueError(
                f"{trustedzone} is a trustedzone of the {home[0]} {home[1]} network and runs on no other: "
                f"run it there, not on {self.network_name} {self.network_type}")
        unsafe_zone = trustedzone.endswith(UNSAFE_TRUSTEDZONE_SUFFIX)
        if unsafe_zone and not self.is_unsafe():
            twin = f"{self.network_type}{UNSAFE_NETWORK_SUFFIX}"
            if getattr(getattr(ECNetwork, self.network_name), twin, None) is None:
                raise ValueError(
                    f"{trustedzone} runs without a CAS; {self.network_name} "
                    f"{self.network_type} has no -unsafe network")
            raise ValueError(
                f"{trustedzone} runs without a CAS: run it on the {self.network_name} "
                f"{twin} network")
        if self.is_unsafe() and not unsafe_zone:
            raise ValueError(
                f"{self.network_name} {self.network_type} runs only -unsafe trustedzones, "
                f"and {trustedzone} is provisioned by a CAS: run it on the "
                f"{self.network_name} {self.network_type[:-len(UNSAFE_NETWORK_SUFFIX)]} network")
        own = getattr(self.network_config, "TRUSTEDZONES", None)
        if own is not None and trustedzone not in own:
            raise ValueError(
                f"{self.network_name} {self.network_type} runs only its trustedzones ({', '.join(own)}), "
                f"and {trustedzone} is not one of them")
        return trustedzone
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
        """The receipt of `tx_hash`, read every CHAIN_POLL_SECONDS for up to
        `max_attempts` blocks (max_attempts * block_time seconds). None when
        the transaction is not mined by then, or the run was cancelled."""
        provider = self.contract.get_provider().eth if self.contract else None
        if not provider:
            raise RuntimeError("No provider available.")
        return self._poll_receipt(provider, tx_hash, max_attempts, self.is_running)
    def _poll_receipt(self, provider: Any, tx_hash: str, max_attempts: int, in_progress: callable) -> Optional[Dict]:
        """poll_transaction's wait, through the eth module `provider`, for as
        long as `in_progress()` holds: the runner's is_running for a run, a
        session handle's own state for a row of that handle, whose receipt
        is read through the contract the handle was made with. A read the
        RPC does not answer (requests.RequestException: no connection, no
        answer within rpc.RPC_TIMEOUT) is made again at the next poll, as a
        receipt not found yet is."""
        self.logger.info(f"Submitting transaction {tx_hash}")
        deadline = time.monotonic() + max_attempts * self.block_time
        attempt = 0
        while True:
            if not in_progress():
                self.logger.info("Transaction processing was cancelled")
                return None
            attempt += 1
            try:
                receipt = provider.get_transaction_receipt(tx_hash)
                if receipt:
                    return receipt
            except TransactionNotFound:
                pass
            except requests.exceptions.RequestException as e:
                self.logger.debug(f"The receipt of {tx_hash} was not read ({type(e).__name__}: {e})")
            left = deadline - time.monotonic()
            if left <= 0:
                self.logger.error(f"Transaction {tx_hash} was not mined within {max_attempts} blocks.")
                return None
            self.logger.debug(f"Transaction {tx_hash} still processing, check {attempt}")
            time.sleep(min(CHAIN_POLL_SECONDS, left))
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
        challenge_ipfs_hash, _ = self._seal_artefact(challenge_hash, operation=self._task_blobs)
        if challenge_ipfs_hash is None:
            raise ValueError("Failed to upload challenge to IPFS.")
        self.challenge_ipfs_hash = challenge_ipfs_hash
        self.logger.info(f"Uploaded challenge to IPFS: {challenge_ipfs_hash}")
        public_key = self.get_current_wallet_public_key()
        return f"{TRUSTEDZONE_VERSION}:{self.enclave_image_ipfs_hash}:{self.securelock_enclave if not self.trustedZoneImage else self.trustedZoneImage}:{self.enclave_docker_compose_ipfs_hash}:{challenge_ipfs_hash}:{public_key}"
    def get_v3_code_metadata(self, code: str) -> str:
        """Generate v3 code metadata."""
        # as_hex=True is REQUIRED: sha256()'s default returns bytes, and
        # f-string interpolation of bytes writes the literal "b'...'" repr into
        # the on-chain metadata. The enclave then compares its computed hex
        # against that repr and every payload fails with
        # PAYLOAD_CHECKSUM_ERROR (orders 1817-1819 on bloxberg testnet).
        script_checksum = sha256(code, True)
        self.script_hash, _ = self._seal_artefact(code.encode("utf-8"), operation=self._task_blobs)
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
        """Generate v3 input metadata: '<version>:<cid>:<sha256>' for the run's
        input dataset, or '<version>::<ZERO_CHECKSUM>' when it has none.

        The dataset is encrypted for the trustedzone and uploaded like the
        payload; the node fetches the CID into the task's input.txt and the
        trustedzone checks its plain sha256 against the checksum here, then
        hands it to the securelock as ___etny_data_set___ / ecld.input.
        Interactive sessions mark the request with a 'v3s' version tag --
        the trustedzone parses it through the same v3 branch but keeps the
        enclaves alive for the order duration."""
        session = getattr(self, "_session_request", False)
        version = f"{TRUSTEDZONE_VERSION}s" if session else TRUSTEDZONE_VERSION
        input_data = None if session else getattr(self, "input_data", None)
        if not input_data:
            self.file_set_hash = ""
            return f"{version}::{ZERO_CHECKSUM}"
        input_checksum = sha256(input_data, True)
        self.file_set_hash, _ = self._seal_artefact(input_data.encode("utf-8"), operation=self._task_blobs)
        if self.file_set_hash is None:
            raise ValueError("Failed to upload encrypted input to IPFS.")
        self.logger.info(f"Uploaded encrypted input to IPFS: {self.file_set_hash}")
        return f"{version}:{self.file_set_hash}:{input_checksum}"
    def create_do_request(self, image_metadata: str, code_metadata: str, input_metadata: str, node_address: Address) -> bool:
        """Create a DO request on the contract."""
        if not self.contract:
            raise RuntimeError("Contract not initialized.")
        self.logger.info("Submitting transaction for DO request")
        # An unpinned request must leave Metadata4 EMPTY: the contract's
        # "any node may take it" path is metadata4.length == 0. The zero
        # address is a 42-character string, so it takes the delegated branch,
        # parses to 0x0 and reverts with "node address invalid" for every
        # caller -- no node can ever place an order. The zero address is
        # therefore written as the empty string, like no address at all.
        node_address = normalize_node_address(node_address)
        node_address = Web3.to_checksum_address(node_address) if node_address else ""
        def send_tx():
            return self._sender().add_do_request(image_metadata, code_metadata, input_metadata, node_address, self.resources)
        # A request the fee ceiling refuses is not sent again: the refusal
        # ends the tries and the submission.
        transaction_hash = self.retry_operation(send_tx, max_retries=50, backoff_factor=2, final=(FeeCeilingError,))
        if not transaction_hash:
            return False
        self.do_hash = transaction_hash
        # The receipt poll_transaction returns is the one the event is read
        # from: a second read can land on an RPC replica that has not seen the
        # transaction yet and raise TransactionNotFound.
        receipt = self.poll_transaction(transaction_hash, max_attempts=100)
        if not receipt or receipt['status'] != 1:
            reason = self.get_reason(self.protocol_contract, transaction_hash) if receipt else "no receipt"
            self.logger.error(f"Unable to create DO request: {reason}")
            return False
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
        # An artefact the held cache carried is referenced on chain now.
        self.storage().release_held([getattr(self, "challenge_ipfs_hash", None), self.script_hash, self.file_set_hash])
        # With the public intake, the artefacts named in the request, those
        # its task queued, are delivered now that the request is on chain.
        self.storage().flush_pending(self.do_request, operation=self._task_blobs)
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
            if result is None or result["function_name"] != "_addResultToOrder":
                raise ValueError("the result transaction is not an _addResultToOrder call")
            arr = result["result"].split(":")
            task_code_int = int(arr[1])
            return {
                "version": arr[0],
                "from": result["from"],
                "to": result["to"],
                "chain_id": result["chain_id"],
                "order_id": result["params"]["_orderItem"],
                "task_code": arr[1],
                "task_code_int": task_code_int,
                "task_code_string": task_status_name(task_code_int),
                "checksum": arr[2],
                "enclave_challenge": arr[3],
            }
        except (IndexError, ValueError) as e:
            raise ValueError(ECError.PARSE_ERROR.value) from e
    def _result_binding_error(self, transaction_result: Dict[str, Any], order_id: int) -> Optional[str]:
        """Why the enclave-signed result transaction is not this order's result
        on this network's PoX, or None when it is.

        The validators reject such a result the same way (ethernity-cas
        result_tx.rs, bound_to): a genuine enclave signature over another
        order, contract or chain proves nothing about this order. A chain id
        of 0 is a pre-EIP-155 signature."""
        if int(transaction_result["order_id"]) != int(order_id):
            return f"the result transaction is for order {transaction_result['order_id']}"
        protocol = self.contract.get_protocol_address()
        to = transaction_result["to"] or ""
        if to.lower() != protocol.lower():
            return f"the result transaction is addressed to {to or 'no contract'}, not {protocol}"
        if transaction_result["chain_id"] not in (0, self.network_config.CHAIN_ID):
            return f"the result transaction is signed for chain {transaction_result['chain_id']}"
        return None
    def _apply_envelope(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Decode the structured result envelope (legacy strings pass through).

        Keeps `value` as the legacy STRING view so string-treating dApps work
        against both old and new enclaves, and adds the typed accessors:
        result_type / result_data / result_esr / result_raw. When the state
        cache is enabled, every envelope's esr entries refresh it, under the
        runner's network (_state_network)."""
        parsed = parse_result_envelope(result.get("value"))
        result["value"] = parsed["legacy"]
        result["result_type"] = parsed["type"]
        result["result_data"] = parsed["data"]
        # get_state() advertises the payload under "result", so a caller
        # reading get_result()["result"] got None on a task that succeeded --
        # a silent false negative. Alias of result_data; both stay populated.
        result["result"] = parsed["data"]
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
                                entry.get("version", 0), entry.get("cid"), network=self._state_network())
                    except Exception:
                        continue
        return result

    def _dp_request_rows(self, dp_request: int) -> List[tuple]:
        """The (key, value) metadata rows of a DP request."""
        caller = self.protocol_contract.caller()
        count = int(caller._getMetadataCountForDPRequest(dp_request))
        return [tuple(caller._getMetadataValueForDPRequest(dp_request, i)) for i in range(count)]

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
        # The RPC is load-balanced over replicas that lag one another, so a read
        # of an order placed moments ago can revert on one that has not seen it.
        status = self.retry_operation(lambda: self.contract.get_status_from_order(order_id), max_retries)
        # The node's start, checked when its DP request advertises the started
        # row: the row must name this order within ORDER_START_WINDOW_BLOCKS.
        caller = self.protocol_contract.caller()
        dp_request = int(self.order[3])
        window_end = None
        try:
            if started_row_advertised(caller._getDPRequestMetadata(dp_request)[4]):
                window_end = self.protocol_contract.w3.eth.block_number + ORDER_START_WINDOW_BLOCKS
        except Exception as e:
            self.logger.debug(f"DP request {dp_request} not readable ({e}); the start of order {order_id} is not checked")
        started = window_end is None
        tick = 0
        while self.is_running() and status != 2:
            if time.time() > deadline:
                self._fault = (
                    f"order {order_id} was not completed within its duration "
                    f"(operator hung or offline)"
                )
                self.logger.error(self._fault)
                return None
            if not started:
                try:
                    verdict = order_start_verdict(self._dp_request_rows(dp_request), order_id,
                                                  self.protocol_contract.w3.eth.block_number, window_end)
                except Exception as e:
                    self.logger.debug(f"start check of order {order_id} skipped this tick ({e})")
                    verdict = "waiting"
                if verdict == "started":
                    started = True
                    self.logger.info(f"Order {order_id} started on its node")
                elif verdict == "late":
                    self._fault = (
                        f"order {order_id} was not started by its node within "
                        f"{ORDER_START_WINDOW_BLOCKS} blocks (operator gone)"
                    )
                    self.logger.error(self._fault)
                    return None
            time.sleep(CHAIN_POLL_SECONDS)
            tick += 1
            # EVENT-FIRST: _orderClosedEV(_orderNumber) fires the moment the
            # operator records the result -- one log scan per tick instead of
            # a struct read. The struct probe stays as a periodic fallback:
            # it also covers terminal states that never emit the event.
            closed = None
            start_block = getattr(self, "request_start_block", None)
            if start_block is not None:
                try:
                    w3 = self.protocol_contract.w3
                    closed = any(
                        w3.codec.decode(["uint256"], bytes(log["data"]))[0] == order_id
                        for log in self._event_logs("_orderClosedEV(uint256)", start_block)
                    )
                except Exception as e:
                    self.logger.debug(f"Event scan unavailable ({type(e).__name__}: {e}); falling back to status polling")
            if closed:
                self.logger.debug(f"_orderClosedEV: order {order_id} closed")
                status = 2
                continue
            if closed is None or tick % 5 == 0:
                status = self.retry_operation(lambda: self.contract.get_status_from_order(order_id), max_retries)
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
        binding_error = self._result_binding_error(transaction_result, order_id)
        if binding_error:
            self._fault = f"order {order_id}: {binding_error}"
            self.logger.error(self._fault)
            self.logger.error("Tokens will be refunded after validation.")
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
        ipfs_result = self._read_result(parsed_order_result["result_ipfs_hash"], deadline)
        if ipfs_result is None:
            self.logger.error("Failed to download the IPFS result before the order's deadline.")
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
            "contract_address": self.contract.get_protocol_address(),
            "input_transaction_hash": self.do_hash,
            "output_transaction_hash": "",
            "order_id": order_id,
            "success": task_code_int == 0,
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
        """Create a new task: its challenge, code and input are sealed and
        its DO request is sent. With an intake storage the sealed blobs are
        queued under a key of the task's own (_task_blobs) and delivered once
        the request is on chain (create_do_request); no other operation of
        the runner posts or drops them, and the task posts no other's. When
        the call ends none of them is left in the queue: a blob that was not
        delivered, because the request was not sent or the delivery failed,
        is dropped (IPFSClient.drop_pending), since the request of a later
        task does not name it and the intake refuses it there. The order
        count read is tried as the reads before a request are
        (_read_before_request)."""
        storage = self.storage()
        self.challenge_hash = generate_random_hex_of_size(20).encode("utf-8")
        blobs = self._task_blobs = object()
        try:
            image_metadata = self.get_v3_image_metadata(self.challenge_hash)
            code_metadata = self.get_v3_code_metadata(code)
            input_metadata = self.get_v3_input_metadata()
            self.current_order_index = self._read_before_request(
                lambda: self.protocol_contract.functions._getOrdersCount().call())
            # Anchor for the stateless event-log scans (find_order / result wait).
            try:
                self.request_start_block = self.protocol_contract.w3.eth.block_number
            except Exception:
                self.request_start_block = None
            return self.create_do_request(image_metadata, code_metadata, input_metadata, self.node_address)
        finally:
            storage.drop_pending(blobs)
            self._task_blobs = None
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
        wait_seconds = getattr(self, "order_wait_seconds", DEFAULT_ORDER_WAIT_SECONDS)
        deadline = time.monotonic() + wait_seconds
        while self.is_running():
            if time.monotonic() >= deadline:
                return self.cancel_unclaimed_request(wait_seconds)
            try:
                if self.find_order(self.do_request):
                    self.logger.info("Connected!")
                    return True
                retry_count = 0
                current_delay = initial_delay
                time.sleep(CHAIN_POLL_SECONDS)
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
    def cancel_unclaimed_request(self, wait_seconds: float) -> bool:
        """The DO request had no order after the wait: cancel it, which
        returns its escrow, and return False. The contract refuses the cancel
        once a node has booked the request; the order that node placed is
        then taken (True) and the task goes on with it."""
        self.logger.warning(f"No node took request {self.do_request} within {wait_seconds} s; cancelling it")
        cancel_error = None
        try:
            transaction_hash = self._sender().cancel_do_request(self.do_request)
            if self.wait_for_transaction_to_be_processed(self.contract, transaction_hash, max_attempts=100):
                self.logger.info(f"Request {self.do_request} cancelled; its escrow is returned")
                return False
            cancel_error = f"cancel transaction {transaction_hash} failed"
        except Exception as e:
            cancel_error = raw_rpc_error_message(e) if isinstance(e, Web3RPCError) else str(e)
        try:
            if self.find_order(self.do_request):
                self.logger.info(f"Request {self.do_request} was booked meanwhile (order {self.order_id}); continuing with it")
                return True
        except Exception as e:
            self.logger.error(f"Could not look the order of request {self.do_request} up: {e}")
        self.logger.error(f"Request {self.do_request} could not be cancelled: {cancel_error}")
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
    def _event_logs(self, signature: str, from_block: int) -> list:
        """Stateless eth_getLogs scan for a protocol event from `from_block`
        to the head. Used instead of eth_newFilter subscriptions, which are
        stateful and break behind load-balanced RPC endpoints. One call per
        range of log_scan_ranges, the logs concatenated in block order: no
        call spans more than GET_LOGS_MAX_BLOCKS, the Zeeve LiteForge RPC's
        limit."""
        w3 = self.protocol_contract.w3
        topics = [w3.keccak(text=signature)]
        logs = []
        for range_from, range_to in log_scan_ranges(from_block, w3.eth.block_number):
            logs.extend(w3.eth.get_logs({
                "address": self.protocol_contract.address,
                "fromBlock": range_from,
                "toBlock": range_to,
                "topics": topics,
            }))
        return logs
    def find_order(self, doreq: int) -> bool:
        """Find the order by request ID."""
        # EVENT-FIRST: one _orderPlacedEV log scan since the request block
        # yields the order number directly -- no struct scanning. The event
        # has no indexed params, so the request id is matched after decoding.
        start_block = getattr(self, "request_start_block", None)
        if start_block is not None:
            try:
                w3 = self.protocol_contract.w3
                for log in self._event_logs("_orderPlacedEV(uint256,uint256,uint256)", start_block):
                    order_no, do_req_id, _dp_req_id = w3.codec.decode(
                        ["uint256", "uint256", "uint256"], bytes(log["data"])
                    )
                    if do_req_id == doreq:
                        self.logger.debug(f"_orderPlacedEV: order {order_no} for request {doreq}")
                        self.order = self.protocol_contract.caller()._getOrder(order_no)
                        self.order_id = order_no
                        return True
                return False
            except Exception as e:
                self.logger.debug(f"Event scan unavailable ({type(e).__name__}: {e}); falling back to order scan")
        # FALLBACK: struct scan over orders created after our request.
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
            return self._sender().approve_order(self.order_id)

        transaction_hash = self.retry_operation(send_tx, max_retries=50, backoff_factor=2)
        # wait_for_transaction_to_be_processed returns a bool, not a receipt:
        # subscripting it raised TypeError and killed the approval.
        approved = self.wait_for_transaction_to_be_processed(self.contract, transaction_hash, max_attempts=100)
        if approved:
            # The receipt came from one RPC replica; the order read can land on
            # one that has not seen the order yet and revert.
            self.node_address = self.retry_operation(lambda: self.contract.get_order(self.order_id))[1]
            self.logger.info(f"{transaction_hash} confirmed!")
            self.logger.info(f"Task {self.order_id} approved successfully!")
            return True
        self.logger.error(f"Approval failed for transaction {transaction_hash}.")
        return False
    @property
    def do_request_id(self) -> int:
        """The DO request of the current run: the _rowNumber of its
        _addDORequestEV (create_do_request), the order's request on
        attach_task; -1 before the request is on chain and after reset()."""
        return self.do_request
    def reset(self) -> None:
        """Reset state variables."""
        self.order = None
        self.order_id = -1
        self.do_hash = None
        self.do_request = -1
        self.script_hash = ""
        self.file_set_hash = ""
        self.get_result_from_order_repeats = 1
        self.task_has_been_picked_for_approval = False
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.reset()
    def out_of_service_message(self) -> Optional[str]:
        """The message that names the PoX as out of service, when its storage
        answers that it does not list it as an allowed caller
        (protocolContract.storage_admission): the storage refuses every call
        made through such a contract, reads included, and its owner takes a
        contract off the list when another one replaces it, so the message
        carries the storage and the advice to upgrade the runner. None when
        the storage lists the PoX or the admission is not read. Asked when a
        read of the PoX fails (verify_protocol, node_check_failure)."""
        admission = self.contract.storage_admission()
        if admission is not None and admission[1] is False:
            return (f"The protocol contract {self.contract.protocol_address} is out of service: its storage "
                    f"{admission[0]} does not list it as an allowed caller, so every call through it is "
                    "refused. That is the state of a contract another one has replaced: upgrade "
                    "ethernity-cloud-runner-py to a release that carries the network's current contract.")
        return None

    def verify_protocol(self) -> None:
        """The protocol check before a DO request, made ahead of the node
        check and the allowance step, so that no escrow is approved for a
        PoX that cannot pull it: the PoX's order count is read
        (protocolContract.get_orders_count), and an answer lets the
        submission go on. A read that fails on a PoX out of service
        (out_of_service_message) raises RuntimeError with that message at
        once, since no later try is answered there. Any other failed read is
        tried again as the balance and allowance reads are
        (_read_before_request), and when no try answers RuntimeError names
        the contract and the provider's message (errors.provider_message) of
        the last one. Either error is chained from the read's own."""
        self.logger.info("Checking the protocol contract...")

        def read() -> Optional[tuple]:
            """None once the order count is read; (message, error) for a read
            that fails on a PoX out of service, which ends the tries; any
            other failed read raises."""
            try:
                self.contract.get_orders_count()
            except Exception as error:
                out_of_service = self.out_of_service_message()
                if out_of_service is not None:
                    return out_of_service, error
                raise RuntimeError(
                    f"The protocol contract {self.contract.protocol_address} did not answer the read "
                    f"of its order count ({provider_message(error)}).") from error
            return None

        refused = self._read_before_request(read)
        if refused is not None:
            message, error = refused
            raise RuntimeError(message) from error

    def node_check_failure(self, error: BaseException) -> str:
        """Why the read of a node's DP requests failed: out_of_service_message's
        text for a PoX its storage does not list as an allowed caller; any
        other failure is reported with the contract and the provider's
        message."""
        return self.out_of_service_message() or (
            f"Could not verify the node address: the protocol contract {self.contract.protocol_address} "
            f"did not answer the read of the node's requests ({provider_message(error)}).")

    def is_node_operator_address(self, node_address: str) -> bool:
        """Whether `node_address` may be named as a run's node: True for no
        address and for an address holding a DP request on the PoX, False for
        a string that is no address and for an address without a DP request.
        A read of the requests that fails raises RuntimeError with
        node_check_failure's message: it says nothing about the node."""
        if is_null_or_empty(node_address):
            return True
        if not is_address(node_address):
            self.logger.error("Introduced address is not a valid wallet address.")
            return False
        try:
            is_node = self.contract.is_node_operator(node_address)
        except Exception as error:
            message = self.node_check_failure(error)
            self.logger.error(message)
            raise RuntimeError(message) from error
        if not is_node:
            self.logger.error("The target address is not a valid node operator address")
        return is_node
    def set_storage_ipfs(self, ipfs_address: str, token: str = ""):
        """Upload and read through a Kubo RPC API: one of your own, or the
        public API (https://ipfs.ethernity.cloud/api/v0) with a writer token
        as `token`. The token is sent as the Authorization header of every
        request. The blobs the intake did not take, held in the runner's held
        cache (ipfs.StorageLimitError), are uploaded through the new API at
        once; returns their outcome, (uploaded, failed)."""
        self.ipfs_client = IPFSClient(ipfs_address, token)
        uploaded, failed = self.ipfs_client.upload_held()
        for cid in uploaded:
            self.logger.info(f"Held blob {cid} uploaded to the IPFS endpoint")
        for cid, reason in failed.items():
            self.logger.warning(f"Held blob {cid} was not taken by the IPFS endpoint: {reason}")
        return uploaded, failed

    def _seal_artefact(self, plaintext: bytes, certificate: Optional[str] = None, operation: Any = None):
        """(cid, digest) of an artefact (challenge, code, input, session
        input) sealed for the enclave's certificate, through the configured
        storage; the digest is the ciphertext's sha256, hex. The certificate
        is `certificate` when given, the one a session handle was made with
        (EthernityCloudSession.send_input), else the one the runner holds
        (enclave_public_key). Through an intake the sealed bytes are queued
        under `operation`, the key of the task or the session handle that
        seals them (IPFSClient.upload_to_ipfs). An artefact the intake does
        not take (ipfs.INTAKE_MAX_BYTES) is held in the runner's held cache under the
        key of its plaintext and the enclave key, logged at ERROR and raised
        as ipfs.StorageLimitError before any transaction names it; once an
        IPFS endpoint of the application's own has uploaded it
        (set_storage_ipfs, or here when one is set), the same plaintext
        sealed for the same enclave resolves to the held ciphertext's CID
        without a new seal, which a new nonce would give a new CID."""
        storage = self.storage()
        if certificate is None:
            certificate = self.enclave_public_key
        enclave_key = self._data_bytes(certificate)
        key = f"{hashlib.sha256(plaintext).hexdigest()}|{hashlib.sha256(enclave_key).hexdigest()}"
        held = storage.held_entry(key)
        if held is not None:
            if held["uploaded"]:
                return held["cid"], held["digest"]
            if not storage.intake_url:
                uploaded, _ = storage.upload_held()
                if held["cid"] in uploaded:
                    return held["cid"], held["digest"]
            refused = StorageLimitError(held["cid"], held["size"], storage.intake_max_bytes, storage.held_cache.location())
            self.logger.error(str(refused))
            raise refused
        ciphertext = self._data_bytes(encrypt(plaintext, certificate))
        try:
            cid = storage.upload_to_ipfs(ciphertext, held_key=key, operation=operation)
        except StorageLimitError as e:
            self.logger.error(str(e))
            raise
        return cid, hashlib.sha256(ciphertext).hexdigest()

    @staticmethod
    def _data_bytes(value) -> bytes:
        return value if isinstance(value, bytes) else str(value).encode("utf-8")
    def set_public_intake(self, base_url: str = PUBLIC_INTAKE) -> None:
        """Upload through the bootnode's payload intake and read through its
        public API: the storage a runner uses when neither this nor
        set_storage_ipfs() was called. Artefact CIDs are computed locally and
        the bytes are delivered once the DO request is on chain, under the
        current network's key. The bootnode's intake serves ipfs.INTAKE_NETWORKS
        only: a run or session on another network is refused by
        _resolve_storage before any transaction; an intake of your own, named
        by `base_url`, serves what its agent runs."""
        self.ipfs_client = self._intake_client(base_url, self._intake_network())
    @staticmethod
    def _intake_client(base_url: str, network: str) -> IPFSClient:
        """A client that delivers through the payload intake at `base_url`
        under the network key `network` and reads through its API."""
        return IPFSClient(f"{base_url.rstrip('/')}/api/v0", "", intake_url=base_url, network=network)
    def _intake_network(self) -> str:
        """The network's key in the intake's route, the node agent's name for
        it: <network>_<type>, lower case (bloxberg_testnet)."""
        return f"{self.network_name.lower()}_{self.network_type.lower()}"
    def storage(self) -> IPFSClient:
        """The client every upload and read goes through: the one
        set_storage_ipfs() or set_public_intake() configured, else the
        bootnode's payload intake, built on first use."""
        if self.ipfs_client is None:
            self.set_public_intake()
        return self.ipfs_client
    def _resolve_storage(self) -> None:
        """Resolves the storage a new task's or session's artefacts go through
        before the first transaction names them (storage() builds the
        default). A runner whose storage is the bootnode's payload intake,
        configured or by default, on a network that intake does not serve
        (ipfs.INTAKE_NETWORKS) is refused here, before any transaction: a
        delivery refused once the DO request is on chain would leave the
        request's escrow on an order nobody approves."""
        network = self._intake_network()
        if network not in INTAKE_NETWORKS and (
                self.ipfs_client is None or self.ipfs_client.intake_url == PUBLIC_INTAKE):
            configured = ("No storage is configured, and the default, the bootnode's payload intake,"
                          if self.ipfs_client is None else "The bootnode's payload intake")
            raise RuntimeError(
                f"{configured} serves {', '.join(INTAKE_NETWORKS)}, not {self.network_name} "
                f"{self.network_type}: call set_storage_ipfs(url, token) with a Kubo RPC API "
                "of your own, or with the public API https://ipfs.ethernity.cloud/api/v0 and "
                "a writer token.")
        self.storage()
    def _read_result(self, result_cid: str, deadline: float) -> Optional[str]:
        """Read the result blob until the order's deadline, and for at least
        two minutes after the order closed: a result pinned at close may take
        that long to reach the endpoint read from. Each attempt tries the
        configured API, then the public gateway (IPFSClient.get_file_content);
        a miss is logged at debug level and asked again, and only giving up is
        a warning."""
        until = max(deadline, time.time() + 120)
        attempt = 0
        while self.is_running():
            attempt += 1
            try:
                content = self.storage().get_file_content(result_cid)
            except Exception as e:
                content = None
                self.logger.debug(f"Result read attempt {attempt}: {e}")
            if content is not None:
                return content
            if time.time() >= until:
                self.logger.warning(f"Result {result_cid} not readable after {attempt} attempts")
                return None
            time.sleep(min(CHAIN_POLL_SECONDS, max(1, until - time.time())))
        return None

    def retry_operation(self, func: callable, max_retries: int = 10, delay: Optional[int] = None, backoff_factor: float = 1.5, final: tuple = ()) -> Any:
        """Retry a function with exponential backoff. An exception of a type
        in `final`, and errors.RunEndedError, is raised as it is, with no
        further try and no wait; so is any exception in the thread of a run
        close() has ended (_ended_run), which tries nothing again."""
        delay = delay or self.block_time
        current_delay = delay
        for attempt in range(max_retries):
            try:
                return func()
            except final:
                raise
            except RunEndedError:
                raise
            except Exception as e:
                self.logger.warning(f"Retry {attempt + 1}/{max_retries}: {e}")
                if attempt == max_retries - 1 or self._ended_run():
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
        trustedzone_enclave: Optional[str] = None,
        max_retries: int = 2,
        retry_delay: int = 30,
        input_data: Optional[str] = None,
    ) -> None:
        """Run the task.

        trustedzone_enclave: the trustedzone the securelock was built against,
        e.g. etny-nodenithy-testnet for a nodenithy dApp. Default: the
        network's (TRUSTEDZONE_IMAGE). A securelock published without a CAS
        runs on the -unsafe network (BLOXBERG TESTNET_UNSAFE, LITVM
        LITEFORGE_UNSAFE, ETHEREUM SEPOLIA_UNSAFE, POLYGON AMOY_UNSAFE) against
        an -unsafe trustedzone, and only there.
        max_retries: how many times to resubmit the task as a NEW DO request
        when it fails on the operator side (order timeout, unusable operator
        output, or an operator-fault task code, OPERATOR_FAULT_CODES). Failures
        caused by the submitted code itself are final results and are never
        retried.
        retry_delay: seconds to wait between resubmissions.
        input_data: the task's input dataset, a string the payload reads as
        ___etny_data_set___ (ecld.input). It travels encrypted for the
        trustedzone, which verifies it against the sha256 in the request.

        Thread-safety: task state (do_request, order, result, ...) lives on
        THIS instance, and two interleaved runs would track the same order,
        fail each other's integrity checks and collide on the wallet's
        transaction nonce. A call starts its thread under the runner's lock,
        which a submission, a connect() or a change of the network or the
        wallet under way holds until it is done. A call made while a run or
        a session of the runner is in progress raises RuntimeError("A task is
        already running.") and changes nothing of it; one made while the
        thread of a run close() ended is still at work raises RuntimeError
        after RUN_END_WAIT_SECONDS (_await_closed_run), and one that waited
        for the lock while close() was called raises CLOSED_WHILE_WAITING.
        For parallel tasks use one runner instance per task."""
        closes = self._closes
        if not self._run_lock.acquire(blocking=False):
            self.logger.info(
                "Another call holds this runner's lock -- waiting for it to be done.")
            self._run_lock.acquire()
        try:
            self._refuse_closed_since(closes, "run()")
            return self.__run_exclusive(
                resources, securelock_enclave, securelock_version, code,
                node_address, trustedzone_enclave, max_retries, retry_delay, input_data)
        finally:
            self._run_lock.release()

    def __run_exclusive(
        self,
        resources,
        securelock_enclave,
        securelock_version,
        code,
        node_address,
        trustedzone_enclave,
        max_retries,
        retry_delay,
        input_data,
    ) -> None:
        self._await_closed_run("run()")
        if self.running or self._run is not None or self._sessions:
            raise RuntimeError("A task is already running.")
        if input_data is not None and not isinstance(input_data, str):
            raise TypeError("input_data must be a string")
        trustedzone = self._resolve_trustedzone(trustedzone_enclave)
        self.input_data = input_data
        if not self.local_mode:
            self._resolve_storage()
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
        self.trustedZoneImage = trustedzone
        # Recorded for every mode, LOCAL included: esr_read() and the ESR
        # wallet memo name the enclave of the last run.
        self.securelock_enclave = securelock_enclave
        self.securelock_version = securelock_version
        self.status = ECStatus.RUNNING
        self.last_error = None
        self.result = None
        self.running = True
        self.processed_events = []
        self._populate_event_queue()
        run = _Run(self.contract)
        self._run = run
        self.task_thread = threading.Thread(
            target=self._process_events,
            args=(code, node_address, resources, run),
            daemon=True
        )
        self.task_thread.start()
    def _populate_event_queue(self) -> None:
        """Makes the event queue the events of one submission, INIT through
        FINISHED, whatever it holds: the events a failed run or attempt did
        not reach stay queued after it, where get_state() reports them as
        remaining_events, and are dropped here, so every run and every
        resubmission starts at INIT."""
        events = [
            ECEvent.INIT,
            ECEvent.CREATED,
            ECEvent.ORDER_PLACED,
            ECEvent.IN_PROGRESS,
            ECEvent.FINISHED,
        ]
        with self.event_queue.mutex:
            self.event_queue.queue.clear()
        for event in events:
            self.event_queue.put(event)
    def _process_events(self, code: str, node_address: str, resources: Dict[str, int], run: _Run) -> None:
        """Process events, resubmitting on operator-side failures. `run` is
        the run() this thread works for: its transactions go through that
        run's contract (_sender), and once close() has ended the run the
        thread sends nothing, tries nothing again, and leaves the runner's
        status, error and running flag as close() set them. When the call
        is over the thread works for no run."""
        self._calling.run = run
        attempt = 0
        try:
            while True:
                try:
                    self._run_attempt(code, node_address, resources)
                    return
                except OperatorFaultError as e:
                    if self._ended_run():
                        return
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
                    if self._ended_run():
                        return
                    self._populate_event_queue()
                except Exception as e:
                    if self._ended_run():
                        self.logger.info(f"The run close() ended has left its thread: {e}")
                        return
                    self.progress = ECEvent.FINISHED
                    self.status = ECStatus.ERROR
                    self.last_error = str(e)
                    self.logger.error(f"Error: {self.last_error}")
                    return
        finally:
            if self._run is run:
                self._run = None
                self.running = False
            del self._calling.run
            run.ended.set()

    def _finish(self, completed: str) -> None:
        """The FINISHED event: SUCCESS when the enclave's task code is 0. A
        non-zero code is the task's own failure (an exception in the dApp, a
        checksum mismatch, ...): ERROR, with last_error naming the code and the
        result kept, since its value carries the enclave's error report."""
        self.progress = ECEvent.FINISHED
        result = self.result or {}
        if result.get("success"):
            self.status = ECStatus.SUCCESS
            self.logger.info(completed)
            return
        self.status = ECStatus.ERROR
        self.last_error = (
            f"The task failed in the enclave with {result.get('result_task_code')} "
            f"({result.get('result_task_code_int')}); the result holds its error report.")
        self.logger.error(self.last_error)

    def _run_local_attempt(self, code: str) -> None:
        """LOCAL mode: run the task against the ecld-test API, no blockchain.

        Walks the same event queue so get_state() reports the same progress
        shape as a real run; the result dict mirrors get_result_from_order's."""
        import json
        import urllib.request

        while self.is_running():
            event = self._next_event()
            if event is None:
                break
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
                body = json.dumps({"payload": code, "input": self.input_data or None}).encode("utf-8")
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
                self._finish("Task completed (LOCAL mode).")
            self.processed_events.append(event.name)

    def _next_event(self) -> Optional[ECEvent]:
        """The next event of the queue, or None when it holds none: the event
        is taken without waiting, so a queue close() empties meanwhile ends
        the attempt instead of blocking its thread."""
        try:
            return self.event_queue.get_nowait()
        except Empty:
            return None
    def _run_attempt(self, code: str, node_address: str, resources: Dict[str, int]) -> None:
        """One full submission attempt: INIT through FINISHED."""
        if self.local_mode:
            return self._run_local_attempt(code)
        while self.is_running():
            event = self._next_event()
            if event is None:
                break
            if event == ECEvent.INIT:
                self.progress = ECEvent.INIT
                self._check_balance()
                self.verify_protocol()
                self.logger.info("Verifying node address...")
                self.node_address = normalize_node_address(node_address)
                if not self.is_node_operator_address(self.node_address):
                    raise ValueError("Node address verification failed.")
                self.cleanup()
                image_to_check = self.securelock_enclave if not self.trustedZoneImage else self.trustedZoneImage
                self.logger.info(f"Checking image {image_to_check} in registry...")
                self.image_registry_contract = ImageRegistryContract(self.network_name, self.network_type, self.signer)
                if not self.check_web3_connection():
                    raise ConnectionError("Web3 connection failed.")
                if not self.get_enclave_details():
                    raise ValueError("Unable to find enclave in registry")
                self.check_allowance()
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
                self._finish("Task completed successfully.")
            self.processed_events.append(event.name)
    def run_session(
        self,
        resources: Optional[Dict[str, int]],
        securelock_enclave: str,
        securelock_version: str,
        code: str,
        node_address: str = "",
        trustedzone_enclave: Optional[str] = None,
    ) -> "EthernityCloudSession":
        """Start an INTERACTIVE SESSION task and return its handle.

        Same submission flow and trustedzone selection as run() up to order
        approval, but the request carries the v3s session marker, so the
        enclaves stay alive for the order duration and stream inputs/outputs
        through the on-chain metadata channels. Returns once the order is
        PROCESSING; use the returned EthernityCloudSession to send_input /
        poll_outputs / close.
        Synchronous by design -- the session handle is the async surface.

        The whole call holds the runner's lock and is the runner's run in
        progress (_submission): its transactions go through the contract the
        runner held when it began, and a close() during it ends it with
        errors.RunEndedError, whose cause is the error of the step it was in.
        RuntimeError("A task is already running.")
        while a run() of the runner is in progress, RuntimeError from
        _await_closed_run while the thread of a run close() ended is still
        at work, and CLOSED_WHILE_WAITING when close() was called while the
        call waited for the runner's lock. The handle returned stays among
        the runner's handles, and the runner in progress, until its
        close(wait=True) has returned the session's summary or the runner's
        close(); a call that fails leaves the runner in progress only for
        the handles it already holds.
        """
        from .session import EthernityCloudSession
        closes = self._closes
        with self._run_lock:
            self._refuse_closed_since(closes, "run_session()")
            self._await_closed_run("run_session()")
            if self._run is not None:
                raise RuntimeError("A task is already running.")
            self.trustedZoneImage = self._resolve_trustedzone(trustedzone_enclave)
            self.input_data = None
            self._resolve_storage()
            self._fault = None
            if resources is None:
                resources = {
                    "taskPrice": 10, "cpu": 1, "memory": 1, "storage": 40,
                    "bandwidth": 1, "duration": 1, "validators": 1,
                }
            self.resources = resources
            self.status = ECStatus.RUNNING
            with self._submission() as run:
                # get_enclave_details() and the submission steps below bail
                # out early unless is_running() holds; without this the
                # registry lookup returns False and surfaces as "Unable to
                # find enclave in registry" even when the enclave is
                # published.
                self.running = True
                try:
                    self._check_balance()
                    self.verify_protocol()
                    self.logger.info("Verifying node address...")
                    self.node_address = normalize_node_address(node_address)
                    if not self.is_node_operator_address(self.node_address):
                        raise ValueError("Node address verification failed.")
                    self.securelock_enclave = securelock_enclave
                    self.securelock_version = securelock_version
                    self.cleanup()
                    self.image_registry_contract = ImageRegistryContract(
                        self.network_name, self.network_type, self.signer)
                    if not self.check_web3_connection():
                        raise ConnectionError("Web3 connection failed.")
                    if not self.get_enclave_details():
                        raise ValueError("Unable to find enclave in registry")
                    self.check_allowance()
                    self._session_request = True
                    try:
                        if not self.create_task(code):
                            raise ValueError("Unable to create a DO request")
                    finally:
                        self._session_request = False
                    if not self.check_order_for_task():
                        raise ValueError("Could not find any available operator matching this task request.")
                    if not self.approve_task():
                        raise ValueError("Task approval failed.")
                    self.logger.info(f"Session order {self.order_id} is processing")
                    session = EthernityCloudSession(self, self.order_id)
                    self._hold_session(run, session)
                except BaseException:
                    # The flag stays set for the handles the runner holds,
                    # and as close() left it when close() ended this call.
                    if self._run is run:
                        self.running = bool(self._sessions)
                    raise
            return session

    def attach_session(
        self,
        order_id: int,
        securelock_enclave: Optional[str] = None,
        securelock_version: str = "v3",
    ) -> "EthernityCloudSession":
        """Reattach to a running session order -- STATELESS: everything is
        rebuilt from chain state (seq resumes from the on-chain rows, output
        decryption uses the wallet key). Pass securelock_enclave to also
        re-resolve the enclave certificate so send_input works from this
        fresh process; without it the handle is receive/close-only.

        The whole call holds the runner's lock, as run_session() does, and a
        call made while another holds it waits. An order id names an order
        of one network and one wallet, those the runner has when the call is
        made: a call that waited for a set_network() or a set_private_key()
        of another thread raises RuntimeError naming both the network and
        the wallet asked for and those the runner has, and reads nothing; a
        call that waited for a close() raises CLOSED_WHILE_WAITING and reads
        nothing; a call that waited for anything else attaches once that is
        done. RuntimeError("A task is already running.") while a run() of the
        runner is in progress, RuntimeError from _await_closed_run while the
        thread of a run close() ended is still at work, errors.RunEndedError
        when close() ends the call, as run_session() raises it. The handle
        returned stays among the runner's handles, and the runner in
        progress, until its close(wait=True) has returned the session's
        summary or the runner's close(); a call that fails leaves the runner
        in progress only for the handles it already holds.
        """
        from .session import EthernityCloudSession
        closes = self._closes
        asked_on = self._network_and_wallet()
        with self._run_lock:
            self._refuse_closed_since(closes, "attach_session()")
            self._await_closed_run("attach_session()")
            if self._run is not None:
                raise RuntimeError("A task is already running.")
            held = self._network_and_wallet()
            if held != asked_on:
                raise RuntimeError(
                    f"attach_session() waited for a change of this runner, which is on {held[0]} {held[1]} with "
                    f"the wallet {held[2]}; order {order_id} was asked for on {asked_on[0]} {asked_on[1]} with "
                    f"the wallet {asked_on[2]}, and an order id names an order of one network and one wallet. "
                    "Call attach_session() again for the order meant.")
            order = self.protocol_contract.caller()._getOrder(int(order_id))
            if str(order[0]).lower() != str(self.signer.address).lower():
                raise ValueError("Order does not belong to this wallet")
            meta = self.protocol_contract.caller()._getDORequestMetadata(int(order[2]))
            if str(meta[3] or "").split(":")[0] != "v3s":
                raise ValueError("Order is not an interactive session")
            with self._submission() as run:
                # The order is PROCESSING on chain, so the runner is running
                # from this process's point of view; get_enclave_details()
                # below needs the flag set or it returns False and reports a
                # missing enclave.
                self.running = True
                try:
                    if securelock_enclave:
                        self.securelock_enclave = securelock_enclave
                        self.securelock_version = securelock_version
                        self.image_registry_contract = ImageRegistryContract(
                            self.network_name, self.network_type, self.signer)
                        # send_input delivers through the storage.
                        self._resolve_storage()
                        # The trustedzone the order was placed with: field 2
                        # of its image metadata
                        # (v3:image:trustedzone:compose:challenge:key).
                        image_fields = str(meta[1] or "").split(":")
                        self.trustedZoneImage = self._resolve_trustedzone(
                            image_fields[2] if len(image_fields) > 2 else None)
                        if not self.get_enclave_details():
                            raise ValueError("Unable to find enclave in registry")
                    session = EthernityCloudSession(self, int(order_id))
                    self._hold_session(run, session)
                except BaseException:
                    # The flag stays set for the handles the runner holds,
                    # and as close() left it when close() ended this call.
                    if self._run is run:
                        self.running = bool(self._sessions)
                    raise
            return session

    def list_sessions(self) -> List[int]:
        """Order ids of THIS wallet's session requests still PROCESSING --
        running enclaves this wallet can reattach to."""
        sessions = []
        try:
            my_orders = self.protocol_contract.functions._getMyDOOrders().call(
                {"from": self.signer.address})
        except Exception as e:
            self.logger.warning(f"Could not enumerate orders: {e}")
            return sessions
        for oid in my_orders:
            try:
                order = self.protocol_contract.caller()._getOrder(int(oid))
                if int(order[4]) != 1:
                    continue
                meta = self.protocol_contract.caller()._getDORequestMetadata(int(order[2]))
                if str(meta[3] or "").split(":")[0] == "v3s":
                    sessions.append(int(oid))
            except Exception:
                continue
        return sessions

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
        """Check if a task is currently running: the running flag, set while
        a run's thread works and from a session's submission or attachment
        until close(). In the thread of a run close() has ended it is False
        whatever the flag says, so the waits of that run stop."""
        if self._ended_run():
            return False
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

    def _state_network(self) -> str:
        """The key the ESR state cache keeps the runner's network's entries
        under: <network>_<type>, lower case (polygon_amoy_pox10). Each
        network's Enclave State Registry holds its own state for a wallet and
        a key, so an entry cached on one network is read on no other."""
        return self._network_key(self.network_name, self.network_type)

    @staticmethod
    def _network_key(network_name: str, network_type: str) -> str:
        """<network>_<type> in lower case."""
        return f"{network_name.lower()}_{network_type.lower()}"

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
        given) and refreshes the cache from its result envelope. The network
        is read once, as the call begins: the cache is read under that
        network's key (_state_network), the free check is made on that
        network's Enclave State Registry, and a state-fetch task is run only
        while the runner is still on that network (RuntimeError otherwise,
        before any task). A state cached on another network is not served.
        An entry under the wallet and the key alone, the key
        ethernity-cloud-runner-py 0.5.38 wrote, is served when no entry of
        the network is cached, its cid is not empty and the network's
        registry holds that cid, and it is then cached under the network's
        key as well. The free check's read is tried as the reads before a
        request are (_read_before_request).

        Wallet resolution: explicit `enclave_wallet`, else the wallet learned
        from previous result envelopes for this enclave (self-healing across
        enclave identity rotation).

        Returns {state, version, cid, wallet, from_cache, checked_on_chain}.
        """
        with self._change_lock:
            network_name, network_type = self.network_name, self.network_type
        network = self._network_key(network_name, network_type)
        enclave_name = securelock_enclave or self.securelock_enclave
        wallet = enclave_wallet or self._esr_wallet_memo.get(enclave_name or "")

        checked_on_chain = False
        cache = self._get_state_cache()
        if (not force) and cache is not None and wallet:
            entry = cache.get(wallet, key, network=network)
            legacy = None
            if entry is None:
                legacy = cache.get(wallet, key)
                if legacy is not None and not legacy.get("cid"):
                    legacy = None
            if entry is not None or legacy is not None:
                try:
                    esr = ESRContract(network_name, network_type)
                    onchain = self._read_before_request(lambda: esr.get_state(wallet, key))
                    checked_on_chain = True
                    fresh = False
                    if entry is None:
                        # The cid names the state's content, whatever
                        # network the entry was written on.
                        fresh = legacy["cid"] == onchain.get("cid")
                        if fresh:
                            entry = legacy
                            cache.set(wallet, key, entry.get("state"), entry.get("version", 0), entry["cid"],
                                      network=network)
                    else:
                        # Prefer cid equality (content-addressed); fall back
                        # to version. trust_min_version covers the caller's
                        # own still-relaying commit: external writes only
                        # increase the version, so they still invalidate.
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
        if (self.network_name, self.network_type) != (network_name, network_type):
            raise RuntimeError(
                f"esr_read('{key}') was called on {network_name} {network_type}, and the runner was moved to "
                f"{self.network_name} {self.network_type} before its state-fetch task: no task was run. Call "
                "esr_read again on the network meant.")
        self.run(
            resources or getattr(self, "resources", None),
            enclave_name,
            version,
            code,
            node_address=node_address or (self.node_address or ""),
            trustedzone_enclave=self.trustedZoneImage,
        )
        # run() hands the task to task_thread and returns at once; the result
        # exists only when that thread has finished.
        if self.task_thread is not None:
            self.task_thread.join()
        result = self.get_result()
        if not result or not result.get("success"):
            reason = self.last_error or (result or {}).get("result_task_code")
            raise RuntimeError(f"esr_read task failed for key '{key}': {reason}")
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
    def _esr_onchain(self, key: str, enclave_wallet: Optional[str] = None) -> Dict[str, Any]:
        """FREE on-chain {wallet, version, cid} for an ESR key (one eth_call).

        Wallet resolution mirrors esr_read: explicit `enclave_wallet`, else the
        wallet learned from previous result envelopes for this enclave."""
        enclave_name = self.securelock_enclave
        wallet = enclave_wallet or self._esr_wallet_memo.get(enclave_name or "")
        if not wallet:
            raise ValueError(
                "esr_version/esr_wait_for_version need enclave_wallet "
                "(no previous run to learn it from)")
        esr = ESRContract(self.network_name, self.network_type)
        onchain = esr.get_state(wallet, key)
        return {
            "wallet": wallet,
            "version": int(onchain.get("version", 0) or 0),
            "cid": onchain.get("cid"),
        }

    def esr_version(self, key: str, enclave_wallet: Optional[str] = None) -> Dict[str, Any]:
        """Current on-chain {wallet, version, cid} for `key` -- free (a single
        eth_call), no task, no gas. version 0 means never committed."""
        return self._esr_onchain(key, enclave_wallet)

    def esr_nonce(self, key: str, enclave_wallet: Optional[str] = None) -> Dict[str, Any]:
        """Last accepted idempotency nonce for `key` -- {wallet, nonce}, free
        (a single eth_call), no task, no gas. nonce 0 means no guarded commit
        was ever made.

        The nonce is PUBLIC on-chain data: the registry records it next to the
        version, so a web3 app reads the latest accepted value here and
        submits the state-writing task with EXACTLY nonce + 1 -- the contract
        enforces the sequence strictly (1, 2, 3, ... per key; no gaps, no
        reuse). A duplicate or out-of-sequence submission fails with task code
        36 (ESR_NONCE_VIOLATION) instead of applying twice."""
        enclave_name = self.securelock_enclave
        wallet = enclave_wallet or self._esr_wallet_memo.get(enclave_name or "")
        if not wallet:
            raise ValueError(
                "esr_nonce needs enclave_wallet (no previous run to learn it from)")
        esr = ESRContract(self.network_name, self.network_type)
        return {"wallet": wallet, "nonce": esr.get_nonce(wallet, key)}

    def esr_wait_for_version(
        self,
        key: str,
        since_version: int,
        enclave_wallet: Optional[str] = None,
        timeout: float = 120.0,
        interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Wait (free polling eth_calls) until `key`'s on-chain version is
        GREATER than `since_version`; returns the fresh {wallet, version, cid}.

        The intended pattern -- read the version, submit the state-writing
        task, then wait for the commit to actually land on-chain:

            v = runner.esr_version("dashboard", enclave_wallet=W)["version"]
            runner.run(...)                       # task that commits state
            runner.esr_wait_for_version("dashboard", v, enclave_wallet=W)

        Raises TimeoutError if the version does not advance within `timeout`
        seconds. A read the RPC does not answer (requests.RequestException)
        is made again at the next interval."""
        deadline = time.monotonic() + float(timeout)
        while True:
            try:
                cur = self._esr_onchain(key, enclave_wallet)
            except requests.exceptions.RequestException as e:
                self.logger.debug(f"ESR version read of '{key}' failed ({type(e).__name__}: {e})")
                cur = None
            if cur is not None and cur["version"] > int(since_version):
                return cur
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"ESR state for '{key}' did not advance past version "
                    f"{since_version} within {timeout}s")
            time.sleep(interval)

    def _release_session(self, session: Any) -> None:
        """Takes `session` out of the runner's handles once its close(wait=True)
        has returned the session's summary: it reads nothing more through the
        runner. The runner stays in progress for the handles it still holds
        and a run in progress."""
        with self._handles_lock:
            if any(held is session for held in self._sessions):
                self._sessions = [held for held in self._sessions if held is not session]
                self.running = bool(self._sessions) or self._run is not None
    def close(self) -> None:
        """Close resources and stop the runner. The run in progress (a run()
        whose thread is at work, a run_session() or attach_session() call
        under way) ends: its thread sends no transaction after this
        (_sender). A connect(), set_network() or set_private_key() building
        and assigning in another thread is waited for, and its outcome ended
        with the rest; one that waits for the runner meanwhile does nothing
        and raises CLOSED_WHILE_WAITING. Every protocol contract the runner
        built is retired (protocolContract.retire), so nothing is sent
        through it by anything that still holds one: the contract the runner
        holds, the one the run in progress began with, the one each session
        handle was made with, and any other the runner built (_contracts). A
        transaction being handed to the node is handed over before close()
        goes on, and none is sent through these contracts after it. The
        contracts, the signer and the key are dropped with the change lock
        held. Every session handle of the runner is detached: it sends and
        reads nothing more and raises session.SessionError
        (EthernityCloudSession._detach). The thread of a run is waited for
        two block times; one still at work then is waited for again, for up
        to RUN_END_WAIT_SECONDS, by the next connect(), run(), run_session(),
        attach_session(), set_network() or set_private_key(), which raises
        RuntimeError while the thread has not ended (_await_closed_run)."""
        self.running = False
        with self._change_lock:
            with self._handles_lock:
                run, self._run = self._run, None
                sessions, self._sessions = self._sessions, []
                if run is not None:
                    self._closed_run = run
                built = list(self._contracts)
            ended = [self.contract] + ([run.contract] if run is not None else []) + [
                session._contract for session in sessions] + built
            for contract in ended:
                if contract is not None:
                    contract.retire("The runner was closed with close()")
            providers = [self.contract, self.image_registry_contract]
            self.contract = None
            self.token_contract = None
            self.protocol_contract = None
            self.image_registry_contract = None
            self.signer = None
            self.private_key = ""
            # Counted as the change lock is let go: a call that began before
            # this point finds another count than at its start.
            self._closes += 1
        detached = (
            f"The runner was closed with close(): this handle of a session on {self.network_name} "
            f"{self.network_type} sends and reads nothing more. The session's order stays as it is on chain; "
            "attach_session(order_id) on a connected runner of that network and wallet gives a new handle.")
        for session in sessions:
            session._detach(detached)
        for obj in providers:
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
        with self.event_queue.mutex:
            self.event_queue.queue.clear()
        self.event_queue = Queue()
        self.reset()
        self.processed_events = []
        self.result = None
        self.task_thread = None
        self.ipfs_client = None
        self.status = ECStatus.SUCCESS
        self.logger.info("Runner resources closed successfully")