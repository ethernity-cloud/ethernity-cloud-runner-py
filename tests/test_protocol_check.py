"""The protocol check before a DO request
(EthernityCloudRunner.verify_protocol), which the INIT step of each attempt
of a run, the resubmission after an operator fault among them, and
run_session make after the balance check and before the node check, the
registry lookup and the allowance step, on the network whose protocol is its
token as on the others: the PoX's order count is read
(protocolContract.get_orders_count), and an answer lets the submission go on.
A read that fails on a PoX its storage does not list as an allowed caller
(out_of_service_message, over protocolContract.storage_admission) raises
RuntimeError at once with the message the node check gives for such a
contract, so the submission ends before the escrow is approved for it; any
other failed read is tried PRE_REQUEST_READ_ATTEMPTS times,
PRE_REQUEST_READ_RETRY_SECONDS apart, with a warning per failed try
(_read_before_request), and then raises RuntimeError naming the contract and
the provider's message (errors.provider_message). No chain: the runner-level
cases use stand-in contracts raising what web3 7.6 raises (ContractLogicError
for a reverted eth_call, Web3RPCError for an RPC error that is no revert,
requests' ConnectionError for a dropped connection), and the web3-level cases
a real protocolContract whose Web3 sends its requests to a provider answering
eth_call from a table, the storage's refusal in the forms the bloxberg and
Polygon Amoy RPCs give it; the clock is a stand-in."""
from types import SimpleNamespace

import pytest
from eth_utils import keccak
from requests.exceptions import ConnectionError as RequestsConnectionError
from web3 import Web3
from web3.exceptions import ContractLogicError, Web3RPCError
from web3.providers.base import BaseProvider

import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECEvent, ECNetwork, ECStatus
from ethernity_cloud_runner_py.errors import provider_message
from ethernity_cloud_runner_py.runner import (
    EthernityCloudRunner,
    PRE_REQUEST_READ_ATTEMPTS,
    PRE_REQUEST_READ_RETRY_SECONDS,
)

WALLET = "0x" + "11" * 20
NODE = "0x837EA0A09612CFF93a787db84Bbe11c65E431133"
POX = ECNetwork.BLOXBERG.TESTNET.PROTOCOL_ADDRESS
TOKEN = ECNetwork.BLOXBERG.TESTNET.TOKEN_ADDRESS
STORAGE = "0xEE3aAa1A7a8C00BeBBb5DfC570F80f6FA12a968d"
TX = "0x" + "ab" * 32
ESCROW = 5
RESOURCES = {"taskPrice": ESCROW, "cpu": 1, "memory": 1, "storage": 40, "bandwidth": 1, "duration": 1, "validators": 1}
# An order count a PoX in service answers.
ORDERS = 163
# The line verify_protocol logs at INFO, once per check, before it reads the order count.
CHECKING = "Checking the protocol contract..."
OUT_OF_SERVICE = (f"The protocol contract {POX} is out of service: its storage {STORAGE} does not list it as an "
                  "allowed caller, so every call through it is refused. That is the state of a contract another "
                  "one has replaced: upgrade ethernity-cloud-runner-py to a release that carries the network's "
                  "current contract.")
# The storage's refusal of a call made through a contract it does not list: its text, the message web3
# gives the revert, the revert data (Error(string)), and the error object each RPC answers the eth_call
# with (bloxberg.ethernity.cloud, polygon-amoy-bor-rpc.publicnode.com).
GUARD_TEXT = "Allowed caller: caller is not allowed"
GUARD = f"execution reverted: {GUARD_TEXT}"
REVERT_DATA = "0x08c379a0" + Web3().codec.encode(["string"], [GUARD_TEXT]).hex()
BLOXBERG_REFUSAL = {"code": -32015, "message": "VM execution error.", "data": f"Reverted {REVERT_DATA}"}
AMOY_REFUSAL = {"code": 3, "message": GUARD, "data": REVERT_DATA}


def _reverted():
    """The refused read as web3 raises it on bloxberg: the guard's text and the revert data."""
    return ContractLogicError(GUARD, f"Reverted {REVERT_DATA}")


