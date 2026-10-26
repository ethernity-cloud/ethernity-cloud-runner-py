"""The HTTP session the runner's web3 provider sends its RPC calls through."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# How many times a connection to the RPC that cannot be made is tried again,
# and the backoff factor between the tries (urllib3 waits factor x 2^(try-1)
# seconds). Only the connection is retried, never a request the RPC may have
# received: a read failure after a send would send a transaction twice.
# (bloxberg testnet 2026-10-26: one client's connection to the RPC failed for
# a moment, "Max retries exceeded with url: /", and its task and the session
# behind it died at once while nine other clients went on.)
RPC_CONNECT_RETRIES = 5
RPC_CONNECT_BACKOFF_SECONDS = 1


def rpc_session() -> requests.Session:
    """A requests session whose connections to the RPC are tried
    RPC_CONNECT_RETRIES times, RPC_CONNECT_BACKOFF_SECONDS x 2^(try-1) seconds
    apart, before a connection failure reaches the caller; a request that
    reached the RPC is never sent again (no read retries), and a response is
    returned as it came (no status retries)."""
    retry = Retry(total=RPC_CONNECT_RETRIES, connect=RPC_CONNECT_RETRIES, read=0, status=0,
                  other=RPC_CONNECT_RETRIES, backoff_factor=RPC_CONNECT_BACKOFF_SECONDS,
                  raise_on_status=False)
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
