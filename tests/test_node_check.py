"""The node check of a run that names its node
(EthernityCloudRunner.is_node_operator_address): the protocol contract's
_getMyDPRequests read as a call from the node's address
(protocolContract.is_node_operator, which gives web3 the address in its EIP-55
form whatever spelling the caller used). An answer decides: a node with a DP
request passes, one with none is not a node operator. A read the contract or
the RPC refuses decides nothing about the node and raises RuntimeError with
what it is: a PoX its storage does not list as an allowed caller
(EthernityCloudStorage.allowedCallers, read through the implementation's
ethStorageAddress: protocolContract.storage_admission) as out of service,
with the storage and the advice to upgrade the runner; any other failure with
the contract's address and the provider's message (errors.provider_message: a
revert by its message, not by the tuple of message and revert data web3
prints). A run and a session whose check fails end with that message
(_process_events, run_session). No chain: the runner-level cases use
stand-in contracts, raising what web3 7.6 raises (ContractLogicError for a
reverted eth_call, Web3RPCError for an RPC error that is no revert, requests'
ConnectionError for a dropped connection), and the storage_admission cases a
real Web3 over a provider that answers eth_call from a table."""
from types import SimpleNamespace

import pytest
from eth_utils import keccak
from requests.exceptions import ConnectionError as RequestsConnectionError
from web3 import Web3
from web3.exceptions import ContractLogicError, Web3RPCError
from web3.providers.base import BaseProvider

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECNetwork, ECStatus
from ethernity_cloud_runner_py.errors import provider_message
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

WALLET = "0x" + "11" * 20
NODE = "0x837EA0A09612CFF93a787db84Bbe11c65E431133"
POX = ECNetwork.BLOXBERG.TESTNET.PROTOCOL_ADDRESS
STORAGE = "0xEE3aAa1A7a8C00BeBBb5DfC570F80f6FA12a968d"
RESOURCES = {"taskPrice": 5, "cpu": 1, "memory": 1, "storage": 40, "bandwidth": 1, "duration": 1, "validators": 1}
OUT_OF_SERVICE = (f"The protocol contract {POX} is out of service: its storage {STORAGE} does not list it as an "
                  "allowed caller, so every call through it is refused. That is the state of a contract another "
                  "one has replaced: upgrade ethernity-cloud-runner-py to a release that carries the network's "
                  "current contract.")
# The storage's refusal of a call made through a contract it does not list.
GUARD = "execution reverted: Allowed caller: caller is not allowed"


def _reverted():
    """The refused read as web3 raises it on bloxberg: the guard's text and the revert data."""
    return ContractLogicError(GUARD, "Reverted 0x08c379a0" + "00" * 100)


def _rpc_error(message):
    """A Web3RPCError carrying the node's error.message: an RPC error that is no revert."""
    return Web3RPCError(f"{{'code': -32000, 'message': '{message}'}}",
                        rpc_response={"jsonrpc": "2.0", "id": 1,
                                      "error": {"code": -32000, "message": message}})


def _generic(reason):
    return (f"Could not verify the node address: the protocol contract {POX} did not answer the read of the "
            f"node's requests ({reason}).")


def _contract():
    """A BLOXBERG TESTNET protocolContract of the wallet WALLET; nothing is requested at construction."""
    return protocolContract(SimpleNamespace(address=WALLET), "BLOXBERG", "TESTNET")


def _requests_read(outcome, calls):
    """A protocol_contract whose _getMyDPRequests().call(tx) records tx and returns `outcome`, raised when it is an exception."""
    def call(tx):
        calls.append(tx)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return SimpleNamespace(functions=SimpleNamespace(_getMyDPRequests=lambda: SimpleNamespace(call=call)))


def _runner(is_node_operator, admission=None):
    """A BLOXBERG TESTNET runner whose contract answers is_node_operator with the given function and
    storage_admission with `admission`; runner.errors lists what it logged as errors."""
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.contract = SimpleNamespace(protocol_address=POX, is_node_operator=is_node_operator,
                                      storage_admission=lambda: admission)
    runner.errors = []
    runner.logger = SimpleNamespace(error=runner.errors.append, info=lambda *a: None, warning=lambda *a: None)
    return runner


def _raises(error):
    def is_node_operator(account):
        raise error
    return is_node_operator


# ---- protocolContract.is_node_operator ----

