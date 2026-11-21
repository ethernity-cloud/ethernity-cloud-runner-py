"""The intake queue after a task or a session input whose transaction was not
sent. A task's sealed blobs are queued for the intake and delivered once its
DO request is on chain; when create_task ends none of them is left queued,
so the request of the next task posts its own blobs alone. A session input
whose row was not sent, or was mined as reverted, leaves no blob queued
either. The intake refuses a blob the request it is posted for does not name,
which fails the delivery of the request that does exist.

No chain and no intake: the contract, the receipt and its event are
stand-ins, the seal is a marker, and requests is replaced by a recorder."""
import logging
from types import SimpleNamespace

import pytest

from ethernity_cloud_runner_py import ipfs
from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.errors import FeeCeilingError
from ethernity_cloud_runner_py.ipfs import IPFSClient, StorageLimitError
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession, SessionError

from test_ipfs_client import Response, post_answering, record_sleeps

INTAKE = "https://intake.invalid"
RESOURCES = {"taskPrice": 1, "cpu": 1, "memory": 1, "storage": 1, "bandwidth": 1, "duration": 1, "validators": 1}
TX = "0x" + "ab" * 32
KEY = "0x" + "11" * 32
REQUEST = 12
ORDER = 7


@pytest.fixture
def sealed(monkeypatch, tmp_path):
    """The seal of an artefact is the marker b"sealed:" before its plaintext, and the held cache is a
    directory of the test's own."""
    monkeypatch.setattr(runner_module, "encrypt", lambda plaintext, certificate: b"sealed:" + plaintext)
    monkeypatch.setenv("ETHERNITY_CLOUD_HELD_DIR", str(tmp_path / "held"))


def _runner(send, receipt=None, event=True):
    """A POLYGON AMOY runner over the intake INTAKE whose DO request is `send`: its receipt is `receipt` (a
    mined one by default) and carries the request event of REQUEST unless `event` is false."""
    runner = EthernityCloudRunner("POLYGON", "AMOY")
    runner.set_public_intake(INTAKE)
    runner.private_key, runner.enclave_public_key = KEY, "certificate"
    runner.resources, runner.running = RESOURCES, True
    eth = SimpleNamespace(get_transaction_receipt=lambda tx_hash: receipt or {"status": 1}, block_number=1)
    runner.contract = SimpleNamespace(add_do_request=send, get_provider=lambda: SimpleNamespace(eth=eth))
    log = SimpleNamespace(args=SimpleNamespace(_rowNumber=REQUEST))
    runner.protocol_contract = SimpleNamespace(
        functions=SimpleNamespace(_getOrdersCount=lambda: SimpleNamespace(call=lambda: 0)),
        w3=SimpleNamespace(eth=eth),
        events=SimpleNamespace(_addDORequestEV=lambda: SimpleNamespace(
            process_receipt=lambda receipt, errors: [log] if event else [])))
    runner.get_reason = lambda contract, tx_hash: "reverted"
    return runner


def _refused(*arguments):
    raise FeeCeilingError("the fee is above the ceiling")


def _sent(*arguments):
    return TX


def _posted(calls):
    """The CIDs the intake was posted, with the request each was posted for."""
    return [tuple(url.rsplit("/", 2)[1:]) for url, _ in calls]


# ---- a task ----

def test_a_task_whose_request_the_fee_ceiling_refuses_leaves_no_blob_queued(sealed, monkeypatch):
    calls = post_answering(monkeypatch)
    runner = _runner(_refused)
    with pytest.raises(FeeCeilingError):
        runner.create_task("code")
    assert runner.storage().pending == {}
    assert calls == []


def test_the_next_task_posts_its_own_blobs_alone(sealed, monkeypatch):
    calls = post_answering(monkeypatch, Response(200), Response(200), Response(200))
    runner = _runner(_refused)
    runner.input_data = "the first task's input"
    with pytest.raises(FeeCeilingError):
        runner.create_task("the first task's code")
    first = {runner.challenge_ipfs_hash, runner.script_hash, runner.file_set_hash}
    runner.contract.add_do_request = _sent
    runner.input_data = "the second task's input"
    assert runner.create_task("the second task's code") is True
    second = [runner.challenge_ipfs_hash, runner.script_hash, runner.file_set_hash]
    assert len(first) == 3 and not first & set(second)
    assert _posted(calls) == [(str(REQUEST), cid) for cid in second]
    assert runner.storage().pending == {}


@pytest.mark.parametrize("receipt, event", [({"status": 0}, True), ({"status": 1}, False)],
                         ids=["reverted", "without the request event"])
def test_a_task_whose_request_is_not_on_chain_leaves_no_blob_queued(sealed, monkeypatch, receipt, event):
    calls = post_answering(monkeypatch)
    runner = _runner(_sent, receipt, event)
    assert runner.create_task("code") is False
    assert runner.storage().pending == {}
    assert calls == []


