"""EthernityCloudRunner.set_network moves a runner to another network whole.
On a connected runner the protocol and token contracts are built again for
the network set, as connect() builds them, and the image registry contract,
the node, the order and the enclave details of the network left are dropped,
so every read and every transaction of a later run goes to the contracts of
the network set, at that network's RPC and signed for its chain. A call that
raises changes nothing: a name the table does not hold (ValueError), a run or
a session in progress (RuntimeError), a provider of the network set that does
not answer (ConnectionError). No chain: the protocol contracts and the image
registries the runner builds are the real ones over a provider that answers
each read from the ABI of the function called and keeps, with the RPC URL of
the network its contract was built for, every read and every transaction it
is sent; the steps of a run after its request (the order a node places, the
task's result) are stand-ins."""
import threading
from types import SimpleNamespace

import pytest
import rlp
from eth_abi import decode, encode
from eth_account import Account
from eth_utils import function_abi_to_4byte_selector
from eth_utils.abi import get_abi_input_types, get_abi_output_types
from web3 import Web3
from web3.providers.base import BaseProvider

import ethernity_cloud_runner_py.runner as runner_module
import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py.contract.abi.ECLDAbi import contract as token_abi
from ethernity_cloud_runner_py.contract.abi.imageRegistryAbi import contract as registry_abi
from ethernity_cloud_runner_py.contract.abi.polygonProtocolAbi import contract as protocol_abi
from ethernity_cloud_runner_py.contract.operation.imageRegistryContract import ImageRegistryContract
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECNetwork, ECStatus
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

KEY = "0x" + "11" * 32
WALLET = Account.from_key(KEY).address
TX = "0x" + "ab" * 32
NONCE = 7
BASE_FEE = 20 * 10 ** 9
ORDER = 7
SECURELOCK = "my-dapp-securelock"
RESOURCES = {"taskPrice": 3, "cpu": 1, "memory": 1, "storage": 40, "bandwidth": 1, "duration": 1, "validators": 1}
# The escrow of a request for RESOURCES, in wei, and the request's arguments as the contract takes them.
ESCROW_WEI = Web3.to_wei(3, "ether")
REQUEST = (1, 1, 40, 1, 1, 1, 3, "image", "code", "input", "")
RESULT = {"success": True, "result_task_code": "SUCCESS", "result_task_code_int": 0, "value": "ok"}

AMOY = ("POLYGON", "AMOY")
AMOY_POX10 = ("POLYGON", "AMOY_POX10")
TESTNET = ("BLOXBERG", "TESTNET")
TESTNET_UNSAFE = ("BLOXBERG", "TESTNET_UNSAFE")
TESTNET_POX10 = ("BLOXBERG", "TESTNET_POX10")
MAINNET = ("BLOXBERG", "MAINNET")
SEPOLIA = ("ETHEREUM", "SEPOLIA")
# (network connected on, network set): each pair of networks on one chain, both ways, and a pair across chains.
SWITCHES = [(AMOY, AMOY_POX10), (AMOY_POX10, AMOY), (TESTNET, TESTNET_POX10), (TESTNET_POX10, TESTNET),
            (MAINNET, TESTNET_POX10), (TESTNET_POX10, MAINNET), (AMOY, TESTNET_POX10), (TESTNET_POX10, AMOY_POX10)]
EVERY_SWITCH = pytest.mark.parametrize(
    "first, second", SWITCHES, ids=[f"{a[0]} {a[1]} to {b[0]} {b[1]}" for a, b in SWITCHES])

# The functions of the protocol, the token and the image registry, by selector.
FUNCTIONS = {bytes(function_abi_to_4byte_selector(entry)): entry
             for abi in (protocol_abi["abi"], token_abi["abi"], registry_abi["abi"])
             for entry in abi if entry.get("type") == "function"}
# What a read answers where the zero value of its outputs does not do: a wallet of 1000 tokens and an image
# the registry records.
ANSWERS = {
    "balanceOf": [Web3.to_wei(1000, "ether")],
    "getLatestTrustedZoneImageCertPublicKey": ["QmTrustedzone", "trustedzone certificate", "QmTrustedzoneCompose"],
    "getLatestImageVersionPublicKey": ["QmSecurelock", "securelock certificate", "QmCompose"],
}
# The answer of a read the contract reverts.
REVERTS = object()


