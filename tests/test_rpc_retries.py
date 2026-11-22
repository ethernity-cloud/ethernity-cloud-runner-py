"""What the runner asks again of an RPC that does not serve a request, now
that web3 sends each request once (rpc.rpc_provider).

A send hands its signed transaction to the node again, the same bytes, while
the hand-over is not answered: an HTTP 429 or 503, a connection reset, an
HTTP 504, a read timeout or a body that is no JSON-RPC answer after the node
took it. A node that holds the
transaction already gives its hash back, and so does any answer after a
hand-over that lost its answer, an answer that the nonce is used among them,
and five hand-overs none of which is answered: no second transaction is built
for the intent, by the send, by the DO request's and the approval's tries,
or by the approval step. attach_session()'s reads of the order and its
request, esr_version and esr_nonce, the node check and the question whether
the RPC answers (connect, set_network, check_web3_connection) are asked again
while the RPC does not serve them; a revert is raised at once.

No chain: the node of the send cases is a provider that keeps a pool of the
transactions it took; the other cases use test_set_network.py's chain."""
import json
import threading
from types import SimpleNamespace

import pytest
import requests
import rlp
from eth_account import Account
from eth_utils import keccak
from urllib3.exceptions import ConnectTimeoutError, MaxRetryError, NewConnectionError
from web3.exceptions import BadResponseFormat, ContractLogicError, Web3RPCError
from web3.providers.base import BaseProvider

import ethernity_cloud_runner_py.contract.operation.protocolContract as protocol_module
import ethernity_cloud_runner_py.rpc as rpc_module
import ethernity_cloud_runner_py.runner as runner_module
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.errors import RunEndedError
from ethernity_cloud_runner_py.runner import RUN_ENDED, RUN_ENDED_REQUEST_SENT, EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession, SessionError

from test_set_network import (  # noqa: F401 (chain is the fixture the cases ask for)
    AMOY, AMOY_POX10, ORDER, RESOURCES, REVERTS, WALLET, _called, _entry, _runner, chain,
)
from test_runner_lifetime import _in_session

SIGNER = Account.from_key("0x" + "11" * 32)
NONCE = 7
GWEI = 10 ** 9
DO_REQUEST = 41
NODE_ADDRESS = "0x" + "22" * 20
TESTNET = ("BLOXBERG", "TESTNET")
GETH_HELD = {"code": -32000, "message": "already known"}
PARITY_HELD = {"code": -32010, "message": "Transaction with the same hash was already imported."}
# What nodes answer to a transaction whose nonce is used: geth and bor, Nethermind, OpenEthereum and Parity
# (bloxberg's).
NONCE_USED = {
    "geth": {"code": -32000, "message": "nonce too low"},
    "nethermind": {"code": -32010, "message": "OldNonce"},
    "openethereum": {"code": -32010, "message": "Transaction nonce is too low. Try incrementing the nonce."},
}


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    """The waits between two hand-overs and between two reads take no time."""
    monkeypatch.setattr(protocol_module, "HANDOVER_RETRY_SECONDS", 0)
    monkeypatch.setattr(rpc_module, "RPC_READ_RETRY_SECONDS", 0)


def _http_error(status):
    """The requests error of an answer of HTTP status `status`, as raise_for_status raises it."""
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(f"{status} Server Error for url: RPC", response=response)


def _nonce_of(raw):
    """The nonce of a signed transaction: a type-2 one, or a legacy one."""
    fields = rlp.decode(raw[1:]) if raw[0] == 2 else rlp.decode(raw)
    return int.from_bytes(fields[1] if raw[0] == 2 else fields[0], "big")