def _rpc_error(message):
    """A Web3RPCError carrying the node's error.message: an RPC error that is no revert."""
    return Web3RPCError(f"{{'code': -32000, 'message': '{message}'}}",
                        rpc_response={"jsonrpc": "2.0", "id": 1,
                                      "error": {"code": -32000, "message": message}})


def _dropped(message="Failed to fetch"):
    """The error requests raises for a connection the RPC drops."""
    return RequestsConnectionError(message)


def _unanswered(reason):
    return f"The protocol contract {POX} did not answer the read of its order count ({reason})."


def _reads(*outcomes):
    """A stand-in for a read of the contract: the n-th call gets the n-th outcome, whatever its arguments,
    raised when it is an exception, returned otherwise. Its .pending lists the outcomes no call has taken."""
    pending = list(outcomes)

    def read(*args):
        outcome = pending.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    read.pending = pending
    return read


def _runner(monkeypatch, orders_count, storage_admission=None):
    """A BLOXBERG TESTNET runner whose contract reads the order count with `orders_count` and asks the
    storage with `storage_admission`, _reads stand-ins both; without the second the storage answers no
    question. runner.infos and runner.warnings list what it logged, and runner.sleeps the sleeps it asked
    for, none of them slept."""
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.contract = SimpleNamespace(protocol_address=POX, get_orders_count=orders_count,
                                      storage_admission=storage_admission or _reads())
    runner.infos, runner.warnings, runner.sleeps = [], [], []
    runner.logger = SimpleNamespace(info=runner.infos.append, warning=runner.warnings.append,
                                    error=lambda *a: None)
    monkeypatch.setattr(runner_module.time, "sleep", runner.sleeps.append)
    return runner


# The ways a read fails, as web3 7.6 raises them, each with the message it is reported with
# (errors.provider_message).
READ_FAILURES = [
    (_reverted(), GUARD),
    (_rpc_error("header not found"), "header not found"),
    (_dropped(), "Failed to fetch"),
]
READ_FAILURE_IDS = ["revert", "rpc error", "dropped"]
FAILED_READS = pytest.mark.parametrize("error, reason", READ_FAILURES, ids=READ_FAILURE_IDS)
# The same failures alone, for the cases whose outcome does not carry that message.
READ_ERRORS = pytest.mark.parametrize("error", [error for error, _ in READ_FAILURES], ids=READ_FAILURE_IDS)
# What the storage answers about a PoX in service, and a storage that gives no answer.
ADMISSIONS = pytest.mark.parametrize("admission", [(STORAGE, True), None], ids=["listed", "unread"])


# ---- EthernityCloudRunner.verify_protocol ----

def test_an_order_count_that_answers_lets_the_submission_go_on_without_a_question_to_the_storage(monkeypatch):
    orders_count = _reads(ORDERS)
    runner = _runner(monkeypatch, orders_count)
    assert runner.verify_protocol() is None
    assert orders_count.pending == []
    assert runner.infos == [CHECKING]
    assert runner.warnings == []
    assert runner.sleeps == []


def test_the_check_logs_its_line_before_it_reads_the_order_count(monkeypatch):
    runner = _runner(monkeypatch, _reads(ORDERS))
    read = runner.contract.get_orders_count
    logged_at_the_read = []
    runner.contract.get_orders_count = lambda: logged_at_the_read.extend(runner.infos) or read()
    runner.verify_protocol()
    assert logged_at_the_read == [CHECKING]


@READ_ERRORS
def test_a_read_that_fails_on_a_pox_its_storage_does_not_list_ends_the_check_at_once(monkeypatch, error):
    orders_count = _reads(error, ORDERS)
    storage_admission = _reads((STORAGE, False))
    runner = _runner(monkeypatch, orders_count, storage_admission)
    with pytest.raises(RuntimeError) as raised:
        runner.verify_protocol()
    assert str(raised.value) == OUT_OF_SERVICE
    assert raised.value.__cause__ is error
    assert orders_count.pending == [ORDERS]
    assert storage_admission.pending == []
    assert runner.infos == [CHECKING]
    assert runner.warnings == []
    assert runner.sleeps == []


