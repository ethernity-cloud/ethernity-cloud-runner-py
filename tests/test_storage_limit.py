"""INTAKE_MAX_BYTES: a blob above what the intake takes is not sent to it; it
is held in the client's local cache, upload_to_ipfs raises StorageLimitError
naming the cache and the remedy, and the held blobs go out through an API of
the application's own once one is set. requests is replaced by a recorder."""
import pytest

from ethernity_cloud_runner_py.ipfs import INTAKE_MAX_BYTES, IPFSClient, StorageLimitError, cidv1_raw

from test_ipfs_client import Response, post_answering

INTAKE = "https://ipfs.ethernity.cloud"


def intake_client(limit):
    return IPFSClient(f"{INTAKE}/api/v0", intake_url=INTAKE, network="bloxberg_testnet", intake_max_bytes=limit)


def test_the_public_limit_is_the_intakes_100_mib():
    assert INTAKE_MAX_BYTES == 100 * 1024 * 1024


def test_a_blob_above_the_limit_is_held_not_queued_and_the_error_names_the_cache_and_the_remedy(monkeypatch):
    calls = post_answering(monkeypatch)
    client = intake_client(16)
    assert client.upload_to_ipfs(b"x" * 16) == cidv1_raw(b"x" * 16)
    with pytest.raises(StorageLimitError) as refused:
        client.upload_to_ipfs(b"y" * 17)
    error = refused.value
    assert (error.cid, error.size, error.limit) == (cidv1_raw(b"y" * 17), 17, 16)
    assert "up to 16 bytes and this one is 17 bytes" in str(error)
    assert "held in the runner's local cache" in str(error)
    assert "set_storage_ipfs(url, token)" in str(error)
    assert client.held == {error.cid: b"y" * 17}
    assert error.cid not in client.pending
    assert calls == []


def test_the_held_blobs_are_uploaded_once_an_api_of_the_applications_own_is_set(monkeypatch):
    large = b"z" * 20
    cid = cidv1_raw(large)
    calls = post_answering(monkeypatch, Response(200, body={"Hash": cid}))
    intake = intake_client(16)
    with pytest.raises(StorageLimitError):
        intake.upload_to_ipfs(large)
    assert intake.upload_held() == ([], {})  # the intake takes none
    api = IPFSClient("http://127.0.0.1:5001/api/v0")
    api.held.update(intake.held)
    assert api.upload_held() == ([cid], {})
    assert api.held == {}
    assert calls[0][0] == "http://127.0.0.1:5001/api/v0/add"


def test_a_held_blob_the_api_names_otherwise_stays_held(monkeypatch):
    post_answering(monkeypatch, Response(200, body={"Hash": "bafkreiother"}))
    api = IPFSClient("http://127.0.0.1:5001/api/v0")
    api.held["bafkreiexpected"] = b"w" * 20
    uploaded, failed = api.upload_held()
    assert uploaded == [] and "bafkreiother" in failed["bafkreiexpected"]
    assert "bafkreiexpected" in api.held
