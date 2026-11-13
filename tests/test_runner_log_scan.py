"""EthernityCloudRunner's event scans (find_order, the order's close) ask
eth_getLogs for at most GET_LOGS_MAX_BLOCKS blocks per call: the LitVM
LiteForge RPC Zeeve hosts refuses a wider range ("eth_getLogs range exceeds
3000 blocks; split the range"). No chain: the RPC is a stand-in that enforces
the limit and answers the logs inside each range."""
from types import SimpleNamespace

import pytest
from web3 import Web3

from ethernity_cloud_runner_py.runner import (
    EthernityCloudRunner, GET_LOGS_MAX_BLOCKS, GET_LOGS_TAIL_SLACK, log_scan_ranges,
)

CONTRACT = "0x" + "11" * 20
PLACED = "_orderPlacedEV(uint256,uint256,uint256)"
PLACED_TOPIC = Web3.keccak(text=PLACED)


def test_the_limit_is_the_zeeve_rpcs_three_thousand_blocks():
    assert GET_LOGS_MAX_BLOCKS == 3000
    assert 0 < GET_LOGS_TAIL_SLACK < GET_LOGS_MAX_BLOCKS


def test_a_scan_within_the_limit_less_the_slack_is_one_open_range():
    assert log_scan_ranges(100, 100) == [(100, "latest")]
    assert log_scan_ranges(100, 2999) == [(100, "latest")]


def test_a_scan_past_the_limit_is_split_into_ranges_of_at_most_the_limit():
    assert log_scan_ranges(100, 3099) == [(100, 3099), (3100, "latest")]
    assert log_scan_ranges(100, 3100) == [(100, 3099), (3100, "latest")]
    assert log_scan_ranges(100, 7000) == [(100, 3099), (3100, 6099), (6100, "latest")]
    for range_from, range_to in log_scan_ranges(0, 10 ** 6)[:-1]:
        assert range_to - range_from + 1 <= GET_LOGS_MAX_BLOCKS


def test_the_open_tail_leaves_the_slack_for_the_heads_advance_and_no_range_passes_the_head():
    for head in range(100, 20000, 37):
        ranges = log_scan_ranges(100, head)
        for range_from, range_to in ranges[:-1]:
            assert range_to <= head
            assert range_to - range_from + 1 <= GET_LOGS_MAX_BLOCKS
        tail_from, tail_to = ranges[-1]
        assert tail_to == "latest"
        assert head - tail_from + 1 <= GET_LOGS_MAX_BLOCKS - GET_LOGS_TAIL_SLACK


def test_a_head_behind_the_request_block_gives_the_one_open_range():
    assert log_scan_ranges(100, 98) == [(100, "latest")]


def _placed_log(block, order_no, do_req_id, dp_req_id=5):
    return {
        "blockNumber": block,
        "topics": [PLACED_TOPIC],
        "data": Web3().codec.encode(["uint256", "uint256", "uint256"], [order_no, do_req_id, dp_req_id]),
    }


def _rpc(head, logs):
    """A stand-in eth: block_number is `head`, get_logs refuses a range wider
    than GET_LOGS_MAX_BLOCKS and answers the logs of `logs` inside the range,
    recording every query."""
    queries = []

    def get_logs(query):
        queries.append(query)
        to_block = head if query["toBlock"] == "latest" else query["toBlock"]
        if to_block - query["fromBlock"] + 1 > GET_LOGS_MAX_BLOCKS:
            raise ValueError("eth_getLogs range exceeds 3000 blocks; split the range")
        return [log for log in logs
                if query["fromBlock"] <= log["blockNumber"] <= to_block and log["topics"] == query["topics"]]
    return SimpleNamespace(block_number=head, get_logs=get_logs), queries


def _runner(head, logs, orders=None):
    r = EthernityCloudRunner("LITVM", "LITEFORGE")
    eth, queries = _rpc(head, logs)
    w3 = SimpleNamespace(eth=eth, codec=Web3().codec, keccak=Web3.keccak)
    r.protocol_contract = SimpleNamespace(
        w3=w3, address=CONTRACT,
        caller=lambda: SimpleNamespace(_getOrder=lambda order_no: (orders or {})[order_no]),
    )
    return r, queries


def test_the_scan_asks_one_call_per_range_and_concatenates_their_logs_in_block_order():
    logs = [_placed_log(block, order_no, 9) for order_no, block in enumerate((150, 3099, 3100, 6500, 7000))]
    r, queries = _runner(head=7000, logs=logs)
    assert r._event_logs(PLACED, 100) == logs
    assert [(q["fromBlock"], q["toBlock"]) for q in queries] == [(100, 3099), (3100, 6099), (6100, "latest")]
    assert all(q["address"] == CONTRACT and q["topics"] == [PLACED_TOPIC] for q in queries)


def test_a_scan_within_the_limit_is_the_one_open_call():
    r, queries = _runner(head=2000, logs=[_placed_log(1500, 3, 9)])
    assert len(r._event_logs(PLACED, 100)) == 1
    assert [(q["fromBlock"], q["toBlock"]) for q in queries] == [(100, "latest")]


def test_an_order_placed_past_the_limit_after_the_request_is_found_through_the_ranges():
    order = (0, "0x" + "22" * 20, 9, 5, 0, 0)
    r, queries = _runner(head=7100, logs=[_placed_log(3500, 41, 8), _placed_log(7050, 42, 9)], orders={42: order})
    r.request_start_block = 100
    assert r.find_order(9) is True
    assert r.order_id == 42
    assert r.order == order
    assert len(queries) == 3


def test_the_limit_is_enforced_by_the_stand_in_rpc():
    eth, _ = _rpc(head=5000, logs=[])
    with pytest.raises(ValueError, match="split the range"):
        eth.get_logs({"fromBlock": 100, "toBlock": "latest", "topics": [PLACED_TOPIC]})