@ADMISSIONS
@FAILED_READS
def test_a_read_that_fails_and_then_answers_passes_with_a_warning(monkeypatch, admission, error, reason):
    orders_count = _reads(error, ORDERS)
    storage_admission = _reads(admission)
    runner = _runner(monkeypatch, orders_count, storage_admission)
    runner.verify_protocol()
    assert orders_count.pending == []
    assert storage_admission.pending == []
    assert runner.infos == [CHECKING]
    assert runner.warnings == [f"Retry 1/{PRE_REQUEST_READ_ATTEMPTS}: {_unanswered(reason)}"]
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS]


@ADMISSIONS
@FAILED_READS
def test_a_read_no_try_answers_names_the_contract_and_the_providers_message(monkeypatch, admission, error, reason):
    orders_count = _reads(_dropped("first"), _dropped("second"), error, ORDERS)
    storage_admission = _reads(admission, admission, admission)
    runner = _runner(monkeypatch, orders_count, storage_admission)
    with pytest.raises(RuntimeError) as raised:
        runner.verify_protocol()
    assert str(raised.value) == _unanswered(reason)
    assert raised.value.__cause__ is error
    assert orders_count.pending == [ORDERS]
    assert storage_admission.pending == []
    assert runner.infos == [CHECKING]
    assert runner.warnings == [f"Retry {attempt}/{PRE_REQUEST_READ_ATTEMPTS}: {_unanswered(failure)}"
                               for attempt, failure in enumerate(("first", "second", reason), 1)]
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS] * (PRE_REQUEST_READ_ATTEMPTS - 1)


@READ_ERRORS
def test_a_pox_found_out_of_service_on_a_later_try_ends_the_check_there(monkeypatch, error):
    orders_count = _reads(_dropped("first"), error, ORDERS)
    storage_admission = _reads(None, (STORAGE, False))
    runner = _runner(monkeypatch, orders_count, storage_admission)
    with pytest.raises(RuntimeError) as raised:
        runner.verify_protocol()
    assert str(raised.value) == OUT_OF_SERVICE
    assert raised.value.__cause__ is error
    assert orders_count.pending == [ORDERS]
    assert storage_admission.pending == []
    assert runner.infos == [CHECKING]
    assert runner.warnings == [f"Retry 1/{PRE_REQUEST_READ_ATTEMPTS}: {_unanswered('first')}"]
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS]


# ---- EthernityCloudRunner.out_of_service_message ----

@pytest.mark.parametrize("admission, message", [
    ((STORAGE, False), OUT_OF_SERVICE),
    ((STORAGE, True), None),
    (None, None),
], ids=["not listed", "listed", "unread"])
def test_a_pox_is_out_of_service_when_its_storage_answers_that_it_does_not_list_it(monkeypatch, admission, message):
    storage_admission = _reads(admission)
    runner = _runner(monkeypatch, _reads(), storage_admission)
    assert runner.out_of_service_message() == message
    assert storage_admission.pending == []


def test_the_node_check_names_a_pox_out_of_service_with_the_protocol_checks_message(monkeypatch):
    runner = _runner(monkeypatch, _reads(_reverted()), _reads((STORAGE, False), (STORAGE, False)))
    runner.contract.is_node_operator = _reads(_reverted())
    with pytest.raises(RuntimeError) as protocol_check:
        runner.verify_protocol()
    with pytest.raises(RuntimeError) as node_check:
        runner.is_node_operator_address(NODE)
    assert str(protocol_check.value) == OUT_OF_SERVICE
    assert str(node_check.value) == OUT_OF_SERVICE


# ---- through web3 ----