class _Node(BaseProvider):
    """A node of chain `chain_id` with a pool of the transactions it took (by hash). The wallet's transaction
    count, at the latest block and pending alike, is NONCE, raised by each transaction taken and each one
    another sender of the wallet mined (`stolen`). Each hand-over (eth_sendRawTransaction) is answered as the
    next of `handovers` says, and once `handovers` is spent as "take". "429" and "503" are answered by the
    RPC, which does not pass the request on, with that HTTP status; "refused" and "connect timeout" raise
    requests' errors for a connection that was never made (refused, or not made within the connect timeout);
    "reset" raises the error of a connection reset after the request was sent, which does not reach the node;
    "lost 504" is an HTTP 504 of a gateway that did not pass the request on; "stolen 504" and "stolen 429" are
    an HTTP 504 and an HTTP 429 after another transaction of the wallet was mined at the current nonce; a dict
    is the node's error answer, the transaction not taken. The others reach the node. A transaction whose nonce is below the count, and which
    the node does not hold, is answered `nonce_used`. Else the node takes a transaction it does not hold:
    "take" answers its hash, "504" and "slow" raise the error of an HTTP 504 and of a read timeout, "mined 504"
    mines it and raises the HTTP 504 error, "html" and "no result" raise web3's errors for a body that is not
    JSON and for a JSON body with neither a result nor an error. A transaction the node holds is answered
    "take" with `held`, or with `nonce_used` once mined, and the others raise their errors for it.
    eth_getTransactionByHash is answered from the pool where `gettx` is "ok"; "429" raises the requests error
    of an HTTP 429 and "null" answers null, a replica that has not seen the transaction. A receipt is a mined
    one for a transaction in the pool while `mines` holds, and null otherwise; where `receipts` is "null" or
    "503" every receipt is answered null or raises the requests error of an HTTP 503, a replica behind the one
    that mined it. `handed` lists the raw bytes of every hand-over and `reads` every method asked but the
    hand-overs."""

    def __init__(self, chain_id, handovers, held=GETH_HELD, nonce_used=NONCE_USED["geth"], gettx="ok", mines=True,
                 receipts="mined"):
        super().__init__()
        self.chain_id = chain_id
        self.handovers = list(handovers)
        self.held, self.nonce_used, self.gettx, self.mines = held, nonce_used, gettx, mines
        self.receipts = receipts
        self.pool, self.mined, self.handed, self.reads = {}, set(), [], []
        self.stolen = 0

    def count(self):
        return NONCE + len(self.pool) + self.stolen

    def is_connected(self, show_traceback=False):
        return True

    def make_request(self, method, params):
        if method != "eth_sendRawTransaction":
            self.reads.append(method)
        if method == "eth_chainId":
            return self._answer(hex(self.chain_id))
        if method == "eth_getTransactionCount":
            return self._answer(hex(self.count()))
        if method == "eth_getBlockByNumber":
            return self._answer({"number": "0x1", "baseFeePerGas": hex(20 * GWEI)})
        if method == "eth_estimateGas":
            return self._answer(hex(50_000))
        if method == "eth_getTransactionByHash":
            if self.gettx == "429":
                raise _http_error(429)
            found = self.gettx == "ok" and params[0] in self.pool
            return self._answer({"hash": params[0]} if found else None)
        if method == "eth_getTransactionReceipt":
            if self.receipts == "503":
                raise _http_error(503)
            mined = self.receipts == "mined" and self.mines and params[0] in self.pool
            return self._answer({"transactionHash": params[0], "status": "0x1", "blockNumber": "0x1", "logs": []}
                                if mined else None)
        if method == "eth_sendRawTransaction":
            raw = bytes.fromhex(params[0][2:])
            self.handed.append(raw)
            tx_hash = "0x" + keccak(raw).hex()
            answer = self.handovers.pop(0) if self.handovers else "take"
            if answer in ("429", "503", "lost 504"):
                raise _http_error(int(answer[-3:]))
            if answer in ("stolen 504", "stolen 429"):
                self.stolen += 1
                raise _http_error(int(answer[-3:]))
            if answer == "refused":
                raise requests.exceptions.ConnectionError(MaxRetryError(None, "/", NewConnectionError(
                    None, "Failed to establish a new connection: [WinError 10061] No connection could be made")))
            if answer == "connect timeout":
                raise requests.exceptions.ConnectTimeout(MaxRetryError(None, "/", ConnectTimeoutError(
                    None, "Connection to 127.0.0.1 timed out. (connect timeout=5)")))
            if answer == "reset":
                raise requests.exceptions.ConnectionError("Connection aborted.")
            if isinstance(answer, dict):
                return {"jsonrpc": "2.0", "id": 1, "error": answer}
            held = tx_hash in self.pool
            if not held and _nonce_of(raw) < self.count():
                return {"jsonrpc": "2.0", "id": 1, "error": self.nonce_used}
            self.pool[tx_hash] = raw
            if answer == "mined 504":
                self.mined.add(tx_hash)
            if answer in ("504", "mined 504"):
                raise requests.exceptions.HTTPError("504 Server Error: Gateway Timeout for url: RPC")
            if answer == "slow":
                raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)")
            if answer == "html":
                raise json.JSONDecodeError("Expecting value", "<html>gateway</html>", 0)
            if answer == "no result":
                raise BadResponseFormat("The response was in an unexpected format and unable to be parsed.")
            if held:
                return {"jsonrpc": "2.0", "id": 1, "error": self.nonce_used if tx_hash in self.mined else self.held}
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


