"""The summary a session handle's close(wait=True) returns is the order's own
and its signer is checked. The handle of run_session() checks the signer of
the order's result transaction against the challenge of its request; the
handle of attach_session(), whose process knows no challenge, against the
task wallet the trustedzone attested in the session's etny-sw row. A result
another wallet signed (the node operator's own key) gives no summary, and the
ESR wallet and state its envelope names reach neither the runner's ESR wallet
memo nor its state cache, so esr_version() and esr_read() serve neither; a
handle that verified no attestation reads no result. The summary's deadline
is the order's duration and its request fields are those of the handle's
request, not of the runner's later task.

No chain: the order's reads, its result string and the storage are
stand-ins; the result transactions are signed here and their envelopes
sealed for the runner's key, and the trustedzone's certificate and its
attestation are test_session_wallet's. The run_session() case runs over
test_set_network.py's chain."""
import json
from types import SimpleNamespace

import pytest
from eth_account import Account
from web3 import Web3

import ethernity_cloud_runner_py.runner as runner_module
from ethernity_cloud_runner_py.contract.abi.polygonProtocolAbi import contract as polygon_abi
from ethernity_cloud_runner_py.crypto import encrypt_nacl, sha256
from ethernity_cloud_runner_py.enums import ECNetwork
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession
from ethernity_cloud_runner_py.utils import generate_wallet

from test_runner_lifetime import _in_session, _open
from test_session_wallet import attestation, certificate
from test_set_network import AMOY, _runner as _runner_of, chain  # noqa: F401 (chain is the fixture a case asks for)

KEY = "0x" + "11" * 32
WALLET = Account.from_key(KEY).address
NODE = "0x" + "22" * 20
ORDER, DO_REQUEST, DP_REQUEST = 2022, 12, 9
SECURELOCK = "my-securelock"
PROTOCOL = ECNetwork.POLYGON.AMOY.PROTOCOL_ADDRESS
CHAIN_ID = ECNetwork.POLYGON.AMOY.CHAIN_ID
ENCLAVE_CHALLENGE = "5e" * 16
ATTACKER = "0x00000000000000000000000000000000000BAD01"
GENUINE_WALLET = "0x" + "e5" * 20
# The result fields of the session's request, as run_session() hands them to its handle.
REQUEST = {"input_transaction_hash": "0x" + "a1" * 32, "image_hash": "QmImage:" + SECURELOCK,
           "script_hash": "QmPayload", "file_set_hash": ""}


@pytest.fixture(autouse=True)
def no_registry(monkeypatch):
    """The Enclave State Registry is not read: a read of it fails the case."""
    def registry(*arguments):
        raise AssertionError("the Enclave State Registry was read")
    monkeypatch.setattr(runner_module, "ESRContract", registry)


def _envelope(wallet, state):
    return json.dumps({"ecld": 1, "type": "json", "data": {"summary": state["by"]},
                       "esr": {"wallet": wallet, "entries": [{"key": "k", "state": state, "version": 3, "cid": ""}]}})


class _Order:
    """The reads of session order ORDER on DO request DO_REQUEST and DP request DP_REQUEST, of `hours` hours,
    whose DP request carries `rows`; its status is closed (2) from `closed_at` on the clock `clock()`."""

    def __init__(self, rows, hours=1, clock=lambda: 0, closed_at=0):
        self.rows, self.hours, self.clock, self.closed_at = rows, hours, clock, closed_at

    def status(self):
        return 2 if self.clock() >= self.closed_at else 1

    def _getOrder(self, order_id):
        return [WALLET, NODE, DO_REQUEST, DP_REQUEST, self.status()]

    def _getDORequest(self, do_request):
        return [WALLET, 1, 1, 10, 1, self.hours, 3, 1]

    def _getMetadataCountForRequest(self, do_request):
        return 0

    def _getMetadataCountForDPRequest(self, dp_request):
        return len(self.rows)

    def _getMetadataValueForDPRequest(self, dp_request, index):
        return self.rows[index]

    def _getDPRequestMetadata(self, dp_request):
        return [NODE, "", "", "", ""]


