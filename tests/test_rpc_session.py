"""rpc.rpc_session: the runner's RPC connections are tried again when they
cannot be made, and nothing the RPC may have received is ever sent twice
(bloxberg testnet 2026-10-26: a moment's connection failure killed a client's
task and session at once)."""
import pytest
from urllib3.exceptions import MaxRetryError, NewConnectionError, ReadTimeoutError

from ethernity_cloud_runner_py.rpc import RPC_CONNECT_BACKOFF_SECONDS, RPC_CONNECT_RETRIES, rpc_session

RPC = "https://bloxberg.ethernity.cloud"


def test_the_session_retries_connections_on_both_schemes():
    session = rpc_session()
    for url in (RPC, "http://127.0.0.1:8545"):
        retry = session.get_adapter(url).max_retries
        assert (retry.connect, retry.read, retry.status) == (RPC_CONNECT_RETRIES, 0, 0)
        assert retry.backoff_factor == RPC_CONNECT_BACKOFF_SECONDS
        assert retry.raise_on_status is False


def test_a_connection_that_cannot_be_made_is_tried_again_with_a_growing_wait():
    retry = rpc_session().get_adapter(RPC).max_retries
    waits = []
    for _ in range(RPC_CONNECT_RETRIES):
        retry = retry.increment(method="POST", url="/", error=NewConnectionError(None, "connection refused"))
        waits.append(retry.get_backoff_time())
    assert not retry.is_exhausted()
    assert waits == [0, 2, 4, 8, 16]
    with pytest.raises(MaxRetryError):
        retry.increment(method="POST", url="/", error=NewConnectionError(None, "connection refused"))


def test_a_request_the_rpc_may_have_received_is_not_sent_again():
    """A read failure surfaces as it is, at once: urllib3 re-raises it instead
    of retrying when no read retries are allowed."""
    retry = rpc_session().get_adapter(RPC).max_retries
    with pytest.raises(ReadTimeoutError):
        retry.increment(method="POST", url="/", error=ReadTimeoutError(None, "/", "read timed out"))