class _Chain(BaseProvider):
    """A provider answering eth_call from `answers`, {(to, data): the result hex, the error object of a
    refused call, or the exception of a failed request}, and reverting every other call without a
    reason; `requests` lists the calls made."""

    def __init__(self, answers):
        super().__init__()
        self.answers = answers
        self.requests = []

    def make_request(self, method, params):
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(8995)}
        if method != "eth_call":
            raise AssertionError(f"unexpected request {method}")
        call = (params[0]["to"].lower(), params[0]["data"].lower())
        self.requests.append(call)
        answer = self.answers.get(call, {"code": -32000, "message": "execution reverted"})
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, dict):
            return {"jsonrpc": "2.0", "id": 1, "error": answer}
        return {"jsonrpc": "2.0", "id": 1, "result": answer}


def _selector(signature):
    return "0x" + keccak(text=signature)[:4].hex()


def _word(value):
    return value.lower().replace("0x", "").rjust(64, "0")


BALANCE_CALL = (TOKEN.lower(), _selector("balanceOf(address)") + _word(WALLET))
ORDERS_CALL = (POX.lower(), _selector("_getOrdersCount()"))
POINTER_CALL = (POX.lower(), _selector("ethStorageAddress()"))
ALLOW_LIST_CALL = (STORAGE.lower(), _selector("allowedCallers(address)") + _word(POX))
ORDERS_ANSWER = "0x" + _word(hex(ORDERS))
# The answers about a PoX its storage does not list: the storage it names, and that storage's allow-list.
NOT_LISTED = {POINTER_CALL: "0x" + _word(STORAGE), ALLOW_LIST_CALL: "0x" + _word("0x0")}


def _contract(chain):
    """A BLOXBERG TESTNET protocolContract of the wallet WALLET whose Web3 sends its requests to `chain`."""
    contract = protocolContract(SimpleNamespace(address=WALLET), "BLOXBERG", "TESTNET")
    contract.provider.provider = chain
    return contract


def _web3_runner(monkeypatch, chain):
    """A BLOXBERG TESTNET runner connected to `chain` through _contract; runner.sleeps lists the sleeps it
    asked for, none of them slept."""
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.contract = _contract(chain)
    runner.token_contract = runner.contract.token_contract
    runner.signer = runner.contract.signer
    runner.sleeps = []
    monkeypatch.setattr(runner_module.time, "sleep", runner.sleeps.append)
    return runner


def test_get_orders_count_reads_the_order_count_of_the_pox():
    chain = _Chain({ORDERS_CALL: ORDERS_ANSWER})
    assert _contract(chain).get_orders_count() == ORDERS
    assert chain.requests == [ORDERS_CALL]


@pytest.mark.parametrize("answer, raised_type, reason", [
    (BLOXBERG_REFUSAL, ContractLogicError, GUARD),
    (AMOY_REFUSAL, ContractLogicError, GUARD),
    ({"code": -32000, "message": "header not found"}, Web3RPCError, "header not found"),
    (_dropped(), RequestsConnectionError, "Failed to fetch"),
], ids=["bloxberg refusal", "amoy refusal", "rpc error", "dropped"])
def test_get_orders_count_raises_what_the_read_raises(answer, raised_type, reason):
    chain = _Chain({ORDERS_CALL: answer})
    with pytest.raises(Exception) as raised:
        _contract(chain).get_orders_count()
    assert type(raised.value) is raised_type
    assert provider_message(raised.value) == reason
    assert chain.requests == [ORDERS_CALL]


def test_the_check_of_a_pox_in_service_is_one_call(monkeypatch):
    chain = _Chain({ORDERS_CALL: ORDERS_ANSWER})
    _web3_runner(monkeypatch, chain).verify_protocol()
    assert chain.requests == [ORDERS_CALL]


@pytest.mark.parametrize("refusal", [BLOXBERG_REFUSAL, AMOY_REFUSAL], ids=["bloxberg", "amoy"])
def test_the_check_asks_the_storage_about_a_refused_read_and_names_the_pox_out_of_service(monkeypatch, refusal):
    chain = _Chain({ORDERS_CALL: refusal, **NOT_LISTED})
    runner = _web3_runner(monkeypatch, chain)
    with pytest.raises(RuntimeError) as raised:
        runner.verify_protocol()
    assert str(raised.value) == OUT_OF_SERVICE
    assert type(raised.value.__cause__) is ContractLogicError
    assert raised.value.__cause__.message == GUARD
    assert chain.requests == [ORDERS_CALL, POINTER_CALL, ALLOW_LIST_CALL]
    assert runner.sleeps == []