def _entry(network):
    return getattr(getattr(ECNetwork, network[0]), network[1])


def _zero(kind):
    """The zero value of an ABI type."""
    if kind.endswith("]"):
        return []
    if kind.startswith(("uint", "int")):
        return 0
    if kind == "bool":
        return False
    if kind == "string":
        return ""
    if kind == "address":
        return "0x" + "00" * 20
    raise AssertionError(f"no zero value for {kind}")


def _called(to, data):
    """(contract, function, arguments) of a call: the contract's address in its EIP-55 form, the ABI entry of
    the function its selector names and its decoded arguments, addresses in their EIP-55 form."""
    data = bytes.fromhex(data[2:]) if isinstance(data, str) else data
    function = FUNCTIONS[data[:4]]
    kinds = get_abi_input_types(function)
    arguments = tuple(Web3.to_checksum_address(value) if kind == "address" else value
                      for kind, value in zip(kinds, decode(kinds, data[4:])))
    return Web3.to_checksum_address(to), function, arguments


def _signed(raw):
    """(chain id, recipient, data) of a signed transaction: a type-2 one, or a legacy one signed for a chain."""
    if raw[0] == 2:
        fields = rlp.decode(raw[1:])
        return int.from_bytes(fields[0], "big"), fields[5], fields[7]
    fields = rlp.decode(raw)
    return (int.from_bytes(fields[6], "big") - 35) // 2, fields[3], fields[5]


class _Rpc(BaseProvider):
    """The RPC endpoint of a table entry. A read is answered with the test's `answers` for the function called,
    else ANSWERS' values, else the zero value of each of its outputs, and kept in `log` as ("read", RPC URL,
    contract, function, arguments); an answer that is a function is called with the read's arguments, and the
    answer REVERTS is the node's error for a call that reverts. A raw transaction is answered with TX and
    kept as ("send", RPC URL, the chain id it is signed for, contract, function, arguments); its receipt is a
    mined one without logs. An endpoint whose URL is in `down` does not answer is_connected. `wallets` keeps,
    in order, the wallet each request names or is signed by: ("nonce", address) for a transaction count,
    ("estimate", address) for a gas estimate's sender, ("call", address) for a read made from an address,
    ("signed", address) for the signer recovered from a raw transaction. Each of `hooks` is called with (RPC
    URL, method, params) before a request is answered, and with the method "is_connected" before that
    question is."""

    def __init__(self, entry, log, down, wallets, answers, hooks):
        super().__init__()
        self.url = entry.RPC_URL
        self.chain_id = entry.CHAIN_ID
        self.log = log
        self.down = down
        self.wallets = wallets
        self.answers = answers
        self.hooks = hooks

    def is_connected(self, show_traceback=False):
        for hook in list(self.hooks):
            hook(self.url, "is_connected", ())
        return self.url not in self.down

    def make_request(self, method, params):
        for hook in list(self.hooks):
            hook(self.url, method, params)
        if method == "eth_chainId":
            return self._answer(hex(self.chain_id))
        if method == "eth_call":
            to, function, arguments = _called(params[0]["to"], params[0].get("data") or params[0]["input"])
            self.log.append(("read", self.url, to, function["name"], arguments))
            if params[0].get("from"):
                self.wallets.append(("call", Web3.to_checksum_address(params[0]["from"])))
            kinds = get_abi_output_types(function)
            values = self.answers.get(function["name"], ANSWERS.get(function["name"]))
            if callable(values):
                values = values(arguments)
            if values is REVERTS:
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}
            return self._answer("0x" + encode(kinds, values or [_zero(kind) for kind in kinds]).hex())
        if method == "eth_getTransactionReceipt":
            return self._answer({"transactionHash": params[0], "status": "0x1", "blockNumber": "0x1", "logs": []})
        if method == "eth_getTransactionCount":
            self.wallets.append(("nonce", Web3.to_checksum_address(params[0])))
            return self._answer(hex(NONCE))
        if method == "eth_getBlockByNumber":
            return self._answer({"number": "0x1", "baseFeePerGas": hex(BASE_FEE)})
        if method == "eth_estimateGas":
            self.wallets.append(("estimate", Web3.to_checksum_address(params[0]["from"])))
            return self._answer(hex(50_000))
        if method == "eth_sendRawTransaction":
            chain_id, recipient, data = _signed(bytes.fromhex(params[0][2:]))
            to, function, arguments = _called(recipient, data)
            self.log.append(("send", self.url, chain_id, to, function["name"], arguments))
            self.wallets.append(("signed", Account.recover_transaction(params[0])))
            return self._answer(TX)
        raise AssertionError(f"unexpected request {method}")

    @staticmethod
    def _answer(result):
        return {"jsonrpc": "2.0", "id": 1, "result": result}


