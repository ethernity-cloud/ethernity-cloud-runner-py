"""A session's etny-si rows by the grammar of spec/matching.md section 20
(SF20; session-rows.json in tests/spec/): the rows the runner writes are in
the grammar (session.input_row, session.close_row), the rows it reads are
read by it (session.session_row: the accepted and refused rows of the
fixture, each read for its order), and the seq a handle resumes at is the
next one the enclave takes after the request's rows (session.next_input_seq,
the fixture's row list)."""
import logging
from types import SimpleNamespace

import pytest

from ethernity_cloud_runner_py.session import (SESSION_INPUT_KEY, UINT64_MAX, EthernityCloudSession, close_row,
                                               input_row, next_input_seq, session_row)
from spec_copies import load

ROWS = load("session-rows.json")
ORDER = ROWS["order"]
CID = "bafkreigh2akiscaildcqabsyg3dfr6chu3fgpregiymsck7e7aqa4s52zy"
SHA = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"


def kind_of(read):
    """A session_row answer in the fixture's terms: (kind, seq or depth)."""
    if read is None:
        return (None, None)
    kind, number = read
    return (kind, str(number) if kind == "input" else number)


@pytest.mark.parametrize("row", ROWS["accepted"], ids=[r["name"] for r in ROWS["accepted"]])
def test_an_accepted_row_is_read(row):
    expected = row["expected"]
    number = expected["seq"] if expected["kind"] == "input" else expected["depth"]
    assert kind_of(session_row(row["value"], ORDER)) == (expected["kind"], number)


@pytest.mark.parametrize("row", ROWS["refused"], ids=[r["name"] for r in ROWS["refused"]])
def test_a_refused_row_is_not_read(row):
    assert row["expected"]["kind"] is None
    assert session_row(row["value"], ORDER) is None


def test_the_row_list_resumes_at_the_seq_the_enclave_takes_next():
    listed = ROWS["list"]
    taken = [o for o in listed["outcome"] if o["read"] == "taken"]
    assert [o["value"] for o in taken] == listed["taken"]
    assert next_input_seq(listed["rows"], ORDER) == len(taken) == 4
    for o in listed["outcome"]:
        read = session_row(o["value"], ORDER)
        assert (read is None) is (o["read"] in ("outsideGrammar", "otherOrder")), o
    assert next_input_seq(listed["rows"][:2], ORDER) == 1


@pytest.mark.parametrize("seq", [0, 12, UINT64_MAX])
def test_each_input_row_the_runner_writes_is_in_the_grammar(seq):
    row = input_row(seq, ORDER, CID, SHA)
    assert session_row(row, ORDER) == ("input", seq)
    assert row == next(r["value"] for r in ROWS["accepted"] if r["name"] == "input").replace("v1:0:", f"v1:{seq}:")


def test_the_close_row_the_runner_writes_is_in_the_grammar():
    assert close_row(ORDER) == next(r["value"] for r in ROWS["accepted"] if r["name"] == "close")
    assert session_row(close_row(ORDER), ORDER) == ("close", None)


@pytest.mark.parametrize("args", [(-1, ORDER, CID, SHA), (UINT64_MAX + 1, ORDER, CID, SHA), (True, ORDER, CID, SHA),
                                  ("0", ORDER, CID, SHA), (0, -1, CID, SHA), (0, ORDER, "a:b", SHA),
                                  (0, ORDER, CID, "a:b")])
def test_a_value_outside_the_grammar_is_refused_before_a_row_is_written(args):
    with pytest.raises(ValueError, match="etny-si row"):
        input_row(*args)
    with pytest.raises(ValueError, match="etny-si row"):
        close_row(UINT64_MAX + 1)


class _Contract:
    def __init__(self):
        self.rows = []

    def add_metadata_to_request(self, do_req, key, value):
        self.rows.append((key, value))
        return "0xrow"

    def get_provider(self):
        return SimpleNamespace(eth=SimpleNamespace())


class _Caller:
    def __init__(self, rows):
        self.rows = rows

    def _getOrder(self, order_id):
        return [None, None, 12, 9, 1]

    def _getDORequest(self, do_req):
        return [None, 1, 1, 10, 1, 1, 3, 1]

    def _getMetadataCountForRequest(self, do_req):
        return len(self.rows)

    def _getMetadataValueForRequest(self, do_req, index):
        return self.rows[index]


def test_a_handle_resumes_at_the_seq_the_enclave_takes_and_writes_its_close_row():
    rows = [[SESSION_INPUT_KEY, value] for value in ROWS["list"]["rows"]] + [["etny-so", "v1:9:7:x"]]
    contract = _Contract()
    runner = SimpleNamespace(protocol_contract=SimpleNamespace(caller=lambda: _Caller(rows)),
                             retry_operation=lambda read: read(), contract=contract,
                             enclave_public_key="certificate", private_key="0x" + "11" * 32,
                             logger=logging.getLogger("test"), _poll_receipt=lambda *args: {"status": 1})
    session = EthernityCloudSession(runner, ORDER)
    assert session.get_status()["inputs_sent"] == 4
    session.close(wait=False)
    assert contract.rows == [(SESSION_INPUT_KEY, close_row(ORDER))]


def test_the_input_rows_a_handle_writes_are_in_the_grammar_and_taken_in_order(monkeypatch):
    """Two inputs after the fixture's row list: the rows are seq 4 and 5, in
    the grammar, and the enclave's next seq after them is 6."""
    rows = [[SESSION_INPUT_KEY, value] for value in ROWS["list"]["rows"]]
    contract = _Contract()
    storage = SimpleNamespace(drop_pending=lambda *args: None, flush_pending=lambda *args, **kwargs: None,
                              release_held=lambda cids: None)
    runner = SimpleNamespace(protocol_contract=SimpleNamespace(caller=lambda: _Caller(rows)),
                             retry_operation=lambda read: read(), contract=contract,
                             enclave_public_key="certificate", private_key="0x" + "11" * 32,
                             logger=logging.getLogger("test"), _poll_receipt=lambda *args: {"status": 1},
                             storage=lambda: storage, _seal_artefact=lambda plaintext, certificate, blobs: (CID, SHA))
    session = EthernityCloudSession(runner, ORDER)
    monkeypatch.setattr(session, "is_running", lambda: True)
    monkeypatch.setattr(session, "remaining_seconds", lambda: 3600)
    monkeypatch.setattr(session, "_lodge_input", lambda cid: True)
    assert [session.send_input("a"), session.send_input("b")] == [4, 5]
    written = [value for key, value in contract.rows]
    assert [session_row(v, ORDER) for v in written] == [("input", 4), ("input", 5)]
    assert next_input_seq(ROWS["list"]["rows"] + written, ORDER) == 6
