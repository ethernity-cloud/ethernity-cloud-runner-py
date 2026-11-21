"""A session handle's outputs and its summary. poll_outputs reads the rows in
one thread at a time, so on_output, wait_output and close in other threads
take each message once. close(wait=True) reads the summary with the handle's
own order and challenge, so a handle attach_session() made, whose runner
holds no order, returns it too. No chain: the reads, the rows and the
runner's result read are stand-ins."""
import logging
import threading
from types import SimpleNamespace

from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession

KEY = "0x" + "11" * 32
ORDER = 7
NODE = "0x" + "22" * 20
ORDER_STRUCT = [None, NODE, 12, 9, 1]
SUMMARY = {"success": True, "value": "the session summary"}


class _Reads:
    """The reads of session order ORDER on request 12 and DP request 9: PROCESSING within its hour until
    `settled`, with one output row on the DP request."""

    def __init__(self):
        self.settled = False

    def _getOrder(self, order_id):
        return ORDER_STRUCT[:4] + [2 if self.settled else 1]

    def _getDORequest(self, do_req):
        return [None, 1, 1, 10, 1, 1, 3, 1]

    def _getMetadataCountForRequest(self, do_req):
        return 0

    def _getMetadataCountForDPRequest(self, dp_req):
        return 1

    def _getMetadataValueForDPRequest(self, dp_req, index):
        return ["etny-so", "the output row"]


def _handle(challenge=None):
    """(handle, runner, reads): a handle of ORDER over a stand-in runner whose close row settles the order and
    whose get_result_from_order records what it is asked for and answers SUMMARY."""
    reads = _Reads()
    asked = []

    def get_result_from_order(order_id, order=None, challenge=None):
        asked.append((order_id, order, challenge))
        return dict(SUMMARY)

    def close_row(do_req, key, value):
        reads.settled = True
        return "0x" + "ab" * 32

    runner = SimpleNamespace(
        protocol_contract=SimpleNamespace(caller=lambda: reads),
        retry_operation=lambda read: read(),
        contract=SimpleNamespace(add_metadata_to_request=close_row,
                                 get_provider=lambda: SimpleNamespace(eth=SimpleNamespace())),
        enclave_public_key="certificate",
        private_key=KEY,
        logger=logging.getLogger("test"),
        _poll_receipt=lambda provider, tx_hash, max_attempts, in_progress: {"status": 1},
        get_result_from_order=get_result_from_order,
        _release_session=lambda session: None,
        asked=asked)
    handle = EthernityCloudSession(runner, ORDER, challenge=challenge)
    handle._attested_wallet = "0x" + "33" * 20
    return handle, runner, reads


def test_two_threads_polling_the_outputs_take_a_message_once():
    """The first poll is held while it verifies the row; a second poll of another thread meanwhile takes
    nothing, the row being the first poll's."""
    handle, _, _ = _handle()
    entered, release = threading.Event(), threading.Event()
    verified = []

    def verify(value):
        verified.append(value)
        if len(verified) == 1:
            entered.set()
            release.wait(2)
        return {"seq": 0, "ack": 0, "status": "ok", "code": 0, "data": "the answer"}

    handle._verify_output_row = verify
    taken = []
    first = threading.Thread(target=lambda: taken.extend(handle.poll_outputs()))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=lambda: taken.extend(handle.poll_outputs()))
    second.start()
    second.join(0.3)
    release.set()
    first.join(5)
    second.join(5)
    assert [message["data"] for message in taken] == ["the answer"]
    assert len(handle.outputs) == 1
    assert verified == ["the output row"]


def test_close_reads_the_summary_with_the_handles_order_and_challenge():
    for challenge in (b"the session's challenge", None):
        handle, runner, _ = _handle(challenge)
        handle._verify_output_row = lambda value: None
        assert handle.close(wait=True, timeout=5) == SUMMARY
        assert runner.asked == [(ORDER, ORDER_STRUCT[:4] + [1], challenge)]


def test_the_result_read_of_an_order_given_reads_that_order_and_not_the_runners():
    """The runner holds no order, as after attach_session(): the read goes to the given order's DP request
    and on to the result, which does not parse here."""
    runner = EthernityCloudRunner("POLYGON", "AMOY")
    runner.running, runner.order = True, None
    dp_requests = []
    runner.contract = SimpleNamespace(get_status_from_order=lambda order_id: 2,
                                      get_result_from_order=lambda order_id: "not a result")
    runner.protocol_contract = SimpleNamespace(caller=lambda: SimpleNamespace(
        _getDPRequestMetadata=lambda dp_request: dp_requests.append(dp_request) or [None] * 5))
    assert runner.get_result_from_order(ORDER, order=ORDER_STRUCT, challenge=None) is None
    assert dp_requests == [9]
    assert runner._fault == f"order {ORDER}: operator result could not be parsed"
