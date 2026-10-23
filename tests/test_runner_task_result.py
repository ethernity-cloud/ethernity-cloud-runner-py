"""EthernityCloudRunner: a task the enclave reports with a non-zero task code
ends in ERROR, with its error report kept as the result; the run's input
dataset is sent with the request. The LOCAL-mode runs talk to a stand-in for
the ecld-test API; the input metadata is built against a stand-in storage."""
import hashlib
import io
import json
import urllib.request

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.enums import ZERO_CHECKSUM
from ethernity_cloud_runner_py.runner import EthernityCloudRunner


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _local_api(monkeypatch, task_code, task_code_name, result):
    """Serve /v1/health and /v1/task; returns the list of task request bodies."""
    bodies = []

    def urlopen(req, timeout=None):
        if isinstance(req, str):
            return _Response(json.dumps({"backend": []}).encode())
        bodies.append(json.loads(req.data))
        return _Response(json.dumps({
            "task_code": task_code, "task_code_name": task_code_name,
            "result": result, "checksum": hashlib.sha256(result.encode()).hexdigest(),
        }).encode())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return bodies


def _run_local(**kwargs):
    r = EthernityCloudRunner("LOCAL", "LOCAL")
    r.run(None, "demo", "v3", "f()", **kwargs)
    r.task_thread.join(10)
    return r


def test_a_task_with_task_code_zero_succeeds(monkeypatch):
    _local_api(monkeypatch, 0, "SUCCESS", "ok")
    r = _run_local()
    state = r.get_state()
    assert state["status"] == "SUCCESS"
    assert state["last_error"] is None
    assert r.get_result()["success"] is True


def test_a_task_that_raised_in_the_enclave_is_an_error_with_its_report(monkeypatch):
    report = "BASE_EXCEPTION: RuntimeError('boom')\nTraceback ..."
    _local_api(monkeypatch, 4, "BASE_EXCEPTION", report)
    r = _run_local()
    state = r.get_state()
    assert state["status"] == "ERROR"
    assert "BASE_EXCEPTION (4)" in state["last_error"]
    result = r.get_result()
    assert result["success"] is False
    assert result["result_task_code_int"] == 4
    assert result["value"] == report


def test_the_input_dataset_reaches_the_task(monkeypatch):
    bodies = _local_api(monkeypatch, 0, "SUCCESS", "ok")
    _run_local(input_data="a,b,c\n1,2,3")
    assert bodies == [{"payload": "f()", "input": "a,b,c\n1,2,3"}]


def test_a_task_without_input_sends_none(monkeypatch):
    bodies = _local_api(monkeypatch, 0, "SUCCESS", "ok")
    _run_local()
    assert bodies[0]["input"] is None


class _Storage:
    def __init__(self):
        self.uploads = []

    def upload_to_ipfs(self, data):
        self.uploads.append(data)
        return "QmInput"


def _metadata_runner(monkeypatch, input_data, session=False):
    monkeypatch.setattr(runner_module, "encrypt", lambda data, key: b"sealed:" + data)
    r = EthernityCloudRunner("BLOXBERG", "TESTNET")
    storage = _Storage()
    r.storage = lambda: storage
    r.input_data = input_data
    r._session_request = session
    return r, storage


def test_an_input_dataset_is_uploaded_sealed_and_named_with_its_sha256(monkeypatch):
    data = "the dataset"
    r, storage = _metadata_runner(monkeypatch, data)
    assert r.get_v3_input_metadata() == f"v3:QmInput:{hashlib.sha256(data.encode()).hexdigest()}"
    assert storage.uploads == [b"sealed:" + data.encode()]
    assert r.file_set_hash == "QmInput"


def test_no_input_is_the_empty_metadata(monkeypatch):
    for empty in (None, ""):
        r, storage = _metadata_runner(monkeypatch, empty)
        assert r.get_v3_input_metadata() == f"v3::{ZERO_CHECKSUM}"
        assert storage.uploads == []


def test_a_session_request_carries_no_input(monkeypatch):
    r, storage = _metadata_runner(monkeypatch, "ignored", session=True)
    assert r.get_v3_input_metadata() == f"v3s::{ZERO_CHECKSUM}"
    assert storage.uploads == []


def test_input_data_must_be_a_string(monkeypatch):
    _local_api(monkeypatch, 0, "SUCCESS", "ok")
    r = EthernityCloudRunner("LOCAL", "LOCAL")
    try:
        r.run(None, "demo", "v3", "f()", input_data=b"bytes")
    except TypeError as e:
        assert "input_data" in str(e)
    else:
        raise AssertionError("bytes input_data was accepted")
