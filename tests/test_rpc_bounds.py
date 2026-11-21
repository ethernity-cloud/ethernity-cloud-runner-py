"""One RPC call of the runner is one HTTP request, bounded in time: the
providers of the protocol contract, the Enclave State Registry and the image
registry carry rpc.RPC_TIMEOUT and web3 sends each request once, so a call
to an RPC that accepts the connection and never answers ends after the read
timeout, well inside RUN_END_WAIT_SECONDS. What is tried again is tried by
the runner: the receipt poll, the image registry read, a send's reads, a
session handle's reads and the ESR version wait read again after a read the
RPC did not answer. The hanging RPC is a socket on 127.0.0.1 that accepts and
never answers; every other provider is a stand-in."""
import logging
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import requests
from eth_abi import encode
from eth_account import Account
from web3.providers.base import BaseProvider

import ethernity_cloud_runner_py.contract.operation.protocolContract as protocol_module
import ethernity_cloud_runner_py.runner as runner_module
import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py.contract.operation.esrContract import ESRContract
from ethernity_cloud_runner_py.contract.operation.imageRegistryContract import ImageRegistryContract
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECNetwork
from ethernity_cloud_runner_py.rpc import RPC_CONNECT_RETRIES, RPC_REQUEST_MAX_SECONDS, RPC_TIMEOUT
from ethernity_cloud_runner_py.runner import CHAIN_POLL_SECONDS, RUN_END_WAIT_SECONDS, EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession

from test_set_network import AMOY, ORDER, _runner, chain  # noqa: F401 (chain is the fixture a case asks for)

SIGNER = Account.from_key("0x" + "11" * 32)
TX = "0x" + "ab" * 32
NOT_ANSWERED = requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)")


def _contracts():
    return (protocolContract(SIGNER, *AMOY), ESRContract(*AMOY), ImageRegistryContract(*AMOY))


# ---- the providers ----

def test_every_provider_sends_each_request_once_with_the_rpc_timeout_through_the_rpc_session():
    for contract in _contracts():
        provider = contract.provider.provider
        assert provider.exception_retry_configuration is None
        assert dict(provider.get_request_kwargs())["timeout"] == RPC_TIMEOUT == (3, 10)
        session = provider._request_session_manager.cache_and_return_session(provider.endpoint_uri)
        assert session.get_adapter(provider.endpoint_uri).max_retries.connect == RPC_CONNECT_RETRIES


def test_one_request_at_its_longest_and_a_poll_interval_fit_in_the_wait_for_a_closed_run():
    assert RPC_REQUEST_MAX_SECONDS == 3 * 3 + 1 + 10 == 20
    assert RUN_END_WAIT_SECONDS > RPC_REQUEST_MAX_SECONDS + CHAIN_POLL_SECONDS


