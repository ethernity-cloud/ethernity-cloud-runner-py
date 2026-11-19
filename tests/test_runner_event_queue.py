"""EthernityCloudRunner: the events a run walks. run() queues the events of
one submission, INIT through FINISHED (_populate_event_queue), in place of
whatever the queue holds, and its task thread walks them in order. A run that
fails leaves the events it did not reach in the queue, where get_state()
reports them as remaining_events; the next run on the same runner starts at
INIT all the same, and so does the resubmission after an operator fault. No
chain and no ecld-test API: the contract, the registry, the submission steps
and urlopen are stand-ins."""
import io
import json
import urllib.request
from types import SimpleNamespace

import pytest

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.enums import ECNetwork
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

WALLET = "0x" + "11" * 20
POX = ECNetwork.BLOXBERG.TESTNET.PROTOCOL_ADDRESS
RESOURCES = {"taskPrice": 5, "cpu": 1, "memory": 1, "storage": 40, "bandwidth": 1, "duration": 1, "validators": 1}
SUBMISSION = ["INIT", "CREATED", "ORDER_PLACED", "IN_PROGRESS", "FINISHED"]
# The steps the stand-in runner records, in the order one submission reaches them.
WALK = ["balance", "enclave", "request", "order", "approval", "result"]
# (the step that is refused, the error the run ends with, the events processed before it)
FAILURES = [
    ("enclave", "Unable to find enclave in registry", []),
    ("request", "Unable to create a DO request", []),
    ("order", "Could not find any available operator matching this task request.", ["INIT"]),
    ("approval", "Task approval failed.", ["INIT", "CREATED"]),
    ("result", "Task processing failed.", ["INIT", "CREATED", "ORDER_PLACED"]),
]


def _runner(monkeypatch):
    """A BLOXBERG TESTNET runner with a funded wallet whose submission steps are stand-ins; runner.calls
    lists the steps of WALK that are reached. A step named in runner.refused fails, and each wait for the
    result takes the next entry of runner.faults, while there is one, as the fault of an operator that
    gave no result."""
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.signer = SimpleNamespace(address=WALLET)
    runner.calls = []
    runner.refused = set()
    runner.faults = []

    def step(name):
        def reached(*args):
            runner.calls.append(name)
            return name not in runner.refused
        return reached

    def process_task():
        runner.calls.append("result")
        if runner.faults:
            runner._fault = runner.faults.pop(0)
            return None
        return None if "result" in runner.refused else {"success": True}

    runner.contract = SimpleNamespace(
        protocol_address=POX,
        get_balance=lambda: runner.calls.append("balance") or 100,
        get_orders_count=lambda: 0,
        get_protocol_address=lambda: POX)
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(
        allowance=lambda owner, spender: SimpleNamespace(call=lambda: 10**30)))
    runner._resolve_storage = lambda: None
    runner.check_web3_connection = lambda: True
    runner.get_enclave_details = step("enclave")
    runner.create_task = step("request")
    runner.check_order_for_task = step("order")
    runner.approve_task = step("approval")
    runner.process_task = process_task
    monkeypatch.setattr(runner_module, "ImageRegistryContract", lambda *args: SimpleNamespace())
    return runner


def _run(runner, **kwargs):
    """A run to its end, run() and the task thread it starts; returns the state it ends in."""
    runner.run(RESOURCES, "securelock", "v3", "code", **kwargs)
    runner.task_thread.join(10)
    assert not runner.task_thread.is_alive()
    return runner.get_state()


def test_the_queue_of_a_run_is_the_events_of_one_submission():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner._populate_event_queue()
    assert runner.get_state()["remaining_events"] == SUBMISSION
    # Over a queue that holds the events a failed run did not reach.
    runner.event_queue.get()
    runner._populate_event_queue()
    assert runner.get_state()["remaining_events"] == SUBMISSION


def test_a_run_walks_the_events_of_one_submission(monkeypatch):
    runner = _runner(monkeypatch)
    state = _run(runner)
    assert state["status"] == "SUCCESS"
    assert state["processed_events"] == SUBMISSION
    assert state["remaining_events"] == []
    assert runner.calls == WALK


@pytest.mark.parametrize("step, error, processed", FAILURES)
def test_a_run_that_fails_reports_the_events_it_did_not_reach(monkeypatch, step, error, processed):
    runner = _runner(monkeypatch)
    runner.refused = {step}
    state = _run(runner)
    assert state["status"] == "ERROR"
    assert state["last_error"] == error
    assert state["processed_events"] == processed
    assert state["remaining_events"] == SUBMISSION[len(processed) + 1:]
    assert runner.calls == WALK[:WALK.index(step) + 1]
    assert runner.is_running() is False


@pytest.mark.parametrize("step, error, processed", FAILURES)
def test_the_run_after_one_that_failed_walks_one_whole_submission(monkeypatch, step, error, processed):
    runner = _runner(monkeypatch)
    runner.refused = {step}
    _run(runner)
    runner.refused = set()
    runner.calls.clear()
    state = _run(runner)
    assert state["status"] == "SUCCESS"
    assert state["last_error"] is None
    assert state["processed_events"] == SUBMISSION
    assert state["remaining_events"] == []
    assert runner.calls == WALK


def test_the_resubmission_after_an_operator_fault_walks_a_whole_submission_again(monkeypatch):
    runner = _runner(monkeypatch)
    runner.faults = ["the node withheld the result"]
    state = _run(runner, max_retries=1, retry_delay=0)
    assert state["status"] == "SUCCESS"
    assert state["processed_events"] == SUBMISSION[:3] + SUBMISSION
    assert state["remaining_events"] == []
    assert runner.calls == WALK + WALK


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _local_api(monkeypatch):
    """A stand-in for the ecld-test API behind urlopen: api["up"] says whether it answers, and api["tasks"]
    lists the bodies of the tasks posted to it."""
    api = {"up": True, "tasks": []}

    def urlopen(request, timeout=None):
        if not api["up"]:
            raise OSError("connection refused")
        if isinstance(request, str):
            return _Response(json.dumps({"backend": []}).encode())
        api["tasks"].append(json.loads(request.data))
        return _Response(json.dumps({
            "task_code": 0, "task_code_name": "SUCCESS", "result": "ok", "checksum": "00"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return api


def test_a_local_run_after_one_whose_api_did_not_answer_posts_its_task_once(monkeypatch):
    api = _local_api(monkeypatch)
    api["up"] = False
    runner = EthernityCloudRunner("LOCAL", "LOCAL")
    state = _run(runner)
    assert state["status"] == "ERROR"
    assert state["last_error"].startswith("Local test API not reachable")
    assert state["remaining_events"] == SUBMISSION[1:]
    api["up"] = True
    state = _run(runner)
    assert state["status"] == "SUCCESS"
    assert state["processed_events"] == SUBMISSION
    assert state["remaining_events"] == []
    assert api["tasks"] == [{"payload": "code", "input": None}]
