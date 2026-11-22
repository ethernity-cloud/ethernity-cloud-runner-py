"""The HTTP layer the runner's web3 providers send their RPC calls through.

One provider call is one HTTP request, bounded in time (RPC_REQUEST_MAX_SECONDS):
web3's own retries are off (rpc_provider), urllib3 sends no request again
that the RPC may have received, and a connection that cannot be made is tried
again RPC_CONNECT_RETRIES times in the thread that built the provider: web3
7.6 keeps the session a provider is built with for that thread and gives
every other thread a requests.Session of its own, which makes one connection
try. What is tried again is tried by the runner, between two requests, and
stops for a run close() has ended: retry_operation, the receipt, order and
result polls, the attempts of a send and the hand-over of its signed bytes
(protocolContract._build_sign_send), the reads of read_again, the question
of rpc_answers and a session handle's reads."""
import time
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from web3 import Web3
from web3.exceptions import ProviderConnectionError

# The (connect, read) timeout of one request, in seconds. The connect timeout
# covers the TCP connection and the TLS handshake; the read timeout is the
# longest wait for the RPC's answer once the request is sent.
RPC_CONNECT_TIMEOUT_SECONDS = 5
RPC_READ_TIMEOUT_SECONDS = 10
RPC_TIMEOUT = (RPC_CONNECT_TIMEOUT_SECONDS, RPC_READ_TIMEOUT_SECONDS)
# How many times a connection to the RPC that cannot be made is tried again,
# and the backoff factor between the tries: urllib3 waits 0 s after the first
# failure and factor x 2^(n-1) s after the n-th, 0 s here. Only the
# connection is retried, never a request the RPC may have received: a read
# failure after a send would send a transaction twice.
RPC_CONNECT_RETRIES = 1
RPC_CONNECT_BACKOFF_SECONDS = 0.5
RPC_CONNECT_WAITS_SECONDS = (0,)
# The longest one request takes: every connection try but the last times out,
# the waits between them pass, the last connection takes its whole timeout and
# the answer does not come within the read timeout. 2 * 5 s + 0 s + 10 s = 20 s
# in the thread that built the provider, 5 s + 10 s = 15 s in any other. An
# RPC that accepts the connection and never answers takes the read timeout,
# 10 s; one that refuses connections takes the time the system takes to report
# the two refusals; a host that answers nothing takes 2 * 5 s = 10 s (5 s in
# another thread).
RPC_REQUEST_MAX_SECONDS = ((RPC_CONNECT_RETRIES + 1) * RPC_CONNECT_TIMEOUT_SECONDS + sum(RPC_CONNECT_WAITS_SECONDS)
                           + RPC_READ_TIMEOUT_SECONDS)
# How many times read_again and rpc_answers ask, and the seconds between two
# questions.
RPC_READ_ATTEMPTS = 3
RPC_READ_RETRY_SECONDS = 2
# The requests whose first answer a provider keeps (rpc_provider).
CACHED_REQUESTS = {"eth_chainId"}


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
    and web3 sends each of them once (no exception_retry_configuration). web3
    asks eth_chainId before every eth_call, eth_estimateGas and transaction it
    validates; the chain id of an RPC does not change, so the provider keeps
    the first answer in each thread (CACHED_REQUESTS) and asks every other
    request, web3_clientVersion among them, each time."""
    return Web3.HTTPProvider(url, request_kwargs=request_kwargs or {"timeout": RPC_TIMEOUT}, session=rpc_session(),
                             exception_retry_configuration=None, cache_allowed_requests=True,
                             cacheable_requests=CACHED_REQUESTS)


def read_again(read: Callable[[], Any], ended: Callable[[], bool] = lambda: False) -> Any:
    """`read()`, asked again while the RPC does not serve it
    (requests.RequestException: no connection, no answer within RPC_TIMEOUT,
    an HTTP error status such as 429 or 503), up to RPC_READ_ATTEMPTS times
    RPC_READ_RETRY_SECONDS apart, and not again once `ended()` holds. The
    last such error, and any other error at once (a revert among them), is
    raised."""
    for attempt in range(1, RPC_READ_ATTEMPTS + 1):
        try:
            return read()
        except requests.exceptions.RequestException:
            if attempt == RPC_READ_ATTEMPTS or ended():
                raise
        time.sleep(RPC_READ_RETRY_SECONDS)


def rpc_answers(w3: Web3, ended: Callable[[], bool] = lambda: False) -> bool:
    """Whether the RPC of `w3` answers web3_clientVersion (Web3.is_connected).
    A question the RPC refuses or drops (an HTTP error status such as 429 or
    503, a connection refused or reset, an error answer) is asked again, up
    to RPC_READ_ATTEMPTS times RPC_READ_RETRY_SECONDS apart, and not again
    once `ended()` holds. A question that timed out (requests.Timeout: no
    connection within the connect timeout, no answer within the read
    timeout) is not asked again: an RPC that does not answer takes one
    request, RPC_REQUEST_MAX_SECONDS at its longest."""
    for attempt in range(1, RPC_READ_ATTEMPTS + 1):
        try:
            if w3.is_connected(show_traceback=True):
                return True
        except ProviderConnectionError as error:
            # is_connected raises it inside its handler of the request's
            # error, which is its __context__.
            if isinstance(error.__context__, requests.exceptions.Timeout):
                return False
        if attempt == RPC_READ_ATTEMPTS or ended():
            return False
        time.sleep(RPC_READ_RETRY_SECONDS)