@pytest.mark.parametrize("unreadable", ["html", "no result"])
def test_a_hand_over_whose_answer_cannot_be_read_is_followed_by_no_second_transaction(unreadable):
    """The node took the transaction and the RPC answered a body that is no JSON-RPC answer."""
    node = _Node(80002, [unreadable])
    assert _contract(node).approve_order(ORDER) == _taken(node)
    assert len(node.handed) == 2 and node.handed[0] == node.handed[1]
    assert node.reads.count("eth_getTransactionCount") == 1


def test_bloxbergs_answer_for_a_transaction_it_holds_gives_its_hash_back():
    node = _Node(8995, ["504"], held=PARITY_HELD)
    assert _contract(node, TESTNET).approve_order(ORDER) == _taken(node)
    assert len(node.handed) == 2


# The sends of the protocol contract, by the name of their method.
SENDS = {
    "set_allowance": lambda contract: contract.set_allowance(3),
    "faucet": lambda contract: contract.faucet(),
    "add_do_request": lambda contract: contract.add_do_request("image", "code", "input", "", RESOURCES),
    "add_metadata_to_request": lambda contract: contract.add_metadata_to_request(DO_REQUEST, "etny-si", "v1:0:7:c:d"),
    "approve_order": lambda contract: contract.approve_order(ORDER),
    "cancel_do_request": lambda contract: contract.cancel_do_request(DO_REQUEST),
}


def _first_hash(node):
    """The hash of the transaction the first hand-over carried."""
    return "0x" + keccak(node.handed[0]).hex()


@pytest.mark.parametrize("gettx", ["ok", "429", "null"])
@pytest.mark.parametrize("client", list(NONCE_USED))
@pytest.mark.parametrize("send", list(SENDS))
def test_a_transaction_mined_before_its_answer_was_lost_gives_its_hash_back_and_no_second_one(send, client, gettx):
    """The node took and mined the transaction, and the answer of its hand-over was lost. The same bytes go to
    it again and it answers that their nonce is used: the send takes the hash whether the transaction is found
    by its hash, not found (null, a replica that has not seen it) or not read (an HTTP 429)."""
    node = _Node(80002, ["mined 504"], nonce_used=NONCE_USED[client], gettx=gettx)
    assert SENDS[send](_contract(node)) == _taken(node)
    assert len(node.handed) == 2 and node.handed[0] == node.handed[1]
    assert node.reads.count("eth_getTransactionCount") == 1


def test_any_answer_after_a_lost_answer_gives_the_hash_back_and_no_transaction_is_built_at_another_nonce():
    """The hand-over's connection was reset, and the next hand-over is answered that another transaction holds
    the nonce in the pool: the first may be held by another replica, and the receipt decides."""
    node = _Node(80002, ["reset", {"code": -32000, "message": "replacement transaction underpriced"}])
    assert _contract(node).approve_order(ORDER) == _first_hash(node)
    assert len(node.handed) == 2 and len(set(node.handed)) == 1
    assert node.pool == {}
    assert node.reads.count("eth_getTransactionCount") == 1


def test_a_send_none_of_whose_hand_overs_is_answered_gives_its_hash_back_and_builds_no_second_transaction():
    """A gateway answers each hand-over with an HTTP 504: it may have passed the request on."""
    node = _Node(80002, ["lost 504"] * protocol_module.HANDOVER_ATTEMPTS)
    assert _contract(node).approve_order(ORDER) == _first_hash(node)
    assert len(node.handed) == protocol_module.HANDOVER_ATTEMPTS
    assert len(set(node.handed)) == 1
    assert node.pool == {}
    assert node.reads.count("eth_getTransactionCount") == 1