def test_the_check_of_a_pox_that_names_no_storage_tries_a_refused_read_again(monkeypatch):
    chain = _Chain({})
    runner = _web3_runner(monkeypatch, chain)
    with pytest.raises(RuntimeError) as raised:
        runner.verify_protocol()
    assert str(raised.value) == _unanswered("execution reverted")
    assert chain.requests == [ORDERS_CALL, POINTER_CALL] * PRE_REQUEST_READ_ATTEMPTS
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS] * (PRE_REQUEST_READ_ATTEMPTS - 1)


def test_a_run_on_a_pox_its_storage_does_not_list_asks_the_chain_four_reads_and_nothing_else(monkeypatch):
    chain = _Chain({BALANCE_CALL: "0x" + _word(hex(Web3.to_wei(100, "ether"))),
                    ORDERS_CALL: BLOXBERG_REFUSAL, **NOT_LISTED})
    runner = _web3_runner(monkeypatch, chain)
    runner.running = True
    runner.resources = RESOURCES
    runner._populate_event_queue()
    runner._process_events("code", "", RESOURCES)
    assert runner.status == ECStatus.ERROR
    assert runner.last_error == OUT_OF_SERVICE
    assert chain.requests == [BALANCE_CALL, ORDERS_CALL, POINTER_CALL, ALLOW_LIST_CALL]
    assert runner.running is False


# ---- a run and a session ----

def _submitting_runner(monkeypatch, orders_count, storage_admission=None, network=("BLOXBERG", "TESTNET")):
    """A runner of `network` (its name and type) with a funded wallet that holds no allowance for the
    PoX, whose contract, at the network's protocol address, reads the order count with `orders_count` and
    asks the storage with `storage_admission` (_reads stand-ins, as in _runner). runner.calls lists, in
    order, the steps of a submission that are reached: the balance read, each read of the order count, the
    node check's read with the node, the registry, the connection check, the enclave lookup, the allowance
    read, the approval with its tokens and the wait for it, and the DO request. No sleep is slept."""
    runner = EthernityCloudRunner(*network)
    runner.running = True
    runner.resources = RESOURCES
    runner.signer = SimpleNamespace(address=WALLET)
    runner.calls = []

    def step(name, answer=True):
        return lambda *args, **kwargs: runner.calls.append((name,)) or answer

    def get_orders_count():
        runner.calls.append(("orders",))
        return orders_count()

    def check_order_for_task():
        runner.order_id = 7
        return True

    runner.contract = SimpleNamespace(
        protocol_address=runner.network_config.PROTOCOL_ADDRESS,
        get_balance=step("balance", 100),
        get_orders_count=get_orders_count,
        storage_admission=storage_admission or _reads(),
        get_protocol_address=lambda: runner.network_config.PROTOCOL_ADDRESS,
        is_node_operator=lambda account: runner.calls.append(("requests", account)) or True,
        set_allowance=lambda tokens: runner.calls.append(("approve", tokens)) or TX)
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(
        allowance=lambda owner, spender: SimpleNamespace(call=step("allowance", 0))))
    runner.poll_transaction = step("wait", {"status": 1})
    runner.check_web3_connection = step("web3")
    runner.get_enclave_details = step("enclave")
    runner.create_task = step("task")
    runner.check_order_for_task = check_order_for_task
    runner.approve_task = lambda: True
    runner._resolve_storage = lambda: None
    monkeypatch.setattr(runner_module, "ImageRegistryContract", step("registry", SimpleNamespace()))
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id: SimpleNamespace(order_id=order_id))
    monkeypatch.setattr(runner_module.time, "sleep", lambda seconds: None)
    return runner


