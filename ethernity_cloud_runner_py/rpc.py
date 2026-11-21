"""The HTTP layer the runner's web3 providers send their RPC calls through.

One provider call is one HTTP request, bounded in time (RPC_REQUEST_MAX_SECONDS):
web3's own retries are off (rpc_provider), a request the RPC may have
received is never sent again, and a connection that cannot be made is tried
again RPC_CONNECT_RETRIES times in the thread that built the provider: web3
7.6 keeps the session a provider is built with for that thread and gives
every other thread a requests.Session of its own, which makes one connection
try. What is tried again is tried by the runner (retry_operation, the
receipt, order and result polls, the attempts of a send, a session handle's
reads), which stops for a run close() has ended."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from web3 import Web3

# The (connect, read) timeout of one request, in seconds. The connect timeout
# covers the TCP connection and the TLS handshake; the read timeout is the
# longest wait for the RPC's answer once the request is sent.
RPC_CONNECT_TIMEOUT_SECONDS = 3
RPC_READ_TIMEOUT_SECONDS = 10
RPC_TIMEOUT = (RPC_CONNECT_TIMEOUT_SECONDS, RPC_READ_TIMEOUT_SECONDS)
# How many times a connection to the RPC that cannot be made is tried again,
# and the backoff factor between the tries: urllib3 waits 0 s after the first
# failure and factor x 2^(n-1) s after the n-th, 0 s and 1 s here. Only the
# connection is retried, never a request the RPC may have received: a read
# failure after a send would send a transaction twice.
RPC_CONNECT_RETRIES = 2
RPC_CONNECT_BACKOFF_SECONDS = 0.5
RPC_CONNECT_WAITS_SECONDS = (0, 1)
# The longest one request takes: every connection try but the last times out,
# the waits between them pass, the last connection takes its whole timeout and
# the answer does not come within the read timeout. 3 * 3 s + 1 s + 10 s = 20 s
# in the thread that built the provider, 3 s + 10 s = 13 s in any other. An
# RPC that accepts the connection and never answers takes the read timeout,
# 10 s; one that refuses connections takes the waits, 1 s, and the time the
# system takes to report each refusal; a host that answers nothing takes
# 3 * 3 s + 1 s = 10 s (3 s in another thread).
RPC_REQUEST_MAX_SECONDS = ((RPC_CONNECT_RETRIES + 1) * RPC_CONNECT_TIMEOUT_SECONDS + sum(RPC_CONNECT_WAITS_SECONDS)
                           + RPC_READ_TIMEOUT_SECONDS)


def rpc_session() -> requests.Session:
    """A requests session whose connections to the RPC are tried
    RPC_CONNECT_RETRIES times more, RPC_CONNECT_WAITS_SECONDS apart, before a
    connection failure reaches the caller; a request that reached the RPC is
    never sent again (no read retries), and a response is returned as it came
    (no status retries)."""
    retry = Retry(total=RPC_CONNECT_RETRIES, connect=RPC_CONNECT_RETRIES, read=0, status=0,
                  other=RPC_CONNECT_RETRIES, backoff_factor=RPC_CONNECT_BACKOFF_SECONDS,
                  raise_on_status=False)
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def rpc_provider(url: str, request_kwargs=None) -> Web3.HTTPProvider:
    """The web3 provider of an RPC URL: its requests go through rpc_session()
    with RPC_TIMEOUT, unless `request_kwargs` gives other requests arguments,
    and web3 sends each of them once (no exception_retry_configuration)."""
    return Web3.HTTPProvider(url, request_kwargs=request_kwargs or {"timeout": RPC_TIMEOUT}, session=rpc_session(),
                             exception_retry_configuration=None)
