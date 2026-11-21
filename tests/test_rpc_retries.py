"""What the runner asks again of an RPC that does not serve a request, now
that web3 sends each request once (rpc.rpc_provider).

A send hands its signed transaction to the node again, the same bytes, while
the hand-over is not answered: an HTTP 429 or 503, a connection reset, an
HTTP 504 or a read timeout after the node took it. A node that holds the
transaction already, or has mined it, gives its hash back, and no second
transaction is built. attach_session()'s reads of the order and its request,
esr_version and esr_nonce, the node check and the question whether the RPC
answers (connect, set_network, check_web3_connection) are asked again while
the RPC does not serve them; a revert is raised at once.

No chain: the node of the send cases is a provider that keeps a pool of the
transactions it took; the other cases use test_set_network.py's chain."""
import threading
from types import SimpleNamespace

import pytest
import requests
from eth_account import Account
from eth_utils import keccak
from web3.exceptions import ContractLogicError
from web3.providers.base import BaseProvider

import ethernity_cloud_runner_py.contract.operation.protocolContract as protocol_module
import ethernity_cloud_runner_py.rpc as rpc_module
import ethernity_cloud_runner_py.runner as runner_module
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.errors import RunEndedError
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession

from test_set_network import AMOY, AMOY_POX10, ORDER, REVERTS, _called, _entry, _runner, chain  # noqa: F401
from test_runner_lifetime import _in_session

SIGNER = Account.from_key("0x" + "11" * 32)
NONCE = 7
GWEI = 10 ** 9
TESTNET = ("BLOXBERG", "TESTNET")
GETH_HELD = {"code": -32000, "message": "already known"}
PARITY_HELD = {"code": -32010, "message": "Transaction with the same hash was already imported."}


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    """The waits between two hand-overs and between two reads take no time."""
    monkeypatch.setattr(protocol_module, "HANDOVER_RETRY_SECONDS", 0)
    monkeypatch.setattr(rpc_module, "RPC_READ_RETRY_SECONDS", 0)


class _Node(BaseProvider):
    """A node of chain `chain_id` with a pool of the transactions it took (by hash) and a pending nonce that each
    taken transaction raises. Each hand-over (eth_sendRawTransaction) is answered as the next of `handovers`
    says: "take" takes the transaction and answers its hash; "429", "503" and "reset" do not take it and raise
    the requests error of an HTTP 429, an HTTP 503 and a connection reset; "504" and "slow" take it and raise the
    error of an HTTP 504 and of a read timeout; "mined 504" takes and mines it and raises the HTTP 504 error.
    Once `handovers` is spent a hand-over takes. A transaction in the pool is answered with `held`, or with
    "nonce too low" once mined. `handed` lists the raw bytes of every hand-over and `reads` every method asked
    but the hand-overs."""

    def __init__(self, chain_id, handovers, held=GETH_HELD):
        super().__init__()
        self.chain_id = chain_id
        self.handovers = list(handovers)
        self.held = held
        self.pool, self.mined, self.handed, self.reads = {}, set(), [], []

    def is_connected(self, show_traceback=False):
        return True

    def make_request(self, method, params):
        if method != "eth_sendRawTransaction":
            self.reads.append(method)
        if method == "eth_chainId":
            return self._answer(hex(self.chain_id))
        if method == "eth_getTransactionCount":
            return self._answer(hex(NONCE + len(self.pool)))
        if method == "eth_getBlockByNumber":
            return self._answer({"number": "0x1", "baseFeePerGas": hex(20 * GWEI)})
        if method == "eth_estimateGas":
            return self._answer(hex(50_000))
        if method == "eth_getTransactionByHash":
            return self._answer({"hash": params[0]} if params[0] in self.pool else None)
        if method == "eth_sendRawTransaction":
            raw = bytes.fromhex(params[0][2:])
            self.handed.append(raw)
            tx_hash = "0x" + keccak(raw).hex()
            if tx_hash in self.pool:
                error = {"code": -32000, "message": "nonce too low"} if tx_hash in self.mined else self.held
                return {"jsonrpc": "2.0", "id": 1, "error": error}
            answer = self.handovers.pop(0) if self.handovers else "take"
            if answer in ("429", "503"):
                raise requests.exceptions.HTTPError(f"{answer} Server Error for url: RPC")
            if answer == "reset":
                raise requests.exceptions.ConnectionError("Connection aborted.")
            self.pool[tx_hash] = raw
            if answer == "mined 504":
                self.mined.add(tx_hash)
            if answer in ("504", "mined 504"):
                raise requests.exceptions.HTTPError("504 Server Error: Gateway Timeout for url: RPC")
            if answer == "slow":
                raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)")
            return self._answer(tx_hash)
        raise AssertionError(f"unexpected request {method}")

    @staticmethod
    def _answer(result):
        return {"jsonrpc": "2.0", "id": 1, "result": result}


