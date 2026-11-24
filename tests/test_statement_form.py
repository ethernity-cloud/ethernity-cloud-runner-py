"""The etny-sw row's statement form (spec/matching.md 3.7, SF19; OD10 B) on
reserved-prefixes.json (tests/spec/): the statement form's bytes, its
signed etny-sw example verified under capability-record.json's trustedzone
test key, and the cut rule for the row: on a network whose pricing names a
PoxMatching only the statement form verifies, so a plain-form row, the form
of a trustedzone built before the statement form, is refused there; on any
other network both forms verify."""
import logging

import pytest
from Crypto.Hash import SHA256
from Crypto.PublicKey import ECC
from Crypto.Signature import DSS

from ethernity_cloud_runner_py.crypto import STATEMENT_PREFIX, statement_bytes, verify_certificate_signature
from ethernity_cloud_runner_py.session import EthernityCloudSession
from spec_copies import load

PREFIXES = load("reserved-prefixes.json")
FORM = PREFIXES["statementForm"]
KEY = load("capability-record.json")["trustedzoneKey"]
EXAMPLE = next(e for e in FORM["examples"] if e["name"] == "etny-sw")
ORDER = int(EXAMPLE["statement"].split("|")[1])
WALLET = EXAMPLE["statement"].split("|")[2]


def plain_row():
    """The example's etny-sw row signed over the statement's UTF-8 bytes."""
    key = ECC.import_key(KEY["privateKeyPem"])
    signature = DSS.new(key, "fips-186-3", encoding="der").sign(SHA256.new(EXAMPLE["statement"].encode("utf-8")))
    return f"v1:{ORDER}:{WALLET}:{signature.hex()}"


class _Caller:
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


class _Runner:
    def __init__(self, rows, matching_network):
        self.protocol_contract = type("Contract", (), {"caller": lambda _self: _Caller(rows)})()
        self.contract = None
        self.logger = logging.getLogger("test")
        self.enclave_public_key = KEY["publicKeyPem"]
        self.private_key = ""
        self.matching_reads = 0
        self.matching_network = matching_network

    def retry_operation(self, fn, *args, **kwargs):
        return fn()

    def _names_pox_matching(self):
        self.matching_reads += 1
        if isinstance(self.matching_network, Exception):
            raise self.matching_network
        return self.matching_network


def attested(row, matching_network):
    runner = _Runner([["etny-sw", row]], matching_network)
    session = EthernityCloudSession(runner, ORDER)
    session.poll_outputs()
    return session._attested_wallet, runner


def test_the_statement_form_s_bytes():
    assert STATEMENT_PREFIX.hex() == FORM["prefixHex"]
    assert SHA256.new(statement_bytes(EXAMPLE["statement"])).hexdigest() == EXAMPLE["statementBytesSha256"]
    assert verify_certificate_signature(KEY["publicKeyPem"], statement_bytes(EXAMPLE["statement"]),
                                        bytes.fromhex(EXAMPLE["signatureDerHex"]))
    assert not verify_certificate_signature(KEY["publicKeyPem"], EXAMPLE["statement"].encode("utf-8"),
                                            bytes.fromhex(EXAMPLE["signatureDerHex"]))
    assert EXAMPLE["row"] == f"v1:{ORDER}:{WALLET}:{EXAMPLE['signatureDerHex']}"


@pytest.mark.parametrize("matching_network", [True, False])
def test_a_statement_form_row_is_attested_on_every_network(matching_network):
    wallet, runner = attested(EXAMPLE["row"], matching_network)
    assert wallet == WALLET and runner.matching_reads == 1


def test_a_plain_form_row_is_refused_on_a_matching_network_and_attested_elsewhere():
    rule = next(r for r in FORM["cutRule"]["rows"] if r["statement"] == "etny-sw row")
    assert rule["matchingNetwork"] == "the statement form only"
    assert attested(plain_row(), True)[0] is None
    assert attested(plain_row(), False)[0] == WALLET


def test_a_failed_read_of_the_network_leaves_the_row_for_the_next_poll():
    runner = _Runner([["etny-sw", EXAMPLE["row"]]], ConnectionError("no answer"))
    session = EthernityCloudSession(runner, ORDER)
    assert session.poll_outputs() == [] and session._attested_wallet is None and session._rows_seen == 0
    runner.matching_network = True
    session.poll_outputs()
    assert session._attested_wallet == WALLET and session._rows_seen == 1