UNTAKEN = ["429", "503", "refused", "connect timeout"]


@pytest.mark.parametrize("refusal", UNTAKEN)
def test_a_send_every_hand_over_of_which_was_refused_untaken_raises(refusal):
    """No node took the request: the send raises, and the transaction is the runner's to build again."""
    node = _Node(80002, [refusal] * protocol_module.HANDOVER_ATTEMPTS)
    with pytest.raises(Exception, match="^Unable to send transaction: "):
        _contract(node).approve_order(ORDER)
    assert len(node.handed) == protocol_module.HANDOVER_ATTEMPTS and len(set(node.handed)) == 1
    assert node.pool == {}


@pytest.mark.parametrize("refusal", UNTAKEN)
def test_a_hand_over_that_went_unanswered_among_refusals_gives_the_hash_back(refusal):
    """One HTTP 504 among the refusals: the node may hold the transaction."""
    handovers = [refusal] * protocol_module.HANDOVER_ATTEMPTS
    handovers[2] = "lost 504"
    node = _Node(80002, handovers)
    assert _contract(node).approve_order(ORDER) == _first_hash(node)
    assert len(set(node.handed)) == 1 and node.pool == {}


@pytest.mark.parametrize("error, untaken", [
    (_http_error(429), True), (_http_error(503), True), (_http_error(504), False), (_http_error(502), False),
    (requests.exceptions.ConnectionError(MaxRetryError(None, "/", NewConnectionError(None, "refused"))), True),
    (requests.exceptions.ConnectTimeout(MaxRetryError(None, "/", ConnectTimeoutError(None, "timed out"))), True),
    (requests.exceptions.ConnectionError("Connection aborted."), False),
    (requests.exceptions.ReadTimeout("Read timed out."), False),
    (requests.exceptions.HTTPError("429 Server Error"), False),
    (json.JSONDecodeError("Expecting value", "<html>", 0), False),
], ids=["429", "503", "504", "502", "refused", "connect timeout", "reset", "read timeout", "no response",
        "not json"])
def test_the_errors_that_show_no_node_took_the_request(error, untaken):
    assert protocol_module.refused_untaken(error) is untaken


@pytest.mark.parametrize("answer", [GETH_HELD, {"code": -32000, "message": "known transaction: 5180e592"},
                                    {"code": -32010, "message": "AlreadyKnown"}, PARITY_HELD],
                         ids=["geth", "geth before 1.9", "nethermind", "openethereum"])
def test_a_node_that_answers_it_holds_the_transaction_gives_its_hash(answer):
    node = _Node(80002, [answer])
    assert _contract(node).approve_order(ORDER) == _first_hash(node)
    assert len(node.handed) == 1


def test_an_answer_that_holds_a_held_phrase_inside_a_word_is_the_nodes_refusal():
    """"unknown transaction" is not "known transaction": the node refused the transaction, and the send raises
    its error."""
    node = _Node(80002, [{"code": -32000, "message": "rlp: unknown transaction type 7"}] * 20)
    with pytest.raises(Web3RPCError):
        _contract(node).approve_order(ORDER)
    assert node.pool == {}


# ---- no second transaction at the steps that call a send ----

@pytest.fixture
def submitting(monkeypatch, tmp_path):
    """A POLYGON AMOY runner of SIGNER whose protocol contract is a real one over a node of its own: call it with
    the node. No wait takes time, a receipt is polled for a tenth of a second (a hundred blocks of 1 ms), the
    request's receipt carries the event of request DO_REQUEST and the order read after an approval names
    NODE_ADDRESS. The held cache is a directory of the test's own."""
    monkeypatch.setenv("ETHERNITY_CLOUD_HELD_DIR", str(tmp_path / "held"))
    monkeypatch.setattr(runner_module.time, "sleep", lambda seconds: None)

    def build(node):
        runner = EthernityCloudRunner(*AMOY)
        runner.signer, runner.resources, runner.running, runner.block_time = SIGNER, RESOURCES, True, 0.001
        runner.contract = _contract(node)
        runner.contract.get_order = lambda order_id: [WALLET, NODE_ADDRESS, DO_REQUEST, 9, 1]
        log = SimpleNamespace(args=SimpleNamespace(_rowNumber=DO_REQUEST))
        runner.protocol_contract = SimpleNamespace(events=SimpleNamespace(_addDORequestEV=lambda: SimpleNamespace(
            process_receipt=lambda receipt, errors: [log])))
        runner.order_id = ORDER
        return runner
    return build


