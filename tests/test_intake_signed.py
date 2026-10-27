"""IPFSClient.deliver_signed: a queued blob is lodged with the intake under
the request owner's signature before the request names it; one the intake
takes leaves the queue, one it refuses stays for flush_pending after the row
(bloxberg testnet rig, 2026-10-26: two clients stopped between committing an
input's row and uploading its bytes, and the row without bytes held their
sessions until the deadline). requests is replaced by a recorder."""
from ethernity_cloud_runner_py.ipfs import IPFSClient, OWNER_SIGNATURE_HEADER, owner_signature_message

from test_ipfs_client import Response, post_answering, record_sleeps

INTAKE = "https://ipfs.ethernity.cloud"


def intake_client():
    return IPFSClient(f"{INTAKE}/api/v0", intake_url=INTAKE, network="bloxberg_testnet")


def test_the_message_names_the_network_and_the_request():
    assert owner_signature_message("bloxberg_testnet", 4935) == "etny-intake|bloxberg_testnet|4935"
    assert OWNER_SIGNATURE_HEADER == "X-Etny-Owner-Signature"


def test_a_lodged_blob_goes_out_with_the_signature_and_leaves_the_queue(monkeypatch):
    calls = post_answering(monkeypatch, Response(200, body={"status": "pinned"}))
    client = intake_client()
    cid = client.upload_to_ipfs(b"alpha")
    assert client.deliver_signed(7, "0xsignature", [cid]) == ([cid], {})
    assert client.pending == {}
    url, kwargs = calls[0]
    assert url == f"{INTAKE}/payload/bloxberg_testnet/7/{cid}"
    assert kwargs["headers"][OWNER_SIGNATURE_HEADER] == "0xsignature"
    assert kwargs["data"] == b"alpha"


def test_a_blob_an_intake_without_the_signed_path_refuses_stays_queued_for_the_delivery_after_the_row(monkeypatch):
    calls = post_answering(monkeypatch, Response(403, text='{"error": "the DO request does not name this cid"}'),
                           Response(200, body={"status": "pinned"}))
    record_sleeps(monkeypatch)
    client = intake_client()
    cid = client.upload_to_ipfs(b"beta")
    delivered, refused = client.deliver_signed(8, "0xsignature", [cid])
    assert delivered == [] and refused[cid].startswith("403 ")
    assert client.pending == {cid: b"beta"}
    assert len(calls) == 1
    client.flush_pending(8)
    assert client.pending == {}
    assert OWNER_SIGNATURE_HEADER not in calls[1][1]["headers"]


def test_a_5xx_is_tried_again_and_a_later_200_delivers(monkeypatch):
    calls = post_answering(monkeypatch, Response(503, text="IPFS unavailable"), Response(200, body={}))
    slept = record_sleeps(monkeypatch)
    client = intake_client()
    cid = client.upload_to_ipfs(b"gamma")
    assert client.deliver_signed(9, "0xsignature", [cid], attempts=3, delay=5) == ([cid], {})
    assert len(calls) == 2 and slept == [5]


def test_a_blob_never_queued_and_a_client_without_an_intake_deliver_nothing(monkeypatch):
    calls = post_answering(monkeypatch)
    assert intake_client().deliver_signed(10, "0xsignature", ["bafkreinotqueued"]) == ([], {})
    assert IPFSClient("http://127.0.0.1:5001/api/v0").deliver_signed(10, "0xsignature") == ([], {})
    assert calls == []
