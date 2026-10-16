"""EthernityCloudRunner: a DO request no node takes within the order wait is
cancelled; one a node booked before the cancel goes on with that order. No
chain: the contract, the order lookup and the clock are stand-ins."""
from types import SimpleNamespace

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

TX = "0x" + "cd" * 32


def _runner(cancel, order_after_cancel=None):
    r = EthernityCloudRunner("BLOXBERG", "TESTNET")
    r.running = True
    r.do_request = 9
    r.block_time = 1
    calls = {"cancel": []}

    def cancel_do_request(request_id):
        calls["cancel"].append(request_id)
        return cancel()
    r.contract = SimpleNamespace(cancel_do_request=cancel_do_request)
    r.wait_for_transaction_to_be_processed = lambda contract, tx, max_attempts=10: tx == TX

    def find_order(doreq):
        if calls["cancel"] and order_after_cancel is not None:
            r.order_id = order_after_cancel
            return True
        return False
    r.find_order = find_order
    return r, calls


def _clock(monkeypatch):
    t = {"now": 0.0}
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: t["now"])
    monkeypatch.setattr(runner_module.time, "sleep", lambda s: t.__setitem__("now", t["now"] + s))
    return t


def test_a_request_no_node_took_is_cancelled_after_the_wait(monkeypatch):
    t = _clock(monkeypatch)
    r, calls = _runner(cancel=lambda: TX)
    r.set_order_wait(30)
    assert r.check_order_for_task() is False
    assert calls["cancel"] == [9]
    assert t["now"] >= 30


def test_a_request_booked_before_the_cancel_goes_on_with_its_order(monkeypatch):
    _clock(monkeypatch)

    def refused():
        raise ValueError("execution reverted: status must be available")
    r, calls = _runner(cancel=refused, order_after_cancel=4)
    r.set_order_wait(30)
    assert r.check_order_for_task() is True
    assert r.order_id == 4


def test_a_failed_cancel_with_no_order_ends_the_wait(monkeypatch):
    _clock(monkeypatch)
    r, calls = _runner(cancel=lambda: "0x" + "00" * 32)
    r.set_order_wait(30)
    assert r.check_order_for_task() is False
    assert calls["cancel"] == [9]


def test_the_default_wait_is_ten_minutes(monkeypatch):
    t = _clock(monkeypatch)
    r, _ = _runner(cancel=lambda: TX)
    assert r.check_order_for_task() is False
    assert t["now"] >= runner_module.DEFAULT_ORDER_WAIT_SECONDS == 600
