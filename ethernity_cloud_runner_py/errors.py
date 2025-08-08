"""
errors.py

Centralized error-handling helpers and logging filters for Ethernity Cloud Runner.

Why this exists
---------------
Web3.py sometimes logs a separate, "friendly" line from `web3.manager.RequestManager`:

    "An RPC error was returned by the node. Check the message provided in the error and any available logs for more information."

That message is fine for simple scripts, but in production it becomes noisy—especially
when you already log the *actual* node error (e.g., "nonce too low", "replacement
transaction underpriced"). Worse, this friendly line is emitted as its own log
record (often **without** `exc_info`), so:
- You can’t suppress it by catching the exception,
- Overriding `Web3RPCError.__str__` doesn’t help,
- And filters that depend on the error code usually can’t see the code.

This module solves it by providing:
1) `raw_rpc_error_message(e)`: extract the **raw** JSON-RPC error message from a `Web3RPCError`.
2) A **context manager** `suppress_web3_friendly_prefix()` that temporarily drops the friendly
   line around a specific RPC call (works even when `exc_info` is missing).
3) An optional **global filter** `install_web3_friendly_prefix_filter(...)` that suppresses the
   friendly line only for selected error codes when `exc_info` is present.
4) `ECWeb3RPCError`: a subclass that renders only the raw node message when stringified.

Recommended usage
-----------------
- Around calls that may emit the friendly line (e.g. `send_raw_transaction`):

    with suppress_web3_friendly_prefix():
        w3.eth.send_raw_transaction(...)

- In `except Web3RPCError as e:` blocks, always log:

    msg = raw_rpc_error_message(e)

- Optionally, at process startup (main **and** workers):

    install_web3_friendly_prefix_filter(suppress_codes=(-32000, -32010))

Notes
-----
- Multiprocessing: each process has its own logging config; install filters per process.
- Performance: filters run only on `web3.manager.RequestManager` records; overhead is negligible.
- If Web3.py changes the friendly text, update `_PREFIX` below.
"""

import logging
from typing import Optional, Iterable
from web3.exceptions import Web3RPCError

__all__ = [
    "raw_rpc_error_message",
    "ECWeb3RPCError",
    "suppress_web3_friendly_prefix",
    "install_web3_friendly_prefix_filter",
]

# ---------- Helpers ----------

def raw_rpc_error_message(e: Web3RPCError) -> str:
    """
    Return the raw JSON-RPC 'error.message' if available; otherwise fall back.
    Safe to use everywhere instead of e.message / str(e).
    """
    try:
        resp = getattr(e, "rpc_response", {}) or {}
        err = resp.get("error", {}) or {}
        return err.get("message") or getattr(e, "message", "") or str(e)
    except Exception:
        return getattr(e, "message", "") or str(e)

def raw_rpc_error_code(e: Web3RPCError):
        """
        Return the raw JSON-RPC 'error.code' if available; otherwise fall back.
        Safe to use everywhere instead of e.code / str(e).
        """
        try:
            resp = getattr(e, "rpc_response", {}) or {}
            err = resp.get("error", {}) or {}
            return err.get("code", getattr(e, "code", None)) or str(e)
        except Exception:
            return getattr(e, "messacodege", "") or str(e)
    

class ECWeb3RPCError(Web3RPCError):
    """
    Optional: a Web3RPCError that prints ONLY the raw node message.
    You can raise this from your own handlers if you want cleaner logs.
    """
    def __str__(self) -> str:
        return raw_rpc_error_message(self)


# ---------- Filter (global) ----------

_PREFIX = "An RPC error was returned by the node"

class _SuppressWeb3FriendlyPrefixByCode(logging.Filter):
    """
    Suppress Web3.py’s friendly prefix line for specific error codes.
    NOTE: This only works when Web3 logs with exc_info containing Web3RPCError.
    If exc_info is missing (common), this filter won't catch it — use the
    context manager below to suppress during the critical call.
    """
    def __init__(self, suppress_codes: Iterable[int]):
        super().__init__()
        self._codes = set(int(c) for c in suppress_codes)

    def _extract_code(self, exc: Optional[BaseException]):
        if isinstance(exc, Web3RPCError):
            # Prefer rpc_response.error.code
            try:
                resp = getattr(exc, "rpc_response", {}) or {}
                err = resp.get("error", {}) or {}
                if "code" in err:
                    return err["code"]
            except Exception:
                pass
            # Fallback
            return getattr(exc, "code", None)
        return None

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "web3.manager.RequestManager":
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if not (isinstance(msg, str) and msg.startswith(_PREFIX)):
            return True

        exc = record.exc_info[1] if record.exc_info else None
        code = self._extract_code(exc)
        if code in self._codes:
            return False  # drop only for selected codes
        return True


def install_web3_friendly_prefix_filter(suppress_codes: Iterable[int] = (-32000, -32010)) -> None:
    """
    Attach a best-effort filter to 'web3.manager.RequestManager' to hide the friendly line
    for specific JSON-RPC codes. Call this in EVERY PROCESS (main & workers).
    """
    logger = logging.getLogger("web3.manager.RequestManager")
    # Avoid duplicates
    if not any(isinstance(f, _SuppressWeb3FriendlyPrefixByCode) for f in logger.filters):
        logger.addFilter(_SuppressWeb3FriendlyPrefixByCode(suppress_codes))


# ---------- Context manager (works 100% of the time) ----------

class _DropWeb3FriendlyPrefix(logging.Filter):
    """Drops ONLY the fixed friendly prefix line, regardless of exc_info presence."""
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "web3.manager.RequestManager":
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not (isinstance(msg, str) and msg.startswith(_PREFIX))


class suppress_web3_friendly_prefix:
    """
    Use this around the exact RPC call that tends to emit the friendly prefix:
        with suppress_web3_friendly_prefix():
            w3.eth.send_raw_transaction(...)

    This guarantees the prefix line is not emitted during the call.
    If you want that line for other error codes, re-log it yourself
    after you catch the exception and know the code.
    """
    def __enter__(self):
        self._logger = logging.getLogger("web3.manager.RequestManager")
        self._filter = _DropWeb3FriendlyPrefix()
        self._logger.addFilter(self._filter)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self._logger.removeFilter(self._filter)
        except Exception:
            pass