def test_is_node_operator_reads_the_requests_from_the_nodes_address():
    contract = _contract()
    calls = []
    contract.protocol_contract = _requests_read([7], calls)
    assert contract.is_node_operator(NODE) is True
    contract.protocol_contract = _requests_read([], calls)
    assert contract.is_node_operator(NODE) is False
    assert calls == [{"from": NODE}, {"from": NODE}]


@pytest.mark.parametrize("spelling", [NODE.lower(), "0x" + NODE[2:].upper(), NODE[2:]])
def test_is_node_operator_reads_from_the_eip55_form_of_any_spelling(spelling):
    contract = _contract()
    calls = []
    contract.protocol_contract = _requests_read([7], calls)
    assert contract.is_node_operator(spelling) is True
    assert calls == [{"from": NODE}]


def test_is_node_operator_raises_what_the_read_raises():
    contract = _contract()
    refused = _reverted()
    contract.protocol_contract = _requests_read(refused, [])
    with pytest.raises(ContractLogicError) as raised:
        contract.is_node_operator(NODE)
    assert raised.value is refused


# ---- protocolContract.storage_admission, through web3 ----

class _Chain(BaseProvider):
    """A provider answering eth_call from `answers`, {(to, data): result hex}, and reverting every other call;
    `requests` lists the calls made. `down` makes every call a dropped connection."""

    def __init__(self, answers, down=False):
        super().__init__()
        self.answers = answers
        self.down = down
        self.requests = []

    def make_request(self, method, params):
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(8995)}
        if method != "eth_call":
            raise AssertionError(f"unexpected request {method}")
        if self.down:
            raise RequestsConnectionError("Failed to fetch")
        call = (params[0]["to"].lower(), params[0]["data"].lower())
        self.requests.append(call)
        if call in self.answers:
            return {"jsonrpc": "2.0", "id": 1, "result": self.answers[call]}
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "execution reverted"}}


def _selector(signature):
    return "0x" + keccak(text=signature)[:4].hex()


def _word(value):
    return value.lower().replace("0x", "").rjust(64, "0")


POINTER_CALL = (POX.lower(), _selector("ethStorageAddress()"))
ALLOW_LIST_CALL = (STORAGE.lower(), _selector("allowedCallers(address)") + _word(POX))


@pytest.mark.parametrize("admitted", [False, True])
def test_storage_admission_asks_the_storage_the_implementation_names(admitted):
    contract = _contract()
    chain = _Chain({POINTER_CALL: "0x" + _word(STORAGE), ALLOW_LIST_CALL: "0x" + _word("0x1" if admitted else "0x0")})
    contract.provider = Web3(chain)
    assert contract.storage_admission() == (STORAGE, admitted)
    assert chain.requests == [POINTER_CALL, ALLOW_LIST_CALL]


def test_storage_admission_is_none_when_a_read_fails():
    # An implementation without ethStorageAddress: the read reverts.
    contract = _contract()
    without_pointer = _Chain({})
    contract.provider = Web3(without_pointer)
    assert contract.storage_admission() is None
    assert without_pointer.requests == [POINTER_CALL]
    # The storage's read reverts.
    without_allow_list = _Chain({POINTER_CALL: "0x" + _word(STORAGE)})
    contract.provider = Web3(without_allow_list)
    assert contract.storage_admission() is None
    assert without_allow_list.requests == [POINTER_CALL, ALLOW_LIST_CALL]
    # The RPC drops the connection.
    contract.provider = Web3(_Chain({}, down=True))
    assert contract.storage_admission() is None


# ---- EthernityCloudRunner.is_node_operator_address ----

def test_a_node_with_a_request_passes_and_one_without_is_not_a_node_operator():
    asked = []
    runner = _runner(lambda account: asked.append(account) or True)
    assert runner.is_node_operator_address(NODE) is True
    assert asked == [NODE]
    assert runner.errors == []
    none = _runner(lambda account: False)
    assert none.is_node_operator_address(NODE) is False
    assert none.errors == ["The target address is not a valid node operator address"]


def test_no_address_passes_without_a_read_and_a_string_that_is_no_address_does_not():
    runner = _runner(_raises(AssertionError("not to be called")))
    assert runner.is_node_operator_address("") is True
    assert runner.is_node_operator_address("0x1234") is False
    assert runner.errors == ["Introduced address is not a valid wallet address."]