def test_a_request_none_of_whose_hand_overs_is_answered_is_sent_once(submitting):
    """The node takes the request at the first of five hand-overs and none of their answers comes."""
    node = _Node(80002, ["504"] * protocol_module.HANDOVER_ATTEMPTS)
    runner = submitting(node)
    assert runner.create_do_request("image", "code", "input", "") is True
    assert runner.do_hash == _taken(node) and runner.do_request == DO_REQUEST
    assert len(set(node.handed)) == 1


@pytest.mark.parametrize("refusal", UNTAKEN)
def test_a_request_refused_untaken_at_every_hand_over_is_sent_again_at_its_nonce(submitting, refusal):
    """The first transaction reached no node: retry_operation signs the request again at the same nonce, so
    no second escrow can be mined, and the step goes on without waiting for a receipt."""
    node = _Node(80002, [refusal] * protocol_module.HANDOVER_ATTEMPTS)
    runner = submitting(node)
    assert runner.create_do_request("image", "code", "input", "") is True
    assert runner.do_hash == _taken(node) and runner.do_request == DO_REQUEST
    assert [_nonce_of(raw) for raw in node.handed] == [NONCE] * (protocol_module.HANDOVER_ATTEMPTS + 1)
    assert node.reads.count("eth_getTransactionReceipt") == 1


def test_an_approval_none_of_whose_hand_overs_is_answered_is_sent_once(submitting):
    node = _Node(80002, ["504"] * protocol_module.HANDOVER_ATTEMPTS)
    runner = submitting(node)
    assert runner.approve_task() is True
    assert runner.node_address == NODE_ADDRESS
    _taken(node)
    assert len(set(node.handed)) == 1


def test_an_approval_whose_receipt_does_not_come_is_not_followed_by_another(submitting):
    """The node takes the approval and its receipt is not read within the hundred blocks."""
    node = _Node(80002, [], mines=False)
    runner = submitting(node)
    assert runner.approve_task() is False
    _taken(node)
    assert len(node.handed) == 1


def test_an_approval_whose_order_read_fails_after_it_is_mined_is_not_followed_by_another(submitting):
    node = _Node(80002, [])
    runner = submitting(node)

    def order_not_read(order_id):
        raise Web3RPCError("header not found", rpc_response={"jsonrpc": "2.0", "id": 1, "error": {
            "code": -32000, "message": "header not found"}})

    runner.contract.get_order = order_not_read
    with pytest.raises(RuntimeError) as failed:
        runner.approve_task()
    tx = _taken(node)
    assert str(failed.value) == (f"The approval {tx} of order {ORDER} was handed to the node, and a read after it "
                                 "failed: header not found")
    assert len(node.handed) == 1


def test_a_submission_close_ended_while_its_requests_hand_over_answers_were_lost_names_the_request(submitting,
                                                                                                    monkeypatch):
    """The node takes the request at its first hand-over, whose answer is lost; close() is called in the wait
    before the next hand-over."""
    node = _Node(80002, ["504"])
    runner = submitting(node)
    monkeypatch.setattr(protocol_module, "time", SimpleNamespace(sleep=lambda seconds: runner.close()))
    with pytest.raises(RunEndedError) as ended:
        with runner._submission():
            runner.create_do_request("image", "code", "input", "")
    tx = _taken(node)
    assert ended.value.request_hash == tx and ended.value.request_id is None
    assert str(ended.value) == RUN_ENDED + RUN_ENDED_REQUEST_SENT.format(request_hash=tx)
    assert isinstance(ended.value.__cause__, RunEndedError) and ended.value.__cause__.transaction_hash == tx
    assert tx in str(ended.value.__cause__)
    assert len(node.handed) == 1


