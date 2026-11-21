"""Structured result envelopes + the runner-managed ESR state cache.

The enclave executor returns results as a structured envelope:

    {"ecld": 1, "type": "json"|"text"|"base64", "data": ..., "esr": {...}|null}

`parse_result_envelope` decodes it (and passes legacy raw-string results
through untouched), exposing both the typed view and a legacy string view so
existing dApp code that treats results as strings keeps working.

`StateCache` stores the ESR state carried by result envelopes, keyed by
(network, enclave wallet, state key). The runner auto-populates it from every result
and gates reads behind a free on-chain check (`getState` eth_call): while the
cached version is current, a read costs zero orders and zero gas.
"""

import base64
import json
import os
import threading
import time


def parse_result_envelope(raw):
    """Decode a task result; legacy raw strings pass through.

    Returns a dict:
        is_envelope  True when the result was a structured envelope
        type         "json" | "text" | "base64"
        data         typed value (json -> object, base64 -> bytes, text -> str)
        esr          the envelope's esr attachment (dict) or None
        raw          the exact result string as received
        legacy       the legacy string view (what a string-treating dApp sees)
    """
    out = {
        "is_envelope": False,
        "type": "text",
        "data": raw,
        "esr": None,
        "raw": raw,
        "legacy": raw,
    }
    if not isinstance(raw, str):
        return out
    stripped = raw.lstrip()
    if not stripped.startswith("{"):
        return out
    try:
        env = json.loads(raw)
    except (ValueError, TypeError):
        return out
    if not isinstance(env, dict) or env.get("ecld") != 1:
        return out
    rtype = env.get("type", "text")
    rdata = env.get("data")
    out["is_envelope"] = True
    out["esr"] = env.get("esr")
    if rtype == "base64":
        try:
            out["type"] = "base64"
            out["data"] = base64.b64decode(rdata or "")
            out["legacy"] = rdata or ""
        except Exception:
            out["type"] = "text"
            out["data"] = rdata
            out["legacy"] = str(rdata)
    elif rtype == "json":
        out["type"] = "json"
        out["data"] = rdata
        out["legacy"] = json.dumps(rdata, separators=(",", ":"))
    else:
        out["type"] = "text"
        out["data"] = "" if rdata is None else str(rdata)
        out["legacy"] = out["data"]
    return out


class StateCache:
    """Pluggable (network, enclave wallet, key) -> state cache.

    Default backend is an in-memory dict; pass `file=` for JSON persistence
    across restarts, or `backend=` with any dict-like object implementing
    __getitem__/__setitem__/__delitem__/__contains__ (plus .keys()) to plug in
    custom storage.

    get, set and invalidate take the network an entry belongs to as
    `network`, and an entry set under one network is found under no other:
    the Enclave State Registry of each network holds its own state for a
    wallet and a key. The runner passes its network's key, <network>_<type>
    in lower case (EthernityCloudRunner._state_network). The backend's key is
    "<network>|<wallet in lower case>|<key>"; without `network` it is
    "<wallet in lower case>|<key>", which the runner neither reads nor writes.
    """

    def __init__(self, backend=None, file=None):
        self._lock = threading.Lock()
        self._file = file
        self._backend = backend if backend is not None else {}
        if file and backend is None:
            try:
                if os.path.exists(file):
                    with open(file, "r", encoding="utf-8") as f:
                        self._backend = json.load(f)
            except Exception:
                self._backend = {}

    @staticmethod
    def _k(wallet, key, network=None):
        entry = f"{(wallet or '').lower()}|{key}"
        return f"{network}|{entry}" if network else entry

    def _persist(self):
        if not self._file:
            return
        try:
            tmp = self._file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(self._backend), f)
            os.replace(tmp, self._file)
        except Exception:
            pass

    def get(self, wallet, key, network=None):
        k = self._k(wallet, key, network)
        with self._lock:
            entry = self._backend.get(k) if hasattr(self._backend, "get") \
                else (self._backend[k] if k in self._backend else None)
            return dict(entry) if entry else None

    def set(self, wallet, key, state, version, cid, network=None):
        entry = {
            "state": state,
            "version": int(version),
            "cid": cid,
            "wallet": wallet,
            "savedAt": int(time.time()),
        }
        if network:
            entry["network"] = network
        with self._lock:
            self._backend[self._k(wallet, key, network)] = entry
            self._persist()

    def invalidate(self, wallet, key, network=None):
        with self._lock:
            try:
                del self._backend[self._k(wallet, key, network)]
            except KeyError:
                pass
            self._persist()

    def clear(self):
        with self._lock:
            try:
                keys = list(self._backend.keys())
            except Exception:
                keys = []
            for k in keys:
                try:
                    del self._backend[k]
                except KeyError:
                    pass
            self._persist()