def _runner(order, signer_key, envelope):
    """A POLYGON AMOY runner of KEY whose order reads are `order` and whose order's result is an
    _addResultToOrder transaction for ORDER at the PoX, signed by `signer_key`, naming the result blob
    `envelope` sealed for the runner's key. runner.result_reads counts the reads of the order's status and of
    its result."""
    runner = EthernityCloudRunner("POLYGON", "AMOY")
    runner.set_private_key(KEY)
    runner.protocol_abi = polygon_abi["abi"]
    runner.securelock_enclave = SECURELOCK
    runner.running = True
    runner.result_reads = []
    data = Web3().eth.contract(abi=polygon_abi["abi"]).encode_abi(
        "_addResultToOrder", args=[ORDER, f"v3:0:{sha256(envelope, True)}:{ENCLAVE_CHALLENGE}"])
    signed = Account.sign_transaction({"nonce": 0, "gasPrice": 1, "gas": 300000, "to": PROTOCOL, "value": 0,
                                       "data": data, "chainId": CHAIN_ID}, signer_key)
    blob = encrypt_nacl(runner.get_current_wallet_public_key(), envelope.encode("utf-8"))
    result = f"v3:{signed.raw_transaction.hex()}:QmResult"

    def status(order_id):
        runner.result_reads.append("status")
        return order.status()

    def result_of(order_id):
        runner.result_reads.append("result")
        return result

    eth = SimpleNamespace(get_transaction_receipt=lambda tx_hash: {"status": 1})
    runner.contract = SimpleNamespace(
        get_status_from_order=status, get_result_from_order=result_of, get_protocol_address=lambda: PROTOCOL,
        add_metadata_to_request=lambda do_request, key, value: "0x" + "c1" * 32,
        get_provider=lambda: SimpleNamespace(eth=eth))
    runner.protocol_contract = SimpleNamespace(caller=lambda: order)
    runner.ipfs_client = SimpleNamespace(get_file_content=lambda cid: blob if cid == "QmResult" else None)
    return runner


def _attested(task_wallet):
    """(certificate PEM, the DP request rows of an order whose trustedzone attested `task_wallet`)."""
    key, pem = certificate()
    return pem, [("etny-sw", attestation(key, task_wallet, order=ORDER))]


def _attached(runner, pem):
    """The handle attach_session() makes: no challenge, no request fields, the runner's certificate."""
    runner.enclave_public_key = pem
    return EthernityCloudSession(runner, ORDER)


def _challenge_key(challenge):
    """The key of the task wallet the trustedzone derives from `challenge` and ENCLAVE_CHALLENGE."""
    return sha256(sha256(challenge + ENCLAVE_CHALLENGE, True), True)


# ---- the handle of attach_session() ----

def test_an_attached_handle_gives_no_summary_of_a_result_the_operator_signed():
    """The operator writes a result signed with a key of its own, whose envelope names its wallet and state;
    the attached handle has verified the trustedzone's attestation of the task wallet."""
    task = Account.create()
    operator = Account.create()
    pem, rows = _attested(task.address)
    runner = _runner(_Order(rows), operator.key, _envelope(ATTACKER, {"n": 999, "by": "operator"}))
    handle = _attached(runner, pem)
    assert handle.close(wait=True, timeout=0) is None
    assert handle._attested_wallet == task.address
    assert runner._fault == f"order {ORDER}: result signer verification failed"
    assert runner._esr_wallet_memo == {}
    assert runner._get_state_cache().get(ATTACKER, "k", network=runner._state_network()) is None
    with pytest.raises(ValueError, match="need enclave_wallet"):
        runner.esr_version("k")


def test_an_attached_handle_gives_the_summary_its_attested_task_wallet_signed():
    task = Account.create()
    pem, rows = _attested(task.address)
    runner = _runner(_Order(rows), task.key, _envelope(GENUINE_WALLET, {"n": 4, "by": "the enclave"}))
    runner.do_hash, runner.script_hash, runner.file_set_hash = "0x" + "99" * 32, "QmLater", "QmLaterInput"
    summary = _attached(runner, pem).close(wait=True, timeout=0)
    assert summary["success"] is True and summary["result_data"] == {"summary": "the enclave"}
    assert runner._esr_wallet_memo == {SECURELOCK: GENUINE_WALLET}
    assert runner._get_state_cache().get(GENUINE_WALLET, "k", network=runner._state_network())["state"] == {
        "n": 4, "by": "the enclave"}
    # The attaching process knows none of the request's fields; the runner's are another task's.
    assert [summary[field] for field in REQUEST] == [None, None, None, None]


def test_an_attached_handle_that_verified_no_attestation_reads_no_result():
    task = Account.create()
    pem, _ = _attested(task.address)
    runner = _runner(_Order([]), task.key, _envelope(GENUINE_WALLET, {"n": 4, "by": "the enclave"}))
    handle = _attached(runner, pem)
    assert handle.close(wait=True, timeout=0) is None
    assert handle._attested_wallet is None
    assert runner.result_reads == []
    assert runner._esr_wallet_memo == {}


def test_an_attestation_that_does_not_verify_gives_no_signer_and_no_summary():
    """The row names the operator's wallet, signed with a key that is not the trustedzone certificate's."""
    operator = Account.create()
    _, rows = _attested(operator.address)
    pem, _ = _attested(operator.address)
    runner = _runner(_Order(rows), operator.key, _envelope(ATTACKER, {"n": 999, "by": "operator"}))
    assert _attached(runner, pem).close(wait=True, timeout=0) is None
    assert runner.result_reads == [] and runner._esr_wallet_memo == {}


