"""EthernityCloudSession: output rows are verified against the task wallet
the trustedzone attests in the session's 'etny-sw' row, which the runner
checks with the trustedzone's certificate. An output row before any
attestation, an attestation that does not verify, and an output not signed
by the attested wallet are refused. No chain: the contract is a stand-in; the
certificate and the wallets are made here."""
import datetime
import logging

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from eth_account import Account
from eth_account.messages import encode_defunct

from ethernity_cloud_runner_py.crypto import verify_certificate_signature
from ethernity_cloud_runner_py.session import EthernityCloudSession

ORDER = 2022


def certificate():
    """A P-384 key and its self-signed certificate PEM, as the Image Registry
    holds a trustedzone's."""
    key = ec.generate_private_key(ec.SECP384R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "trustedzone")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


def attestation(key, wallet, order=ORDER):
    sig = key.sign(f"etny-sw|{order}|{wallet}".encode(), ec.ECDSA(hashes.SHA256()))
    return f"v1:{order}:{wallet}:{sig.hex()}"


def notice_row(signer, seq, order=ORDER):
    """A signed 'late' notice: an output row with no payload to fetch."""
    sig = signer.sign_message(encode_defunct(text=f"etny-so|{order}|{seq}|{seq}|late|0||")).signature.hex()
    return f"v1:{seq}:{order}:{seq}:late:0:::{sig}"


class Caller:
    def __init__(self, rows):
        self.rows = rows

    def _getOrder(self, order_id):
        return ["0xdowner", "0xnode", 7, 9, 1]

    def _getDORequest(self, do_req):
        return ["0xdowner", 1, 1, 10, 1, 1, 3, 1]

    def _getMetadataCountForRequest(self, do_req):
        return 0

    def _getMetadataCountForDPRequest(self, dp_req):
        return len(self.rows)

    def _getMetadataValueForDPRequest(self, dp_req, i):
        return self.rows[i]


class Runner:
    def __init__(self, caller, certificate_pem):
        self.protocol_contract = type("Contract", (), {"caller": lambda _self: caller})()
        self.logger = logging.getLogger("test")
        self.enclave_public_key = certificate_pem

    def retry_operation(self, fn, *args, **kwargs):
        return fn()


def session_with(rows, certificate_pem):
    return EthernityCloudSession(Runner(Caller(rows), certificate_pem), ORDER)


def test_the_certificate_key_signature_verifies_and_a_tampered_one_does_not():
    key, pem = certificate()
    sig = key.sign(b"etny-sw|2022|0xabc", ec.ECDSA(hashes.SHA256()))
    assert verify_certificate_signature(pem, b"etny-sw|2022|0xabc", sig)
    assert not verify_certificate_signature(pem, b"etny-sw|2022|0xabd", sig)
    assert not verify_certificate_signature(pem, b"etny-sw|2022|0xabc", b"\x30\x03\x02\x01\x00")


def test_outputs_signed_by_the_attested_wallet_are_delivered():
    key, pem = certificate()
    task = Account.create()
    session = session_with([("etny-sw", attestation(key, task.address)), ("etny-so", notice_row(task, 0)),
                            ("etny-so", notice_row(task, 1))], pem)
    assert [m["seq"] for m in session.poll_outputs()] == [0, 1]
    assert session._task_wallet() == task.address


def test_an_output_before_any_attestation_is_discarded():
    key, pem = certificate()
    task = Account.create()
    session = session_with([("etny-so", notice_row(task, 0)), ("etny-sw", attestation(key, task.address)),
                            ("etny-so", notice_row(task, 1))], pem)
    assert [m["seq"] for m in session.poll_outputs()] == [1]


def test_an_attestation_not_made_with_the_certificate_key_is_ignored():
    _, pem = certificate()
    other_key, _ = certificate()
    task = Account.create()
    session = session_with([("etny-sw", attestation(other_key, task.address)), ("etny-so", notice_row(task, 0))], pem)
    assert session.poll_outputs() == []
    assert session._task_wallet() is None


def test_an_attestation_for_another_order_is_ignored():
    key, pem = certificate()
    task = Account.create()
    session = session_with([("etny-sw", attestation(key, task.address, order=2021)), ("etny-so", notice_row(task, 0))], pem)
    assert session.poll_outputs() == []


def test_an_output_not_signed_by_the_attested_wallet_is_discarded():
    key, pem = certificate()
    task, other = Account.create(), Account.create()
    session = session_with([("etny-sw", attestation(key, task.address)), ("etny-so", notice_row(other, 0)),
                            ("etny-so", notice_row(task, 1))], pem)
    assert [m["seq"] for m in session.poll_outputs()] == [1]