def _init_step(runner, node):
    """The INIT step of a run attempt that names `node`."""
    runner.event_queue.put(ECEvent.INIT)
    runner._run_attempt("code", node, RESOURCES)
    assert runner.processed_events == ["INIT"]


def _session_submission(runner, node):
    """A session's submission, up to the order's approval, that names `node`."""
    assert runner.run_session(RESOURCES, "securelock", "v1", "code", node).order_id == 7


def _failed_run(runner, node):
    """A run that names `node`, to its end; returns the error it ends with."""
    runner._populate_event_queue()
    runner._process_events("code", node, RESOURCES)
    assert runner.status == ECStatus.ERROR
    return runner.last_error


def _failed_session(runner, node):
    """A session's submission that names `node`; returns the message of the RuntimeError it raises."""
    with pytest.raises(RuntimeError) as raised:
        runner.run_session(RESOURCES, "securelock", "v1", "code", node)
    return str(raised.value)


SUBMISSIONS = pytest.mark.parametrize("submission", [_init_step, _session_submission], ids=["init", "session"])
FAILED_SUBMISSIONS = pytest.mark.parametrize("submission", [_failed_run, _failed_session], ids=["run", "session"])
NODES = pytest.mark.parametrize("node", ["", NODE], ids=["no node", "node named"])


@SUBMISSIONS
def test_the_protocol_is_checked_after_the_balance_and_before_every_other_step(monkeypatch, submission):
    runner = _submitting_runner(monkeypatch, _reads(ORDERS))
    submission(runner, NODE)
    assert runner.calls == [("balance",), ("orders",), ("requests", NODE), ("registry",), ("web3",),
                            ("enclave",), ("allowance",), ("approve", ESCROW), ("wait",), ("task",)]


@SUBMISSIONS
def test_the_protocol_is_checked_on_the_network_whose_protocol_is_its_token(monkeypatch, submission):
    # The bloxberg mainnet, where no allowance is read or approved.
    runner = _submitting_runner(monkeypatch, _reads(ORDERS), network=("BLOXBERG", "MAINNET"))
    submission(runner, "")
    assert runner.calls == [("balance",), ("orders",), ("registry",), ("web3",), ("enclave",), ("task",)]


@FAILED_SUBMISSIONS
@NODES
def test_a_submission_on_a_pox_its_storage_does_not_list_ends_before_the_allowance_step(monkeypatch, submission, node):
    runner = _submitting_runner(monkeypatch, _reads(_reverted()), _reads((STORAGE, False)))
    error = submission(runner, node)
    assert runner.calls == [("balance",), ("orders",)]
    assert error == OUT_OF_SERVICE
    assert runner.running is False


@FAILED_SUBMISSIONS
def test_a_submission_whose_protocol_check_no_try_answers_ends_before_the_allowance_step(monkeypatch, submission):
    orders_count = _reads(_dropped(), _dropped(), _rpc_error("header not found"))
    runner = _submitting_runner(monkeypatch, orders_count, _reads(None, None, (STORAGE, True)))
    error = submission(runner, "")
    assert runner.calls == [("balance",)] + [("orders",)] * PRE_REQUEST_READ_ATTEMPTS
    assert error == _unanswered("header not found")
    assert runner.running is False


def test_a_resubmission_on_a_pox_its_storage_does_not_list_ends_before_a_second_approval(monkeypatch):
    # The first attempt's read of the order count is answered and its node gives no result; the
    # resubmission's read is refused, and the storage does not list the PoX.
    runner = _submitting_runner(monkeypatch, _reads(ORDERS, _reverted()), _reads((STORAGE, False)))
    runner.max_retries = 1
    runner.retry_delay = 0

    def process_task():
        runner._fault = "the node withheld the result"
        return None

    runner.process_task = process_task
    assert _failed_run(runner, "") == OUT_OF_SERVICE
    assert runner.calls == [("balance",), ("orders",), ("registry",), ("web3",), ("enclave",), ("allowance",),
                            ("approve", ESCROW), ("wait",), ("task",), ("balance",), ("orders",)]
    assert runner.running is False