def test_a_task_one_of_whose_artefacts_the_intake_does_not_take_leaves_no_blob_queued(sealed, monkeypatch):
    """The input is above the intake's limit: the challenge and the code, sealed before it, were queued."""
    calls = post_answering(monkeypatch)
    sent = []
    runner = _runner(lambda *arguments: sent.append(arguments) or TX)
    runner.storage().intake_max_bytes = 64
    runner.input_data = "i" * 100
    with pytest.raises(StorageLimitError):
        runner.create_task("code")
    assert runner.storage().pending == {}
    assert sent == [] and calls == []


def test_a_task_whose_delivery_the_intake_refuses_leaves_no_blob_queued(sealed, monkeypatch):
    calls = post_answering(monkeypatch, Response(413, text="too large"))
    runner = _runner(_sent)
    with pytest.raises(RuntimeError, match="^intake refused "):
        runner.create_task("code")
    assert runner.do_request == REQUEST
    assert len(calls) == 1
    assert runner.storage().pending == {}


def test_drop_pending_passes_over_what_is_not_queued():
    client = IPFSClient(f"{INTAKE}/api/v0", intake_url=INTAKE, network="polygon_amoy")
    kept, dropped = client.upload_to_ipfs(b"kept"), client.upload_to_ipfs(b"dropped")
    client.drop_pending([dropped, None, "", "bafynotqueued"])
    assert client.pending == {kept: b"kept"}


# ---- a session input ----

class Caller:
    """The reads of a session of order ORDER on request REQUEST, PROCESSING within its hour."""

    def _getOrder(self, order_id):
        return [None, None, REQUEST, 9, 1]

    def _getDORequest(self, do_req):
        return [None, 1, 1, 10, 1, 1, 3, 1]

    def _getMetadataCountForRequest(self, do_req):
        return 0


def _session(send, receipt=None):
    """(session, client): a session whose rows are `send` and whose receipts are `receipt` (a mined one by
    default), over an intake client that queues what the session seals."""
    client = IPFSClient(f"{INTAKE}/api/v0", intake_url=INTAKE, network="polygon_amoy")
    caller = Caller()
    eth = SimpleNamespace()
    runner = SimpleNamespace(
        protocol_contract=SimpleNamespace(caller=lambda: caller),
        retry_operation=lambda read: read(),
        contract=SimpleNamespace(add_metadata_to_request=send, get_provider=lambda: SimpleNamespace(eth=eth)),
        enclave_public_key="certificate",
        _seal_artefact=lambda plaintext, certificate: (client.upload_to_ipfs(b"sealed:" + plaintext), "digest"),
        _poll_receipt=lambda provider, tx_hash, max_attempts, in_progress: receipt or {"status": 1},
        storage=lambda: client,
        private_key=KEY,
        logger=logging.getLogger("test"))
    return EthernityCloudSession(runner, ORDER), client


NOT_NAMED = Response(403, text='{"error": "the DO request does not name this cid"}')


def test_an_input_the_intake_does_not_lodge_leaves_no_blob_queued(sealed, monkeypatch):
    calls = post_answering(monkeypatch, Response(413, text="too large"))
    rows = []
    session, client = _session(lambda *arguments: rows.append(arguments) or TX)
    with pytest.raises(SessionError, match="not committed, send it again"):
        session.send_input("hello")
    assert client.pending == {}
    assert rows == [] and len(calls) == 1


def test_the_input_sent_again_delivers_its_own_blob_alone(sealed, monkeypatch):
    """The intake has no signed path, so a blob goes after its row: the first input's row is refused by the
    fee ceiling, and the delivery after the second input's row posts the second blob alone."""
    calls = post_answering(monkeypatch, NOT_NAMED, NOT_NAMED, Response(200))
    record_sleeps(monkeypatch)
    session, client = _session(_refused)
    with pytest.raises(FeeCeilingError):
        session.send_input("hello")
    first = ipfs.unixfs_cid(b"sealed:hello")
    assert client.pending == {}
    session._contract.add_metadata_to_request = _sent
    assert session.send_input("hello again") == 0
    second = ipfs.unixfs_cid(b"sealed:hello again")
    assert _posted(calls) == [(str(REQUEST), first), (str(REQUEST), second), (str(REQUEST), second)]
    assert client.pending == {}


def test_an_input_whose_row_is_mined_as_reverted_leaves_no_blob_queued(sealed, monkeypatch):
    post_answering(monkeypatch, NOT_NAMED)
    session, client = _session(_sent, {"status": 0})
    with pytest.raises(SessionError, match="input row transaction failed"):
        session.send_input("hello")
    assert client.pending == {}


def test_an_input_whose_row_has_no_receipt_yet_keeps_its_blob_for_the_delivery_after_the_row(sealed, monkeypatch):
    """The row may still be mined, and names the blob then."""
    post_answering(monkeypatch, NOT_NAMED)
    session, client = _session(_sent)
    session.runner._poll_receipt = lambda provider, tx_hash, max_attempts, in_progress: None
    with pytest.raises(SessionError, match="input row transaction failed"):
        session.send_input("hello")
    assert client.pending == {ipfs.unixfs_cid(b"sealed:hello"): b"sealed:hello"}
