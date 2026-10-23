"""EthernityCloudSession: a verified output row whose payload is not readable
yet, or is served under its CID with other bytes, is read again on later polls
and delivered once the payload is, for PAYLOAD_RETRY_SECONDS; a row whose
payload never comes is given up after that, and the rows behind it go on
(bloxberg testnet order 2023: output 3's payload reached the gateway after the
row and was discarded as a digest mismatch). No chain, no IPFS, no NaCl: the
contract, the storage and the decryption are stand-ins."""
import hashlib
import logging

from eth_account import Account
from eth_account.messages import encode_defunct

from ethernity_cloud_runner_py import session as session_module
from ethernity_cloud_runner_py.session import PAYLOAD_RETRY_SECONDS, EthernityCloudSession

from test_session_wallet import Caller, attestation, certificate

ORDER = 2022
PAYLOAD = b"sealed reply bytes"
CID = "bafkreibobnv5ikag6zekcsihz2nsckfjg32uacwd3o6shtu3u7rxi3ot2m"


def output_row(signer, seq, cid=CID, payload=PAYLOAD, order=ORDER):
    sha_hex = hashlib.sha256(payload).hexdigest()
    sig = signer.sign_message(encode_defunct(text=f"etny-so|{order}|{seq}|{seq}|ok|0|{cid}|{sha_hex}")).signature.hex()
    return f"v1:{seq}:{order}:{seq}:ok:0:{cid}:{sha_hex}:{sig}"


class Storage:
    """Serves `served` for a CID from its `serve_from`-th request on; None,
    the no-endpoint answer, before that."""
    def __init__(self, served, serve_from=1):
        self.served = served
        self.serve_from = serve_from
        self.requests = 0

    def get_file_content(self, cid):
        self.requests += 1
        return self.served.get(cid) if self.requests >= self.serve_from else None


class Runner:
    def __init__(self, caller, certificate_pem, storage):
        self.protocol_contract = type("Contract", (), {"caller": lambda _self: caller})()
        self.logger = logging.getLogger("test")
        self.enclave_public_key = certificate_pem
        self.private_key = "0x" + "11" * 32
        self._storage = storage

    def storage(self):
        return self._storage

    def retry_operation(self, fn, *args, **kwargs):
        return fn()


def session_with(rows, storage, monkeypatch):
    monkeypatch.setattr(session_module, "decrypt_nacl", lambda key, data: {"success": True, "data": f"reply:{data}"})
    key, pem = certificate()
    task = Account.create()
    rows = [("etny-sw", attestation(key, task.address))] + [(k, v(task)) for k, v in rows]
    return EthernityCloudSession(Runner(Caller(rows), pem, storage), ORDER)


def test_a_payload_served_later_is_delivered_on_a_later_poll(monkeypatch):
    storage = Storage({CID: PAYLOAD}, serve_from=3)
    session = session_with([("etny-so", lambda t: output_row(t, 0))], storage, monkeypatch)
    assert session.poll_outputs() == []
    assert session.poll_outputs() == []
    assert [m["data"] for m in session.poll_outputs()] == [f"reply:{PAYLOAD.decode()}"]
    assert session._payload_waits == {}


def test_bytes_that_do_not_hash_to_the_digest_are_read_again(monkeypatch):
    storage = Storage({CID: b"other bytes"})
    session = session_with([("etny-so", lambda t: output_row(t, 0))], storage, monkeypatch)
    assert session.poll_outputs() == []
    storage.served[CID] = PAYLOAD
    assert [m["seq"] for m in session.poll_outputs()] == [0]


def test_the_rows_behind_a_pending_payload_wait_for_it_in_order(monkeypatch):
    storage = Storage({CID: PAYLOAD}, serve_from=2)
    session = session_with([("etny-so", lambda t: output_row(t, 0)), ("etny-so", lambda t: output_row(t, 1))],
                           storage, monkeypatch)
    assert session.poll_outputs() == []
    assert [m["seq"] for m in session.poll_outputs()] == [0, 1]


def test_a_payload_that_never_comes_is_given_up_after_the_retry_window(monkeypatch):
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(session_module.time, "time", lambda: clock["now"])
    other = "bafkreifgxs3pym3dkwr3uuio75l56jooxni3joe7vqcgb7jtjdguhirhle"
    storage = Storage({CID: PAYLOAD})
    session = session_with([("etny-so", lambda t: output_row(t, 0, cid=other, payload=b"never")),
                            ("etny-so", lambda t: output_row(t, 1))], storage, monkeypatch)
    assert session.poll_outputs() == []
    clock["now"] += PAYLOAD_RETRY_SECONDS - 1
    assert session.poll_outputs() == []
    clock["now"] += 2
    assert [m["seq"] for m in session.poll_outputs()] == [1]