def test_a_result_read_with_neither_a_challenge_nor_a_signer_reads_nothing():
    """The runner holds no challenge: attach_task on a runner that did not send the order's request."""
    task = Account.create()
    runner = _runner(_Order([]), task.key, _envelope(GENUINE_WALLET, {"n": 4, "by": "the enclave"}))
    runner.order, runner.challenge_hash = [WALLET, NODE, DO_REQUEST, DP_REQUEST, 2], b""
    assert runner.get_result_from_order(ORDER) is None
    assert runner.result_reads == [] and runner._esr_wallet_memo == {}


# ---- the handle of run_session() ----

def test_the_handle_of_run_session_checks_the_signer_against_its_challenge_and_keeps_its_requests_fields():
    challenge = b"the session's challenge"
    pem, rows = _attested(Account.create().address)
    runner = _runner(_Order(rows), _challenge_key(challenge.decode()),
                     _envelope(GENUINE_WALLET, {"n": 4, "by": "the enclave"}))
    runner.enclave_public_key = pem
    handle = EthernityCloudSession(runner, ORDER, challenge=challenge, request=REQUEST)
    # The runner sends another request after the handle was made.
    runner.do_hash, runner.script_hash, runner.file_set_hash = "0x" + "99" * 32, "QmLater", "QmLaterInput"
    runner.enclave_image_ipfs_hash, runner.securelock_enclave = "QmLaterImage", SECURELOCK
    summary = handle.close(wait=True, timeout=0)
    assert generate_wallet(challenge.decode(), ENCLAVE_CHALLENGE) == Account.from_key(
        _challenge_key(challenge.decode())).address
    assert summary["success"] is True
    assert {field: summary[field] for field in REQUEST} == REQUEST


def test_the_handle_run_session_returns_carries_the_fields_of_its_request(chain):
    """create_task stands for the request's send, which leaves its transaction and its payload on the runner."""
    _in_session(chain)
    runner = _runner_of(AMOY)
    send = runner.create_task

    def create_task(code):
        runner.do_hash, runner.script_hash, runner.file_set_hash = REQUEST["input_transaction_hash"], "QmPayload", ""
        return send(code)

    runner.create_task = create_task
    handle = _open(runner)
    assert handle._request == {"input_transaction_hash": REQUEST["input_transaction_hash"],
                               "image_hash": f"{runner.enclave_image_ipfs_hash}:{runner.securelock_enclave}",
                               "script_hash": "QmPayload", "file_set_hash": ""}


def test_the_runners_own_task_is_read_with_its_challenge_and_its_request_fields():
    challenge = b"the task's challenge"
    runner = _runner(_Order([]), _challenge_key(challenge.decode()),
                     _envelope(GENUINE_WALLET, {"n": 4, "by": "the enclave"}))
    runner.order, runner.challenge_hash = [WALLET, NODE, DO_REQUEST, DP_REQUEST, 2], challenge
    runner.do_hash, runner.script_hash, runner.file_set_hash = REQUEST["input_transaction_hash"], "QmPayload", ""
    runner.enclave_image_ipfs_hash, runner.resources = "QmImage", {"duration": 2}
    summary = runner.get_result_from_order(ORDER)
    assert {field: summary[field] for field in REQUEST} == REQUEST
    assert runner._esr_wallet_memo == {SECURELOCK: GENUINE_WALLET}


def test_the_handle_of_run_session_gives_no_summary_of_a_result_its_challenge_does_not_derive():
    challenge = b"the session's challenge"
    task = Account.create()
    pem, rows = _attested(task.address)
    runner = _runner(_Order(rows), task.key, _envelope(ATTACKER, {"n": 999, "by": "operator"}))
    runner.enclave_public_key = pem
    handle = EthernityCloudSession(runner, ORDER, challenge=challenge, request=REQUEST)
    assert handle.close(wait=True, timeout=0) is None
    assert runner._esr_wallet_memo == {}


# ---- the order's duration ----

def test_the_summary_is_waited_for_within_the_orders_duration_not_the_runners_last_resources(monkeypatch):
    """The order is of 5 hours and closes 2 hours on; the runner's last resources were of 1 hour, past which,
    with its 15 minutes, the wait would have ended."""
    clock = [1_000_000.0]
    task = Account.create()
    pem, rows = _attested(task.address)
    order = _Order(rows, hours=5, clock=lambda: clock[0], closed_at=clock[0] + 2 * 3600)
    runner = _runner(order, task.key, _envelope(GENUINE_WALLET, {"n": 4, "by": "the enclave"}))
    runner.resources = {"duration": 1}
    handle = _attached(runner, pem)
    monkeypatch.setattr(runner_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(runner_module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + 600))
    summary = handle.close(wait=True, timeout=0)
    assert runner._fault is None
    assert summary is not None and summary["result_data"] == {"summary": "the enclave"}