@pytest.fixture
def chain(monkeypatch, tmp_path):
    """Every protocol contract and image registry the runner module builds sends its requests to a _Rpc of
    the network it is built for. chain.log lists what the endpoints were sent, in order, chain.wallets the
    wallet each request named or was signed by, and chain.down the RPC URLs that do not answer;
    chain.answers holds a test's own answers by function name and chain.hooks the functions called before
    each request. The held cache is a directory of the test's own and no fee ceiling is set in the
    environment."""
    log, down, wallets, answers, hooks = [], set(), [], {}, []

    class Protocol(protocolContract):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.provider.provider = _Rpc(self.network_config, log, down, wallets, answers, hooks)

    class Registry(ImageRegistryContract):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.provider.provider = _Rpc(self.network_config, log, down, wallets, answers, hooks)

    monkeypatch.setattr(runner_module, "protocolContract", Protocol)
    monkeypatch.setattr(runner_module, "ImageRegistryContract", Registry)
    monkeypatch.setenv("ETHERNITY_CLOUD_HELD_DIR", str(tmp_path / "held"))
    monkeypatch.delenv("ECLD_MAX_FEE_PER_GAS", raising=False)
    return SimpleNamespace(log=log, down=down, wallets=wallets, answers=answers, hooks=hooks)


def _runner(network, connect=True, key=KEY):
    """A `network` runner with `key` and a Kubo API of its own as storage, connected unless `connect` is
    false. Its request is add_do_request with fixed metadata through the contract it holds when the request
    is made; a receipt is a mined one; a node places ORDER on the request; the task's result is RESULT."""
    runner = EthernityCloudRunner(*network)
    runner.set_private_key(key)
    runner.set_storage_ipfs("http://kubo.invalid:5001/api/v0", "writer-token")
    if connect:
        runner.connect()

    def check_order_for_task():
        runner.order_id = ORDER
        return True

    runner.create_task = lambda code: bool(runner.contract.add_do_request("image", "code", "input", "", runner.resources))
    runner.poll_transaction = lambda tx_hash, max_attempts=10: {"status": 1}
    runner.check_order_for_task = check_order_for_task
    runner.process_task = lambda: dict(RESULT)
    return runner


def _run(runner):
    """A run to its end, run() and the task thread it starts."""
    runner.run(RESOURCES, SECURELOCK, "v3", "code")
    runner.task_thread.join(10)
    assert not runner.task_thread.is_alive()
    assert runner.last_error is None
    assert runner.status == ECStatus.SUCCESS


def _expected(network, wallet=WALLET):
    """What a run of RESOURCES from `wallet` on `network` reads and sends, in order: every read at the
    network's token, PoX and image registry, the approval of the PoX on the token where the PoX is apart
    from it, the request and the approval of the order at the PoX, each at the network's RPC and each
    transaction signed for its chain."""
    entry = _entry(network)
    url, chain_id = entry.RPC_URL, entry.CHAIN_ID
    pox, token, registry = (Web3.to_checksum_address(address) for address in (
        entry.PROTOCOL_ADDRESS, entry.TOKEN_ADDRESS, entry.IMAGE_REGISTRY_CONTRACT_ADDRESS))
    walk = [
        ("read", url, token, "balanceOf", (wallet,)),
        ("read", url, pox, "_getOrdersCount", ()),
        ("read", url, registry, "getLatestTrustedZoneImageCertPublicKey", (entry.TRUSTEDZONE_IMAGE, "v3")),
        ("read", url, registry, "getLatestImageVersionPublicKey", (SECURELOCK, "v3")),
    ]
    if pox != token:
        walk += [("read", url, token, "allowance", (wallet, pox)),
                 ("send", url, chain_id, token, "approve", (pox, ESCROW_WEI))]
    return walk + [
        ("send", url, chain_id, pox, "_addDORequest", REQUEST),
        ("send", url, chain_id, pox, "_approveOrder", (ORDER,)),
        ("read", url, pox, "_getOrder", (ORDER,)),
    ]