@pytest.fixture
def hanging_rpc(monkeypatch):
    """POLYGON AMOY's RPC is a socket on 127.0.0.1 that accepts every connection and never answers; the
    list given lists the connections it accepted."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    accepted = []

    def accept():
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return
            accepted.append(connection)

    threading.Thread(target=accept, daemon=True).start()
    monkeypatch.setattr(ECNetwork.POLYGON.AMOY, "RPC_URL", f"http://127.0.0.1:{server.getsockname()[1]}")
    yield accepted
    server.close()
    for connection in accepted:
        connection.close()


READS = {
    "the protocol contract": lambda kwargs: protocolContract(SIGNER, *AMOY, request_kwargs=kwargs).get_orders_count(),
    "the Enclave State Registry": lambda kwargs: ESRContract(*AMOY, request_kwargs=kwargs).get_state(
        SIGNER.address, "counter"),
    "the image registry": lambda kwargs: ImageRegistryContract(*AMOY, request_kwargs=kwargs).get_enclave_details_v3(
        "ecld-pynithy-amoy", "v3"),
}


@pytest.mark.parametrize("read", list(READS))
def test_a_read_of_an_rpc_that_never_answers_is_one_request_and_ends_at_the_read_timeout(hanging_rpc, read):
    """A read timeout of 0.3 s: web3 does not send the request again, and the timeout is raised."""
    started = time.monotonic()
    with pytest.raises(requests.exceptions.ReadTimeout):
        READS[read]({"timeout": (2, 0.3)})
    took = time.monotonic() - started
    assert len(hanging_rpc) == 1
    assert took < 1.5


# ---- what the runner reads again ----

def test_the_receipt_poll_reads_again_after_a_read_the_rpc_did_not_answer(monkeypatch):
    monkeypatch.setattr(runner_module, "CHAIN_POLL_SECONDS", 0.01)
    answers = [NOT_ANSWERED, {"status": 1, "transactionHash": TX}]

    def get_transaction_receipt(tx_hash):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    runner = EthernityCloudRunner(*AMOY)
    eth = SimpleNamespace(get_transaction_receipt=get_transaction_receipt)
    assert runner._poll_receipt(eth, TX, 10, lambda: True) == {"status": 1, "transactionHash": TX}
    assert answers == []


class _Flaky(BaseProvider):
    """An RPC whose first eth_call is not answered (requests.ConnectionError) and whose later ones answer
    `result`."""

    def __init__(self, result):
        super().__init__()
        self.result = result
        self.calls = 0

    def make_request(self, method, params):
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(80002)}
        assert method == "eth_call"
        self.calls += 1
        if self.calls == 1:
            raise requests.exceptions.ConnectionError("Failed to establish a new connection")
        return {"jsonrpc": "2.0", "id": 1, "result": self.result}


def test_the_image_registry_read_is_made_again_after_a_read_the_rpc_did_not_answer():
    registry = ImageRegistryContract(*AMOY)
    flaky = _Flaky("0x" + encode(["string", "string", "string"], ["QmImage", "certificate", "QmCompose"]).hex())
    registry.provider.provider = flaky
    runner = EthernityCloudRunner(*AMOY)
    runner.running, runner.block_time = True, 0.01
    runner.image_registry_contract = registry
    runner.securelock_enclave, runner.securelock_version = runner.trustedZoneImage, "v3"
    assert runner.get_enclave_details() is True
    assert (runner.enclave_image_ipfs_hash, runner.enclave_public_key, runner.enclave_docker_compose_ipfs_hash) == (
        "QmImage", "certificate", "QmCompose")
    assert flaky.calls == 2


def test_a_send_reads_again_after_a_read_the_rpc_did_not_serve(chain, monkeypatch):
    """The nonce read is answered 429 once; the next attempt reads it again and sends."""
    monkeypatch.setattr(protocol_module, "SEND_READ_RETRY_SECONDS", 0)
    runner = _runner(AMOY)
    refused = []

    def rate_limited(url, method, params):
        if method == "eth_getTransactionCount" and not refused:
            refused.append(method)
            raise requests.exceptions.HTTPError("429 Client Error: Too Many Requests")

    chain.hooks.append(rate_limited)
    assert runner.contract.approve_order(ORDER) == TX
    assert refused == ["eth_getTransactionCount"]
    assert [entry[4] for entry in chain.log if entry[0] == "send"] == ["_approveOrder"]


class _SessionCaller:
    """The reads of a session of ORDER on request 12, PROCESSING within its hour, whose request holds the input
    row of seq 2. Each read named in `unanswered` is not answered once."""

    def __init__(self, unanswered=()):
        self.unanswered = list(unanswered)

    def _miss(self, name):
        if name in self.unanswered:
            self.unanswered.remove(name)
            raise NOT_ANSWERED

    def _getOrder(self, order_id):
        self._miss("_getOrder")
        return [None, None, 12, 9, 1]

    def _getDORequest(self, do_req):
        self._miss("_getDORequest")
        return [None, 1, 1, 10, 1, 1, 3, 1]

    def _getMetadataCountForRequest(self, do_req):
        self._miss("_getMetadataCountForRequest")
        return 1

    def _getMetadataValueForRequest(self, do_req, index):
        self._miss("_getMetadataValueForRequest")
        return ["etny-si", f"v1:2:{ORDER}:bafkreiinput:digest"]


def _session(caller):
    runner = SimpleNamespace(
        protocol_contract=SimpleNamespace(caller=lambda: caller),
        retry_operation=lambda read: read(),
        contract=SimpleNamespace(),
        enclave_public_key="certificate",
        private_key="0x" + "11" * 32,
        logger=logging.getLogger("test"))
    return EthernityCloudSession(runner, ORDER)


def test_a_session_handle_reads_its_request_and_its_inputs_again_after_reads_the_rpc_did_not_answer(monkeypatch):
    """The handle resumes at the seq after the input row on chain, as a reattached session must."""
    monkeypatch.setattr(session_module, "SESSION_READ_RETRY_SECONDS", 0)
    caller = _SessionCaller(["_getDORequest", "_getMetadataCountForRequest", "_getMetadataValueForRequest"])
    session = _session(caller)
    assert session.do_req == 12 and session.duration_hours == 1
    assert session.get_status()["inputs_sent"] == 3
    assert caller.unanswered == []


def test_a_session_handle_is_running_through_an_order_read_the_rpc_did_not_answer(monkeypatch):
    monkeypatch.setattr(session_module, "SESSION_READ_RETRY_SECONDS", 0)
    caller = _SessionCaller()
    session = _session(caller)
    caller.unanswered.append("_getOrder")
    assert session.is_running() is True
    assert caller.unanswered == []


def test_a_session_handle_tries_a_read_the_rpc_does_not_answer_a_bounded_number_of_times(monkeypatch):
    monkeypatch.setattr(session_module, "SESSION_READ_RETRY_SECONDS", 0)
    caller = _SessionCaller()
    session = _session(caller)
    caller.unanswered.extend(["_getOrder"] * session_module.SESSION_READ_ATTEMPTS)
    assert session.is_running() is False
    assert caller.unanswered == []


def test_the_esr_version_wait_reads_again_after_a_read_the_rpc_did_not_answer():
    runner = EthernityCloudRunner(*AMOY)
    answers = [NOT_ANSWERED, {"wallet": SIGNER.address, "version": 1, "cid": ""},
               {"wallet": SIGNER.address, "version": 2, "cid": "bafkreistate"}]

    def esr_onchain(key, enclave_wallet=None):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    runner._esr_onchain = esr_onchain
    assert runner.esr_wait_for_version("counter", 1, enclave_wallet=SIGNER.address, timeout=10, interval=0) == {
        "wallet": SIGNER.address, "version": 2, "cid": "bafkreistate"}
    assert answers == []