def _contract(node, network=AMOY):
    contract = protocolContract(SIGNER, *network)
    contract.provider.provider = node
    return contract


def _taken(node):
    """The hash of the one transaction the node took."""
    hashes = list(node.pool)
    assert len(hashes) == 1, hashes
    return hashes[0]


# ---- the hand-over of a send ----

@pytest.mark.parametrize("refusal", ["429", "503", "reset"])
def test_a_hand_over_the_rpc_did_not_take_is_made_again_with_the_same_transaction(refusal):
    node = _Node(80002, [refusal])
    assert _contract(node).approve_order(ORDER) == _taken(node)
    assert len(node.handed) == 2 and node.handed[0] == node.handed[1]
    assert node.reads.count("eth_getTransactionCount") == 1


@pytest.mark.parametrize("lost", ["504", "slow"])
def test_a_hand_over_whose_answer_was_lost_is_followed_by_no_second_transaction(lost):
    """The node took the transaction and its answer did not reach the runner; the same bytes go to it again,
    and its "already known" gives the hash back."""
    node = _Node(80002, [lost])
    assert _contract(node).set_allowance(3) == _taken(node)
    assert len(node.handed) == 2 and node.handed[0] == node.handed[1]
    assert node.reads.count("eth_getTransactionCount") == 1


def test_bloxbergs_answer_for_a_transaction_it_holds_gives_its_hash_back():
    node = _Node(8995, ["504"], held=PARITY_HELD)
    assert _contract(node, TESTNET).approve_order(ORDER) == _taken(node)
    assert len(node.handed) == 2


def test_a_transaction_mined_before_its_answer_was_lost_is_found_by_its_hash():
    node = _Node(80002, ["mined 504"])
    assert _contract(node).approve_order(ORDER) == _taken(node)
    assert node.reads.count("eth_getTransactionByHash") == 1
    assert node.reads.count("eth_getTransactionCount") == 1


def test_a_send_no_hand_over_of_which_is_answered_raises_and_builds_no_second_transaction():
    node = _Node(80002, ["429"] * protocol_module.HANDOVER_ATTEMPTS)
    with pytest.raises(Exception, match="^Unable to send transaction: 429 Server Error"):
        _contract(node).approve_order(ORDER)
    assert len(node.handed) == protocol_module.HANDOVER_ATTEMPTS
    assert len(set(node.handed)) == 1
    assert node.pool == {}
    assert node.reads.count("eth_getTransactionCount") == 1


def test_a_contract_retired_between_two_hand_overs_hands_nothing_more_over(monkeypatch):
    node = _Node(80002, ["503"])
    contract = _contract(node)
    monkeypatch.setattr(protocol_module, "time", SimpleNamespace(sleep=lambda seconds: contract.retire("Retired")))
    with pytest.raises(RunEndedError):
        contract.approve_order(ORDER)
    assert len(node.handed) == 1 and node.pool == {}


# ---- the reads asked again ----

def _miss_once(chain, function):
    """The first read of `function` is not served (a connection reset); the list given counts its reads."""
    reads = []

    def hook(url, method, params):
        if method == "eth_call" and _called(params[0]["to"], params[0].get("data") or params[0]["input"])[1][
                "name"] == function:
            reads.append(function)
            if len(reads) == 1:
                raise requests.exceptions.ConnectionError("Connection aborted.")
    chain.hooks.append(hook)
    return reads