def _held(runner):
    """What names the runner's network: the names, the table entry, the default trustedzone, the block time
    and the contract objects."""
    return (runner.network_name, runner.network_type, runner.network_config, runner.trustedZoneImage,
            runner.block_time, runner.contract, runner.protocol_contract, runner.token_contract,
            runner.image_registry_contract, runner.ipfs_client)


# ---- a run after a switch ----

@EVERY_SWITCH
def test_a_run_after_set_network_reads_and_sends_on_the_network_set(chain, first, second):
    runner = _runner(first)
    _run(runner)
    assert chain.log == _expected(first)
    del chain.log[:]
    runner.set_network(*second)
    _run(runner)
    assert chain.log == _expected(second)
    assert {wallet for _, wallet in chain.wallets} == {WALLET}


@EVERY_SWITCH
def test_a_first_run_after_set_network_reads_and_sends_on_the_network_set(chain, first, second):
    runner = _runner(first)
    runner.set_network(*second)
    assert chain.log == []
    _run(runner)
    assert chain.log == _expected(second)


@EVERY_SWITCH
def test_a_session_submitted_after_set_network_reads_and_sends_on_the_network_set(chain, monkeypatch, first, second):
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id: SimpleNamespace(order_id=order_id))
    runner = _runner(first)
    runner.set_network(*second)
    assert runner.run_session(RESOURCES, SECURELOCK, "v3", "code").order_id == ORDER
    assert chain.log == _expected(second)


def test_the_walks_of_the_two_amoy_networks_differ_in_the_pox_and_the_registry_alone():
    """Their chain, RPC and token are one, so a request sent to the other network's PoX is escrowed there."""
    at_amoy, at_pox10 = _expected(AMOY), _expected(AMOY_POX10)
    assert len(at_amoy) == len(at_pox10) == 9
    assert at_amoy != at_pox10
    assert at_amoy[0] == at_pox10[0] == (
        "read", "https://polygon-amoy-bor-rpc.publicnode.com", "0x9927809B61122B2af3f3b3A3303875e0687b8eE3",
        "balanceOf", (WALLET,))
    assert at_pox10[5] == ("send", "https://polygon-amoy-bor-rpc.publicnode.com", 80002,
                           "0x9927809B61122B2af3f3b3A3303875e0687b8eE3", "approve",
                           ("0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02", ESCROW_WEI))
    assert at_pox10[6][3:5] == ("0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02", "_addDORequest")
    assert at_amoy[5][5] == ("0xd1182deA61CDa785C320cdBE5888EaC4178cAAF2", ESCROW_WEI)
    assert at_amoy[6][3:5] == ("0xd1182deA61CDa785C320cdBE5888EaC4178cAAF2", "_addDORequest")


def test_a_switch_to_the_unsafe_twin_runs_on_the_same_contracts_with_the_unsafe_trustedzone(chain):
    runner = _runner(TESTNET)
    _run(runner)
    del chain.log[:]
    runner.set_network(*TESTNET_UNSAFE)
    runner.run(RESOURCES, f"{SECURELOCK}-unsafe", "v3", "code")
    runner.task_thread.join(10)
    assert runner.status == ECStatus.SUCCESS
    walk = _expected(TESTNET)
    walk[2] = walk[2][:4] + (("etny-pynithy-testnet-unsafe", "v3"),)
    walk[3] = walk[3][:4] + ((f"{SECURELOCK}-unsafe", "v3"),)
    assert chain.log == walk


# ---- what the runner holds after a switch ----

