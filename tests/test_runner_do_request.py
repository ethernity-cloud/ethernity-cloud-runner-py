"""EthernityCloudRunner: the DO request id of a run, do_request_id, read by
ecld-run. No chain: the contract, the receipt and its event log are stand-ins."""
from types import SimpleNamespace

from ethernity_cloud_runner_py.runner import EthernityCloudRunner

RESOURCES = {"taskPrice": 1, "cpu": 1, "memory": 1, "storage": 1,
             "bandwidth": 1, "duration": 1, "validators": 1}
TX = "0x" + "ab" * 32


def _runner_with_request_event(row_number):
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.resources = RESOURCES
    runner.running = True
    eth = SimpleNamespace(get_transaction_receipt=lambda tx_hash: {"status": 1})
    runner.contract = SimpleNamespace(add_do_request=lambda *args: TX,
                                      get_provider=lambda: SimpleNamespace(eth=eth))
    log = SimpleNamespace(args=SimpleNamespace(_rowNumber=row_number))
    event = SimpleNamespace(process_receipt=lambda receipt, errors: [log])
    runner.protocol_contract = SimpleNamespace(
        events=SimpleNamespace(_addDORequestEV=lambda: event))
    return runner


def test_a_runner_without_a_request_reports_minus_one():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    assert runner.do_request == -1
    assert runner.do_request_id == -1


def test_the_do_request_id_is_the_row_number_of_the_request_event():
    runner = _runner_with_request_event(12)
    assert runner.create_do_request("image", "code", "input", "") is True
    assert runner.do_hash == TX
    assert runner.do_request == 12
    assert runner.do_request_id == 12


def test_a_receipt_without_the_request_event_leaves_no_request_id():
    runner = _runner_with_request_event(12)
    runner.protocol_contract.events._addDORequestEV().process_receipt = lambda receipt, errors: []
    assert runner.create_do_request("image", "code", "input", "") is False
    assert runner.do_request == -1
    assert runner.do_request_id == -1


def test_attach_task_reads_the_orders_request():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    order = (0, "0x" + "00" * 20, 13)
    runner.protocol_contract = SimpleNamespace(
        caller=lambda: SimpleNamespace(_getOrder=lambda order_id: order))
    runner.get_result_from_order = lambda order_id: None
    assert runner.attach_task(7) is None
    assert runner.order_id == 7
    assert runner.do_request_id == 13


def test_reset_clears_the_do_request_id():
    runner = _runner_with_request_event(13)
    runner.create_do_request("image", "code", "input", "")
    runner.reset()
    assert runner.do_request == -1
    assert runner.do_request_id == -1
