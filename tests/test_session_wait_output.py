"""EthernityCloudSession.wait_output: the output answering one input, by the
row's ack, however many outputs for other inputs arrive around it (bloxberg
testnet order 2583: the answers to inputs 7 and 8 reached the chain ten
minutes late, after the client had given up on them, and wait_outputs handed
the first of them over as the answer to input 9). No chain, no IPFS, no NaCl:
the contract, the storage and the decryption are stand-ins."""
import hashlib
import logging

from eth_account import Account
from eth_account.messages import encode_defunct

from ethernity_cloud_runner_py import session as session_module
from ethernity_cloud_runner_py.session import EthernityCloudSession

from test_session_wallet import Caller, attestation, certificate

# The order test_session_wallet's attestation is signed for.
ORDER = 2022


def cid_of(ack):
    """The CID of the payload answering input `ack`: content-derived in the
    protocol, so one per answer here too."""
    return f"bafkreib{str(ack).rjust(51, 'a')}"


def output_row(signer, seq, ack):
    """The 'ok' output row `seq` answering input `ack`, its payload "reply to <ack>"."""
    sha_hex = hashlib.sha256(f"reply to {ack}".encode()).hexdigest()
    sig = signer.sign_message(encode_defunct(text=f"etny-so|{ORDER}|{seq}|{ack}|ok|0|{cid_of(ack)}|{sha_hex}")).signature.hex()
    return f"v1:{seq}:{ORDER}:{ack}:ok:0:{cid_of(ack)}:{sha_hex}:{sig}"


class Chain(Caller):
    """The session's chain, its DP request's metadata rows added to over
    time, counting the reads of their number."""
    def __init__(self, rows):
        super().__init__(rows)
        self.reads = 0

    def _getMetadataCountForDPRequest(self, dp_req):
        self.reads += 1
        return super()._getMetadataCountForDPRequest(dp_req)


class Storage:
    """Serves each answer's bytes under its CID."""
    def __init__(self):
        self.served = {}

    def get_file_content(self, cid):
        return self.served.get(cid)


class Runner:
    def __init__(self, chain, certificate_pem, storage):
        self.protocol_contract = type("Contract", (), {"caller": lambda _self: chain})()
        self.logger = logging.getLogger("test")
        self.enclave_public_key = certificate_pem
        self.private_key = "0x" + "11" * 32
        self._storage = storage

    def storage(self):
        return self._storage

    def retry_operation(self, fn, *args, **kwargs):
        return fn()


def session_with(monkeypatch):
    monkeypatch.setattr(session_module, "decrypt_nacl", lambda key, data: {"success": True, "data": data})
    monkeypatch.setattr(session_module.time, "sleep", lambda s: None)
    key, pem = certificate()
    task = Account.create()
    chain = Chain([("etny-sw", attestation(key, task.address))])
    storage = Storage()

    def answer(seq, ack):
        storage.served[cid_of(ack)] = f"reply to {ack}".encode()
        chain.rows.append(("etny-so", output_row(task, seq, ack)))

    return EthernityCloudSession(Runner(chain, pem, storage), ORDER), chain, answer


def test_the_answer_to_the_input_is_returned_not_an_earlier_inputs_late_answer(monkeypatch):
    session, _chain, answer = session_with(monkeypatch)
    answer(0, 7)
    answer(1, 8)
    answer(2, 9)
    msg = session.wait_output(9, timeout=5, poll_seconds=0)
    assert (msg["ack"], msg["data"]) == (9, "reply to 9")
    assert [m["ack"] for m in session.outputs] == [7, 8, 9]


def test_an_answer_that_arrived_during_an_earlier_wait_is_found_without_a_chain_read(monkeypatch):
    session, chain, answer = session_with(monkeypatch)
    answer(0, 7)
    answer(1, 8)
    assert session.wait_output(7, timeout=5, poll_seconds=0)["data"] == "reply to 7"
    reads = chain.reads
    assert session.wait_output(8, timeout=5, poll_seconds=0)["data"] == "reply to 8"
    assert chain.reads == reads


def test_no_answer_within_the_timeout_is_none(monkeypatch):
    session, _chain, answer = session_with(monkeypatch)
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(session_module.time, "time", lambda: clock["now"])
    monkeypatch.setattr(session_module.time, "sleep", lambda s: clock.__setitem__("now", clock["now"] + 5))
    answer(0, 0)
    assert session.wait_output(1, timeout=12, poll_seconds=5) is None
    assert [m["ack"] for m in session.outputs] == [0]
