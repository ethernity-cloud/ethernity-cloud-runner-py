"""The start of an order: a node that advertises 'startrow=v1' in its DP
request's metadata4 adds an etny-st row, 'v1:<order>:<block>', when it begins
running the order; the runner treats an order of such a node without the row
ORDER_START_WINDOW_BLOCKS blocks into processing as abandoned (bloxberg
testnet, 2026-10-24: a node that skipped an approved order left its client
waiting the order's full duration)."""
from ethernity_cloud_runner_py.runner import (ORDER_START_WINDOW_BLOCKS, ORDER_STARTED_KEY,
                                              order_start_verdict, started_row_advertised,
                                              started_row_order)


def test_a_dp_request_advertises_started_rows_as_one_metadata4_entry():
    assert started_row_advertised("trustedzones=etny-pynithy-testnet;ipfs=12D3KooW;startrow=v1")
    assert not started_row_advertised("trustedzones=etny-pynithy-testnet;ipfs=12D3KooW")
    assert not started_row_advertised("")
    assert not started_row_advertised(None)


def test_a_started_row_names_its_order_and_other_shapes_name_none():
    assert started_row_order("v1:2053:30783036") == 2053
    for value in ("", None, "v1:2053", "v2:2053:1", "v1:order:1", "v1:2053:block", "2053:1:v1"):
        assert started_row_order(value) is None


def test_the_verdict_is_started_once_a_row_names_the_order():
    rows = [("etny-sw", "v1:2053:0xabc:sig"), (ORDER_STARTED_KEY, "v1:2052:100"), (ORDER_STARTED_KEY, "v1:2053:101")]
    assert order_start_verdict(rows, 2053, 120, 111) == "started"
    assert ORDER_START_WINDOW_BLOCKS == 10


def test_the_verdict_is_waiting_inside_the_window_and_late_past_it():
    rows = [(ORDER_STARTED_KEY, "v1:2052:100")]
    assert order_start_verdict(rows, 2053, 111, 111) == "waiting"
    assert order_start_verdict(rows, 2053, 112, 111) == "late"
    assert order_start_verdict([], 2053, 112, 111) == "late"
