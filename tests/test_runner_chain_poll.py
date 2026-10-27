"""EthernityCloudRunner reads the chain every CHAIN_POLL_SECONDS while it waits
for a receipt, for the order a node places and for the order's close, and
gives a receipt up after `max_attempts` blocks. No chain: the provider, the
contract and the clock are stand-ins."""
from types import SimpleNamespace

from web3.exceptions import TransactionNotFound

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.runner import EthernityCloudRunner, CHAIN_POLL_SECONDS

TX = "0x" + "ab" * 32
BLOCK_TIME = 30


def _clock(monkeypatch):
    t = {"now": 0.0, "sleeps": []}
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: t["now"])

    def sleep(s):
        t["sleeps"].append(s)
        t["now"] += s
    monkeypatch.setattr(runner_module.time, "sleep", sleep)
    return t


def _runner(receipt_after_reads):
    """A runner whose provider raises TransactionNotFound for the first
    `receipt_after_reads` receipt reads and then answers a mined receipt."""
    r = EthernityCloudRunner("BLOXBERG", "TESTNET")
    r.running = True
    r.block_time = BLOCK_TIME
    reads = {"n": 0}

    def get_transaction_receipt(tx_hash):
        assert tx_hash == TX
        reads["n"] += 1
        if reads["n"] <= receipt_after_reads:
            raise TransactionNotFound(tx_hash)
        return {"status": 1, "blockNumber": 7}
    eth = SimpleNamespace(get_transaction_receipt=get_transaction_receipt)
    r.contract = SimpleNamespace(get_provider=lambda: SimpleNamespace(eth=eth))
    return r, reads


def test_the_receipt_is_read_every_poll_interval_not_every_block(monkeypatch):
    t = _clock(monkeypatch)
    r, reads = _runner(receipt_after_reads=3)
    assert r.poll_transaction(TX, max_attempts=10) == {"status": 1, "blockNumber": 7}
    assert reads["n"] == 4
    assert t["sleeps"] == [CHAIN_POLL_SECONDS] * 3
    assert t["now"] == 3 * CHAIN_POLL_SECONDS < BLOCK_TIME


def test_a_receipt_is_given_up_after_max_attempts_blocks(monkeypatch):
    t = _clock(monkeypatch)
    r, reads = _runner(receipt_after_reads=10 ** 6)
    assert r.poll_transaction(TX, max_attempts=4) is None
    assert t["now"] == 4 * BLOCK_TIME
    assert reads["n"] == 4 * BLOCK_TIME // CHAIN_POLL_SECONDS + 1


def test_the_placed_order_is_looked_for_every_poll_interval(monkeypatch):
    t = _clock(monkeypatch)
    r, _ = _runner(receipt_after_reads=0)
    r.do_request = 9
    looks = {"n": 0}

    def find_order(doreq):
        looks["n"] += 1
        return looks["n"] == 4
    r.find_order = find_order
    assert r.check_order_for_task() is True
    assert looks["n"] == 4
    assert t["now"] == 3 * CHAIN_POLL_SECONDS
