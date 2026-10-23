"""IPFSClient: its construction, the add's answer handling, the intake queue.

requests is replaced by a recorder; no request leaves the process."""
import pytest

from ethernity_cloud_runner_py import ipfs
from ethernity_cloud_runner_py.ipfs import IPFSClient, RAW_BLOCK_PARAMS, cidv1_raw, unixfs_cid


class Response:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        return self._body


def post_answering(monkeypatch, *responses):
    """requests.post answers with `responses` in turn and records each call."""
    calls = []
    answers = list(responses)

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return answers.pop(0)

    monkeypatch.setattr(ipfs.requests, "post", post)
    return calls


def record_sleeps(monkeypatch):
    slept = []
    monkeypatch.setattr(ipfs.time, "sleep", slept.append)
    return slept


def test_api_url_is_required():
    with pytest.raises(TypeError):
        IPFSClient()


def test_token_is_the_authorization_header():
    assert IPFSClient("http://kubo:5001/api/v0", "writer-token").headers == {
        "authorization": "writer-token"}
    assert IPFSClient("http://kubo:5001/api/v0").headers == {}


def test_add_403_stops_at_once_and_names_the_remedies(monkeypatch):
    calls = post_answering(monkeypatch, Response(403, text="forbidden"))
    slept = record_sleeps(monkeypatch)
    client = IPFSClient("https://ipfs.ethernity.cloud/api/v0")
    with pytest.raises(RuntimeError) as failure:
        client.upload_to_ipfs(b"payload")
    message = str(failure.value)
    assert "https://ipfs.ethernity.cloud/api/v0/add" in message
    assert "403" in message
    assert "writer token" in message
    assert "set_storage_ipfs(url, token)" in message
    assert "set_public_intake()" in message
    assert len(calls) == 1
    assert slept == []


def test_add_401_stops_at_once(monkeypatch):
    calls = post_answering(monkeypatch, Response(401))
    record_sleeps(monkeypatch)
    with pytest.raises(RuntimeError):
        IPFSClient("http://kubo:5001/api/v0", "stale").upload_to_ipfs(b"payload")
    assert len(calls) == 1


def test_add_5xx_is_retried_then_gives_up(monkeypatch):
    calls = post_answering(monkeypatch, Response(502), Response(502), Response(502))
    slept = record_sleeps(monkeypatch)
    client = IPFSClient("http://kubo:5001/api/v0")
    assert client.upload_to_ipfs(b"payload", attempts=3, delay=7) is None
    assert len(calls) == 3
    assert slept == [7, 7]


def test_add_returns_the_hash(monkeypatch):
    calls = post_answering(monkeypatch, Response(200, body={"Hash": "bafkreigh2akiscaildc"}))
    client = IPFSClient("http://kubo:5001/api/v0", "writer-token")
    assert client.upload_to_ipfs(b"payload") == "bafkreigh2akiscaildc"
    url, kwargs = calls[0]
    assert url == "http://kubo:5001/api/v0/add"
    assert kwargs["headers"] == {"authorization": "writer-token"}
    assert kwargs["params"] == RAW_BLOCK_PARAMS


def test_intake_client_queues_the_bytes_without_a_request(monkeypatch):
    calls = post_answering(monkeypatch)
    client = IPFSClient("https://ipfs.ethernity.cloud/api/v0",
                        intake_url="https://ipfs.ethernity.cloud", network="bloxberg_testnet")
    cid = client.upload_to_ipfs(b"payload")
    assert cid == cidv1_raw(b"payload")
    assert client.pending == {cid: b"payload"}
    assert calls == []


def test_adds_use_kubos_default_chunk_size():
    assert ipfs.BLOCK_SIZE == 262144
    assert RAW_BLOCK_PARAMS["chunker"] == "size-262144"