@pytest.mark.parametrize("function", ["_getOrder", "_getDORequestMetadata"])
def test_attach_session_reads_the_order_and_its_request_again_after_a_read_the_rpc_did_not_serve(chain, function):
    _in_session(chain)
    runner = _runner(AMOY)
    reads = _miss_once(chain, function)
    session = runner.attach_session(ORDER)
    assert isinstance(session, EthernityCloudSession) and session.order_id == ORDER
    assert len(reads) >= 2


def test_attach_session_raises_a_revert_of_the_order_read_at_once(chain):
    _in_session(chain)
    chain.answers["_getOrder"] = REVERTS
    runner = _runner(AMOY)
    del chain.log[:]
    with pytest.raises(ContractLogicError):
        runner.attach_session(ORDER)
    assert [entry[3] for entry in chain.log] == ["_getOrder"]


class _Registry:
    """Stands for ESRContract: the first read of the state and of the nonce is not served (an HTTP 429)."""
    missed = []

    def __init__(self, network_name, network_type):
        pass

    def _miss(self, read):
        if read not in _Registry.missed:
            _Registry.missed.append(read)
            raise requests.exceptions.HTTPError("429 Client Error: Too Many Requests for url: RPC")

    def get_state(self, wallet, key):
        self._miss("state")
        return {"cid": "", "version": 4, "updated_at": 1, "valid": False}

    def get_nonce(self, wallet, key):
        self._miss("nonce")
        return 9


def test_esr_version_and_esr_nonce_read_again_after_a_read_the_rpc_did_not_serve(monkeypatch):
    monkeypatch.setattr(runner_module, "ESRContract", _Registry)
    monkeypatch.setattr(_Registry, "missed", [])
    runner = EthernityCloudRunner(*AMOY)
    wallet = "0x" + "5e" * 20
    assert runner.esr_version("counter", enclave_wallet=wallet)["version"] == 4
    assert runner.esr_nonce("counter", enclave_wallet=wallet)["nonce"] == 9
    assert _Registry.missed == ["state", "nonce"]


def test_the_node_check_reads_the_nodes_requests_again_after_a_read_the_rpc_did_not_serve():
    answers = [requests.exceptions.ReadTimeout("Read timed out."), True]

    def is_node_operator(account):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    runner = EthernityCloudRunner(*TESTNET)
    runner.contract = SimpleNamespace(protocol_address="0x" + "33" * 20, is_node_operator=is_node_operator,
                                      storage_admission=lambda: None)
    assert runner.is_node_operator_address("0x" + "22" * 20) is True
    assert answers == []


def _unanswered_once(chain, network):
    """The RPC of `network` answers no is_connected question until it has been asked once; the list given
    counts the questions."""
    url = _entry(network).RPC_URL
    chain.down.add(url)
    asked = []

    def hook(hook_url, method, params):
        if method == "is_connected" and hook_url == url:
            asked.append(method)
            if len(asked) == 2:
                chain.down.discard(url)
    chain.hooks.append(hook)
    return asked


def test_connect_asks_again_whether_the_rpc_answers(chain):
    runner = _runner(AMOY, connect=False)
    asked = _unanswered_once(chain, AMOY)
    runner.connect()
    assert runner.contract is not None and len(asked) == 2


def test_set_network_asks_again_whether_the_rpc_of_the_network_set_answers(chain):
    runner = _runner(AMOY)
    asked = _unanswered_once(chain, AMOY_POX10)
    runner.set_network(*AMOY_POX10)
    assert (runner.network_name, runner.network_type) == AMOY_POX10 and len(asked) == 2


def test_the_web3_check_of_a_run_asks_again_whether_the_rpc_answers(chain):
    runner = _runner(AMOY)
    asked = _unanswered_once(chain, AMOY)
    assert runner.check_web3_connection() is True and len(asked) == 2


def test_the_web3_check_of_a_run_close_ended_asks_once(chain):
    runner = _runner(AMOY)
    asked = _unanswered_once(chain, AMOY)
    run = runner_module._Run(runner.contract)
    outcome = {}

    def check():
        runner._calling.run = run
        outcome["connected"] = runner.check_web3_connection()

    thread = threading.Thread(target=check)
    thread.start()
    thread.join(10)
    assert outcome == {"connected": False} and len(asked) == 1