# ---- a transaction whose receipt does not come is not sent again ----

def _allowance_unset(runner):
    """The wallet's allowance for the PoX reads 0: check_allowance approves."""
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(
        allowance=lambda owner, spender: SimpleNamespace(call=lambda: 0)))
    return runner


class _SessionReads:
    """The reads of session order ORDER on DO request DO_REQUEST, PROCESSING within its hour."""

    def _getOrder(self, order_id):
        return [WALLET, NODE_ADDRESS, DO_REQUEST, 9, 1]

    def _getDORequest(self, do_request):
        return [WALLET, 1, 1, 10, 1, 1, 3, 1]

    def _getMetadataCountForRequest(self, do_request):
        return 0


def _session_of(runner):
    """A handle of session order ORDER over the protocol contract and the receipt poll of `runner`; an input is
    sealed as "cid" and the storage has no intake."""
    reads = _SessionReads()
    storage = SimpleNamespace(intake_url="", flush_pending=lambda do_request, operation=None: None,
                              release_held=lambda cids: None, drop_pending=lambda key, cids=None: None)
    stand_in = SimpleNamespace(
        protocol_contract=SimpleNamespace(caller=lambda: reads), retry_operation=lambda read: read(),
        contract=runner.contract, enclave_public_key="certificate", private_key="0x" + "11" * 32,
        logger=runner.logger, storage=lambda: storage, _poll_receipt=runner._poll_receipt,
        _seal_artefact=lambda plaintext, certificate, operation: ("cid", "digest"))
    return EthernityCloudSession(stand_in, ORDER)


# Each step whose receipt wait ends without a receipt, and the outcome it ends with.
STEPS = {
    "the DO request": lambda runner: runner.create_do_request("image", "code", "input", "") is False,
    "the token approval": lambda runner: pytest.raises(ValueError, _allowance_unset(runner).check_allowance),
    "the order's approval": lambda runner: runner.approve_task() is False,
    "a session's input row": lambda runner: pytest.raises(SessionError, _session_of(runner).send_input, "hello"),
    "a session's close row": lambda runner: _session_of(runner).close(wait=False) is None,
}


@pytest.mark.parametrize("receipts", ["null", "503"])
@pytest.mark.parametrize("step", list(STEPS))
def test_a_mined_transaction_whose_receipt_and_lookup_lag_is_not_sent_again(submitting, step, receipts):
    """The node mines the transaction; for the whole receipt wait its receipt is answered null or HTTP 503 and
    its lookup by hash null, while the wallet's transaction count is current."""
    node = _Node(80002, [], gettx="null", receipts=receipts)
    runner = submitting(node)
    assert STEPS[step](runner)
    _taken(node)
    assert len(node.handed) == 1 and node.count() == NONCE + 1


@pytest.mark.parametrize("step", list(STEPS) + ["the cancel of a request"])
def test_a_transaction_whose_nonce_another_sender_took_is_not_sent_again(submitting, step):
    """Another sender of the wallet mines a transaction at the nonce while the hand-over's answer is lost; the
    next hand-over is answered that the nonce is used. The transaction can never be mined, and the step ends
    when its receipt wait does."""
    node = _Node(80002, ["stolen 504"])
    runner = submitting(node)
    if step == "the cancel of a request":
        runner.do_request = DO_REQUEST
        runner.find_order = lambda do_request: False
        assert runner.cancel_unclaimed_request(1800) is False
    else:
        assert STEPS[step](runner)
    assert node.pool == {} and len(set(node.handed)) == 1 and node.stolen == 1


def test_a_transaction_whose_nonce_another_sender_took_after_a_refusal_is_built_again(submitting):
    """The hand-over is answered HTTP 429, not passed on, while another sender of the wallet mines a
    transaction at the nonce: the node's answer that the nonce is used refuses the runner's transaction, and
    the request is built again at the next nonce."""
    node = _Node(80002, ["stolen 429"])
    runner = submitting(node)
    assert runner.create_do_request("image", "code", "input", "") is True
    tx = _taken(node)
    assert runner.do_hash == tx and _nonce_of(node.pool[tx]) == NONCE + 1


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