@EVERY_SWITCH
def test_a_connected_runner_holds_the_contracts_of_the_network_set(chain, first, second):
    runner = _runner(first)
    left = runner.contract
    runner.set_network(*second)
    entry = _entry(second)
    assert (runner.network_name, runner.network_type) == second
    assert runner.network_config is entry
    assert runner.contract is not left
    assert runner.contract.network_config is entry
    assert runner.contract.chain_id == entry.CHAIN_ID
    assert runner.contract.provider.provider.url == entry.RPC_URL
    assert runner.contract.get_protocol_address() == entry.PROTOCOL_ADDRESS
    assert runner.contract.get_token_address() == entry.TOKEN_ADDRESS
    assert runner.protocol_contract is runner.contract.protocol_contract
    assert runner.protocol_contract.address == entry.PROTOCOL_ADDRESS
    assert runner.token_contract is runner.contract.token_contract
    assert runner.token_contract.address == entry.TOKEN_ADDRESS
    assert runner.contract.signer is runner.signer
    assert runner.trustedZoneImage == entry.TRUSTEDZONE_IMAGE
    assert runner.block_time == entry.BLOCK_TIME
    assert runner.escrow_needs_allowance() is (entry.PROTOCOL_ADDRESS != entry.TOKEN_ADDRESS)
    assert chain.log == []


def test_a_read_outside_a_run_goes_to_the_pox_of_the_network_set(chain):
    runner = _runner(AMOY)
    runner.set_network(*AMOY_POX10)
    assert runner.list_sessions() == []
    assert chain.log == [("read", "https://polygon-amoy-bor-rpc.publicnode.com",
                          "0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02", "_getMyDOOrders", ())]


def test_the_network_left_keeps_nothing_of_its_last_run(chain):
    runner = _runner(AMOY)
    _run(runner)
    # What a request of the runner's own leaves beside the order: its challenge, the block it was sent
    # at, the order count it was sent after and its hash.
    runner.challenge_hash, runner.request_start_block, runner.current_order_index = b"challenge", 53_000_000, 41
    runner.do_request, runner.do_hash = 40, TX
    runner._esr_wallet_memo[SECURELOCK] = WALLET
    assert runner.image_registry_contract is not None
    assert (runner.order_id, runner.enclave_image_ipfs_hash) == (ORDER, "QmSecurelock")
    assert runner.node_address == "0x" + "00" * 20
    runner.set_network(*AMOY_POX10)
    assert runner.image_registry_contract is None
    assert (runner.order, runner.order_id, runner.do_request, runner.do_hash) == (None, -1, -1, None)
    assert (runner.challenge_hash, runner.request_start_block, runner.current_order_index) == (b"", None, 0)
    assert runner.node_address == ""
    assert (runner.enclave_image_ipfs_hash, runner.enclave_public_key,
            runner.enclave_docker_compose_ipfs_hash) == ("", "", "")
    assert runner._esr_wallet_memo == {}
    # The last run's outcome, the resources, the securelock and the key stay the runner's.
    assert runner.get_result()["value"] == "ok"
    assert runner.status == ECStatus.SUCCESS
    assert runner.resources == RESOURCES
    assert (runner.securelock_enclave, runner.securelock_version) == (SECURELOCK, "v3")
    assert runner.signer.address == WALLET


def test_the_ceiling_set_with_set_max_fee_per_gas_is_the_ceiling_on_the_network_set(chain):
    runner = _runner(AMOY)
    runner.set_max_fee_per_gas(600)
    runner.set_network(*SEPOLIA)
    assert runner.contract.fee_ceiling() == (600 * 10 ** 9, "set with set_max_fee_per_gas")


def test_without_a_ceiling_set_the_fees_are_those_of_the_network_set(chain):
    runner = _runner(AMOY)
    assert runner.contract.fee_ceiling() == (500 * 10 ** 9, "the network's default")
    runner.set_network(*SEPOLIA)
    assert runner.contract.fee_ceiling() == (15 * 10 ** 9, "the network's default")
    assert runner.contract.max_priority_fee_per_gas == 1


def test_an_unconnected_runner_is_moved_without_a_contract_and_connects_on_the_network_set(chain):
    runner = _runner(AMOY, connect=False)
    runner.set_network(*AMOY_POX10)
    assert (runner.network_name, runner.network_type) == AMOY_POX10
    assert runner.network_config is ECNetwork.POLYGON.AMOY_POX10
    assert (runner.contract, runner.protocol_contract, runner.token_contract) == (None, None, None)
    runner.connect()
    assert runner.protocol_contract.address == "0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02"
    _run(runner)
    assert chain.log == _expected(AMOY_POX10)


def test_the_block_time_is_the_one_of_the_network_set():
    runner = EthernityCloudRunner(*TESTNET)
    assert runner.block_time == 5
    runner.set_network(*AMOY)
    assert runner.block_time == 2


# ---- a call that raises changes nothing ----

