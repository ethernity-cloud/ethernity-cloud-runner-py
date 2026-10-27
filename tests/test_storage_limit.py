"""INTAKE_MAX_BYTES: a blob above what the intake takes is not sent to it; it
is held in the runner's held cache, upload_to_ipfs raises StorageLimitError
naming the cache and the remedy, the held blobs go out through an API of the
application's own once one is set, and release_held forgets them once a
transaction names them. requests is replaced by a recorder; the cache is a
directory of its own."""
import pytest

from ethernity_cloud_runner_py.held_cache import HeldCache
from ethernity_cloud_runner_py.ipfs import INTAKE_MAX_BYTES, IPFSClient, StorageLimitError, cidv1_raw

from test_ipfs_client import Response, post_answering

INTAKE = "https://ipfs.ethernity.cloud"


def intake_client(limit, cache):
    return IPFSClient(f"{INTAKE}/api/v0", intake_url=INTAKE, network="bloxberg_testnet",
                      intake_max_bytes=limit, held_cache=cache)


def test_the_public_limit_is_the_intakes_100_mib():
    assert INTAKE_MAX_BYTES == 100 * 1024 * 1024


def test_a_blob_above_the_limit_is_held_in_the_cache_not_queued_and_the_error_names_the_cache_and_the_remedy(monkeypatch, tmp_path):
    calls = post_answering(monkeypatch)
    cache = HeldCache(str(tmp_path))
    client = intake_client(16, cache)
    assert client.upload_to_ipfs(b"x" * 16) == cidv1_raw(b"x" * 16)
    with pytest.raises(StorageLimitError) as refused:
        client.upload_to_ipfs(b"y" * 17, held_key="plaintext-hash|enclave-key-hash")
    error = refused.value
    assert (error.cid, error.size, error.limit) == (cidv1_raw(b"y" * 17), 17, 16)
    assert "up to 16 bytes and this one is 17 bytes" in str(error)
    assert f"held in {tmp_path}" in str(error)
    assert "set_storage_ipfs(url, token)" in str(error)
    entry = client.held_entry("plaintext-hash|enclave-key-hash")
    assert (entry["cid"], entry["size"], entry["uploaded"]) == (error.cid, 17, False) and len(entry["digest"]) == 64
    assert error.cid not in client.pending
    assert list(cache.read(error.cid)) == [b"y" * 17]
    assert calls == []


def test_the_held_blobs_are_uploaded_once_an_api_of_the_applications_own_is_set_and_released_when_named(monkeypatch, tmp_path):
    large = b"z" * 20
    cid = cidv1_raw(large)
    calls = post_answering(monkeypatch, Response(200, body={"Hash": cid}))
    cache = HeldCache(str(tmp_path))
    intake = intake_client(16, cache)
    with pytest.raises(StorageLimitError):
        intake.upload_to_ipfs(large, held_key="key")
    assert intake.upload_held() == ([], {})  # the intake takes none
    api = IPFSClient("http://127.0.0.1:5001/api/v0", held_cache=cache)
    assert api.upload_held() == ([cid], {})
    assert calls[0][0] == "http://127.0.0.1:5001/api/v0/add"
    assert calls[0][1]["files"]["file"].name == cache.path(cid)  # streamed from its file, not loaded
    assert api.held_entry("key")["uploaded"] is True
    api.release_held([cid, None])
    assert api.held_entry("key") is None and cache.entries() == []


def test_a_held_blob_the_api_names_otherwise_stays_held(monkeypatch, tmp_path):
    post_answering(monkeypatch, Response(200, body={"Hash": "bafkreiother"}))
    cache = HeldCache(str(tmp_path))
    cache.put("key", "bafkreiexpected", b"w" * 20, "digest")
    api = IPFSClient("http://127.0.0.1:5001/api/v0", held_cache=cache)
    uploaded, failed = api.upload_held()
    assert uploaded == [] and "bafkreiother" in failed["bafkreiexpected"]
    assert api.held_entry("key")["uploaded"] is False