# The ways the read is refused, as web3 7.6 raises them, each with the message it is reported with
# (errors.provider_message).
REFUSED_READS = [
    (_reverted(), GUARD),
    (_rpc_error("header not found"), "header not found"),
    (RequestsConnectionError("Failed to fetch"), "Failed to fetch"),
]


@pytest.mark.parametrize("error", [error for error, _ in REFUSED_READS])
def test_a_refused_read_on_a_pox_its_storage_does_not_list_is_a_contract_out_of_service(error):
    runner = _runner(_raises(error), admission=(STORAGE, False))
    with pytest.raises(RuntimeError) as raised:
        runner.is_node_operator_address(NODE)
    assert str(raised.value) == OUT_OF_SERVICE
    assert raised.value.__cause__ is error
    assert runner.errors == [OUT_OF_SERVICE]
    assert "not a valid node operator" not in OUT_OF_SERVICE


@pytest.mark.parametrize("admission", [(STORAGE, True), None])
@pytest.mark.parametrize("error, reason", REFUSED_READS)
def test_a_refused_read_otherwise_names_the_contract_and_the_providers_message(admission, error, reason):
    runner = _runner(_raises(error), admission=admission)
    with pytest.raises(RuntimeError) as raised:
        runner.is_node_operator_address(NODE)
    assert str(raised.value) == _generic(reason)
    assert raised.value.__cause__ is error
    assert runner.errors == [_generic(reason)]


def test_a_revert_is_reported_by_its_message_not_by_the_tuple_web3_prints():
    reverted = _reverted()
    assert str(reverted).startswith("('execution reverted")
    assert provider_message(reverted) == GUARD


# ---- a run and a session whose node check fails ----

def _submitting_runner(monkeypatch, admission):
    """A BLOXBERG TESTNET runner with a funded wallet whose protocol check is answered and whose node check
    read is refused; runner.calls lists that read and every later step of a submission that is reached."""
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.running = True
    runner.resources = RESOURCES
    runner.signer = SimpleNamespace(address=WALLET)
    runner.calls = []

    def is_node_operator(account):
        runner.calls.append(("requests", account))
        raise _reverted()

    runner.contract = SimpleNamespace(
        protocol_address=POX,
        get_balance=lambda: 100,
        get_orders_count=lambda: 163,
        get_protocol_address=lambda: POX,
        is_node_operator=is_node_operator,
        storage_admission=lambda: admission,
        faucet=lambda: runner.calls.append(("faucet",)),
        set_allowance=lambda tokens: runner.calls.append(("approve", tokens)))
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(
        allowance=lambda owner, spender: runner.calls.append(("allowance",)) or SimpleNamespace(call=lambda: 10**30)))
    runner.check_web3_connection = lambda: runner.calls.append(("web3",)) or True
    runner.get_enclave_details = lambda: runner.calls.append(("enclave",)) or True
    runner.create_task = lambda code: runner.calls.append(("task",)) or True
    runner._resolve_storage = lambda: None
    monkeypatch.setattr(runner_module, "ImageRegistryContract",
                        lambda *args: runner.calls.append(("registry",)) or SimpleNamespace())
    return runner


@pytest.mark.parametrize("admission, expected", [
    ((STORAGE, False), OUT_OF_SERVICE),
    ((STORAGE, True), _generic(GUARD)),
    (None, _generic(GUARD)),
])
def test_a_run_whose_node_check_read_fails_ends_with_the_checks_message(monkeypatch, admission, expected):
    runner = _submitting_runner(monkeypatch, admission)
    runner._populate_event_queue()
    runner._process_events("code", NODE, RESOURCES)
    assert runner.status == ECStatus.ERROR
    assert runner.last_error == expected
    assert runner.processed_events == []
    assert runner.calls == [("requests", NODE)]
    assert runner.running is False


def test_a_session_whose_node_check_read_fails_raises_the_checks_message(monkeypatch):
    runner = _submitting_runner(monkeypatch, (STORAGE, False))
    with pytest.raises(RuntimeError) as raised:
        runner.run_session(RESOURCES, "securelock", "v1", "code", NODE)
    assert str(raised.value) == OUT_OF_SERVICE
    assert runner.calls == [("requests", NODE)]
    assert runner.running is False