IN_PROGRESS = ("A run or a session of this runner is in progress on POLYGON AMOY: set_network() is refused "
               "until the run has ended or, after a session, the session is closed with session.close(wait=True) "
               "or the runner with close(). Use another EthernityCloudRunner for POLYGON AMOY_POX10.")


def test_set_network_is_refused_while_a_run_is_in_progress(chain):
    runner = _runner(AMOY)
    reached, release = threading.Event(), threading.Event()

    def process_task():
        reached.set()
        assert release.wait(10)
        return dict(RESULT)

    runner.process_task = process_task
    runner.run(RESOURCES, SECURELOCK, "v3", "code")
    try:
        assert reached.wait(10)
        held = _held(runner)
        with pytest.raises(RuntimeError) as refusal:
            runner.set_network(*AMOY_POX10)
        assert str(refusal.value) == IN_PROGRESS
        assert _held(runner) == held
    finally:
        release.set()
        runner.task_thread.join(10)
    assert runner.status == ECStatus.SUCCESS
    assert chain.log == _expected(AMOY)
    # The run has ended: the switch is taken.
    runner.set_network(*AMOY_POX10)
    assert runner.protocol_contract.address == "0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02"


def test_set_network_is_refused_while_a_session_is_open(chain, monkeypatch):
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id: SimpleNamespace(order_id=order_id))
    runner = _runner(AMOY)
    runner.run_session(RESOURCES, SECURELOCK, "v3", "code")
    held = _held(runner)
    with pytest.raises(RuntimeError) as refusal:
        runner.set_network(*AMOY_POX10)
    assert str(refusal.value) == IN_PROGRESS
    assert _held(runner) == held
    assert runner.is_running()


def test_set_network_is_refused_while_a_submission_holds_the_runners_lock(chain):
    """run() and run_session() submit under the runner's lock, which a submission that is starting holds
    before is_running() says so."""
    runner = _runner(AMOY)
    held = _held(runner)
    with runner._run_lock:
        assert not runner.is_running()
        with pytest.raises(RuntimeError) as refusal:
            runner.set_network(*AMOY_POX10)
    assert str(refusal.value) == IN_PROGRESS
    assert _held(runner) == held
    runner.set_network(*AMOY_POX10)
    assert not runner._run_lock.locked()
    _run(runner)
    assert chain.log == _expected(AMOY_POX10)


@pytest.mark.parametrize("name, kind, message", [
    ("POLYGON", "NOPE", "Invalid network type: NOPE for network POLYGON"),
    ("NOPE", "AMOY", "Invalid network name: NOPE"),
    ("BLOXBERG", "AMOY_POX10", "Invalid network type: AMOY_POX10 for network BLOXBERG"),
])
@pytest.mark.parametrize("connect", [True, False], ids=["connected", "unconnected"])
def test_a_name_the_table_does_not_hold_leaves_the_runner_on_its_network(chain, connect, name, kind, message):
    runner = _runner(AMOY, connect=connect)
    held = _held(runner)
    with pytest.raises(ValueError, match=f"^{message}$"):
        runner.set_network(name, kind)
    assert _held(runner) == held
    assert (runner.network_name, runner.network_type) == AMOY


def test_a_provider_that_does_not_answer_leaves_the_runner_on_its_network(chain):
    runner = _runner(AMOY)
    _run(runner)
    held = _held(runner)
    order = runner.order_id
    chain.down.add(ECNetwork.BLOXBERG.TESTNET_POX10.RPC_URL)
    with pytest.raises(ConnectionError, match="^Failed to connect to Web3 provider.$"):
        runner.set_network(*TESTNET_POX10)
    assert _held(runner) == held
    assert runner.order_id == order
    chain.down.clear()
    runner.set_network(*TESTNET_POX10)
    assert runner.protocol_contract.address == "0x69A7bEB5Da2d3dA711d52E491D71e51296b08745"


def test_an_intake_client_is_rebuilt_under_the_key_of_the_network_set_on_a_connected_runner(chain):
    runner = _runner(TESTNET)
    runner.set_public_intake()
    left = runner.ipfs_client
    runner.set_network(*AMOY)
    assert runner.ipfs_client is not left
    assert runner.ipfs_client.network == "polygon_amoy"
    assert runner.ipfs_client.intake_url == left.intake_url
