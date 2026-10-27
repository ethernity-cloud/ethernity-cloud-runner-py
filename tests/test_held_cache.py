"""held_cache.HeldCache: an artefact is kept as a file by its CID under its
artefact key with its digest, given back in BLOCK_SIZE chunks, marked
uploaded, released, and the index survives a new instance (a new process)."""
import pytest

from ethernity_cloud_runner_py.held_cache import BLOCK_SIZE, HeldCache, HeldCacheError

CID = "bafkreibobnv5ikag6zekcsihz2nsckfjg32uacwd3o6shtu3u7rxi3ot2m"
OTHER = "bafkreifgxs3pym3dkwr3uuio75l56jooxni3joe7vqcgb7jtjdguhirhle"


def test_an_artefact_is_kept_read_back_in_chunks_marked_uploaded_and_released(tmp_path):
    cache = HeldCache(str(tmp_path / "held"))
    path = cache.put("key-a", CID, b"\x07" * (BLOCK_SIZE + 10), "digest-a")
    cache.put("key-b", OTHER, b"\x01\x02\x03", "digest-b")
    assert path == cache.path(CID) and cache.location() == str(tmp_path / "held")
    entry = cache.get("key-a")
    assert (entry["cid"], entry["size"], entry["digest"], entry["uploaded"]) == (CID, BLOCK_SIZE + 10, "digest-a", False)
    assert cache.by_cid(OTHER)["key"] == "key-b"
    assert cache.get("key-none") is None
    chunks = list(cache.read(CID))
    assert [len(c) for c in chunks] == [BLOCK_SIZE, 10]
    cache.mark_uploaded(CID)
    assert cache.get("key-a")["uploaded"] is True and cache.get("key-b")["uploaded"] is False
    cache.release(CID)
    assert cache.get("key-a") is None and cache.by_cid(CID) is None
    with pytest.raises(HeldCacheError):
        list(cache.read(CID))
    assert [e["cid"] for e in cache.entries()] == [OTHER]
    cache.clear()
    assert cache.entries() == []


def test_the_index_survives_a_new_instance(tmp_path):
    first = HeldCache(str(tmp_path))
    first.put("key-c", CID, b"\x09\x09", "digest-c")
    second = HeldCache(str(tmp_path))
    assert second.get("key-c")["cid"] == CID
    assert list(second.read(CID)) == [b"\x09\x09"]
    assert (tmp_path / f"{CID}.bin").exists()
    second.release(CID)
    assert not (tmp_path / f"{CID}.bin").exists()


def test_the_default_directory_is_under_the_home_or_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("ETHERNITY_CLOUD_HELD_DIR", raising=False)
    assert HeldCache().location().endswith(".ethernity-cloud" + ("\\" if "\\" in HeldCache().location() else "/") + "held")
    monkeypatch.setenv("ETHERNITY_CLOUD_HELD_DIR", str(tmp_path / "elsewhere"))
    assert HeldCache().location() == str(tmp_path / "elsewhere")


def test_a_directory_that_cannot_be_written_raises(tmp_path):
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("x")
    with pytest.raises(HeldCacheError):
        HeldCache(str(blocked)).put("key", CID, b"bytes", "digest")