def pattern(n):
    """The first n bytes of the byte values 0..250 repeated: the files Kubo
    0.36.0 and 0.42.0 named the CIDs below, through `add --cid-version=1
    --raw-leaves`, with the default chunker and with the chunker passed."""
    unit = bytes(range(251))
    return (unit * (n // len(unit) + 1))[:n]


def test_content_up_to_one_block_is_named_by_its_raw_cid():
    content = pattern(ipfs.BLOCK_SIZE)
    assert unixfs_cid(content) == cidv1_raw(content) == "bafkreibruh455iawsviqslif5c7uurdcfdemh22mtnytyzvnzn75kpejxy"


def test_content_above_one_block_is_named_by_its_unixfs_root():
    assert unixfs_cid(pattern(ipfs.BLOCK_SIZE + 1)) == "bafybeiexg2oqkfnj56l7fcmawswqbijt5shq4b5rg6a546uwpkqqzwjioi"
    assert unixfs_cid(pattern(648000)) == "bafybeicnawjqvxvtindqftaj5acjkqb6lh5sove2uqkdrzjkwooypl56zu"
    assert unixfs_cid(pattern(1048576)) == "bafybeiedpcapwld4tkgtzwahfofgn4wex5ryysf4se6hwpmlrsh4ntnrau"
    assert unixfs_cid(pattern(2621440)) == "bafybeichq3thyi62tokqze6l4467yvja3nw7w34y7w52vn6h7lyo7qgxoy"


def test_more_blocks_than_a_node_links_make_a_second_level():
    """184330 bytes in 1 KiB blocks are 181 leaves: 174 under one node and 7
    under another, both under the root (Kubo, chunker=size-1024)."""
    assert unixfs_cid(pattern(184330), block_size=1024) == "bafybeids2yxkrcqqq6cpa7lgs6hv5xpsfn2bctwvljcrq73hhhzhszxkvy"


def test_the_intake_queues_an_artefact_of_any_size_under_its_cid(monkeypatch):
    calls = post_answering(monkeypatch)
    client = IPFSClient("https://ipfs.ethernity.cloud/api/v0",
                        intake_url="https://ipfs.ethernity.cloud", network="bloxberg_testnet")
    content = pattern(648000)
    assert client.upload_to_ipfs(content) == "bafybeicnawjqvxvtindqftaj5acjkqb6lh5sove2uqkdrzjkwooypl56zu"
    assert client.pending == {"bafybeicnawjqvxvtindqftaj5acjkqb6lh5sove2uqkdrzjkwooypl56zu": content}
    assert calls == []


def test_flush_pending_posts_to_the_intake_without_a_token(monkeypatch):
    calls = post_answering(monkeypatch, Response(200))
    client = IPFSClient("https://ipfs.ethernity.cloud/api/v0",
                        intake_url="https://ipfs.ethernity.cloud/", network="bloxberg_testnet")
    cid = client.upload_to_ipfs(b"payload")
    client.flush_pending(42)
    url, kwargs = calls[0]
    assert url == f"https://ipfs.ethernity.cloud/payload/bloxberg_testnet/42/{cid}"
    assert kwargs["data"] == b"payload"
    assert "authorization" not in {name.lower() for name in kwargs["headers"]}
    assert client.pending == {}


def test_flush_pending_names_the_storage_an_unserved_network_needs(monkeypatch):
    calls = post_answering(
        monkeypatch, Response(404, text='{"error": "unknown network polygon_mainnet"}'))
    slept = record_sleeps(monkeypatch)
    client = IPFSClient("https://ipfs.ethernity.cloud/api/v0",
                        intake_url="https://ipfs.ethernity.cloud", network="polygon_mainnet")
    cid = client.upload_to_ipfs(b"payload")
    with pytest.raises(RuntimeError) as failure:
        client.flush_pending(7)
    message = str(failure.value)
    assert "https://ipfs.ethernity.cloud does not serve network polygon_mainnet" in message
    assert f"{cid} for request 7" in message
    assert "set_storage_ipfs(url, token)" in message
    assert "writer token" in message
    assert len(calls) == 1
    assert slept == []


def test_flush_pending_reports_any_other_refusal_as_the_intake_answered(monkeypatch):
    post_answering(
        monkeypatch, Response(403, text='{"error": "the DO request does not name this cid"}'))
    record_sleeps(monkeypatch)
    client = IPFSClient("https://ipfs.ethernity.cloud/api/v0",
                        intake_url="https://ipfs.ethernity.cloud", network="bloxberg_testnet")
    cid = client.upload_to_ipfs(b"payload")
    with pytest.raises(RuntimeError) as failure:
        client.flush_pending(7)
    assert str(failure.value).startswith(f"intake refused {cid} for request 7: 403 ")
