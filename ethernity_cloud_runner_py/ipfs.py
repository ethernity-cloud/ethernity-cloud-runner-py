import base64
import hashlib
import time
from typing import Optional

import requests  # type: ignore

# Every blob the runner adds (challenge, code, input, session rows) is stored
# as Kubo's `add --cid-version=1 --raw-leaves` stores it with its default
# chunker: in raw sha256 blocks of BLOCK_SIZE bytes (the last one shorter), a
# single block as it is, several under a balanced UnixFS tree of at most
# LINKS_PER_NODE blocks per node. unixfs_cid() computes the resulting CID from
# the bytes alone, without an IPFS node, and an IPFS node adding the same
# bytes with its default settings names them the same; the chunker is passed
# all the same, for a node whose default was changed. The node adds with the
# same parameters (mvp-pox-node utils.py add_bytes_raw).
BLOCK_SIZE = 262144
LINKS_PER_NODE = 174
RAW_BLOCK_PARAMS = {"cid-version": "1", "raw-leaves": "true", "chunker": f"size-{BLOCK_SIZE}"}

# The bootnode's payload intake: a runner with no IPFS API of its own delivers
# each artefact to POST {intake}/payload/<network>/<doRequestId>/<cid> after
# the DO request is on chain; the intake accepts it only when that request
# names the CID and the bytes hash to it (mvp-pox-node ipfs_intake.py).
PUBLIC_INTAKE = "https://ipfs.ethernity.cloud"
# The networks the intake serves, by the node agent's name for them: those the
# bootnode's agent runs (mvp-pox-node registers an intake backend per network
# handle). A runner on another network configures its storage itself.
INTAKE_NETWORKS = ("bloxberg_testnet", "bloxberg_testnet_unsafe", "litvm_liteforge", "litvm_liteforge_unsafe",
                   "ethereum_sepolia", "ethereum_sepolia_unsafe")

# The public gateway a blob is read from when the configured API does not
# answer: a mirror of the same content, reached without credentials.
PUBLIC_GATEWAY = "https://ipfs.io/ipfs"

# (connect, read) timeout of one read request; a request past it is abandoned
# and the next endpoint tried.
READ_TIMEOUT = (10, 60)


def _b32(cid: bytes) -> str:
    return "b" + base64.b32encode(cid).decode("ascii").lower().rstrip("=")


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(number: int, wire: int, payload: bytes) -> bytes:
    """A protobuf field: varint (wire 0) or length-delimited (wire 2)."""
    tag = _varint((number << 3) | wire)
    return tag + (_varint(len(payload)) + payload if wire == 2 else payload)


def _raw_cid(content: bytes) -> bytes:
    """CIDv1, codec raw (0x55), sha2-256 (0x12, 32 bytes)."""
    return bytes([0x01, 0x55, 0x12, 0x20]) + hashlib.sha256(content).digest()


def _file_node(children):
    """A dag-pb UnixFS File node over `children`, each (cid, tsize, filesize);
    returns (cid, tsize, filesize). Links come before Data in dag-pb; a link
    carries the child's CID, an empty Name and its Tsize, the size of the
    child's subtree; Data is UnixFS Type=File(2), filesize, blocksizes."""
    links = b"".join(
        _field(2, 2, _field(1, 2, cid) + _field(2, 2, b"") + _field(3, 0, _varint(tsize)))
        for cid, tsize, _ in children)
    filesize = sum(size for _, _, size in children)
    data = _field(1, 0, _varint(2)) + _field(3, 0, _varint(filesize))
    data += b"".join(_field(4, 0, _varint(size)) for _, _, size in children)
    block = links + _field(1, 2, data)
    cid = bytes([0x01, 0x70, 0x12, 0x20]) + hashlib.sha256(block).digest()
    return cid, len(block) + sum(tsize for _, tsize, _ in children), filesize


def unixfs_cid(content: bytes, block_size: int = BLOCK_SIZE) -> str:
    """The CID Kubo gives `content` for `add` with RAW_BLOCK_PARAMS: the raw
    block's CID up to one block, else the root of the balanced UnixFS tree
    over the blocks, LINKS_PER_NODE to a node, every node full but the last."""
    if len(content) <= block_size:
        return _b32(_raw_cid(content))
    nodes = [(_raw_cid(content[i:i + block_size]), len(content[i:i + block_size]), len(content[i:i + block_size]))
             for i in range(0, len(content), block_size)]
    while len(nodes) > 1:
        nodes = [_file_node(nodes[i:i + LINKS_PER_NODE]) for i in range(0, len(nodes), LINKS_PER_NODE)]
    return _b32(nodes[0][0])


def cidv1_raw(content: bytes) -> str:
    """The CID of `content` as one raw block: its CID through RAW_BLOCK_PARAMS
    up to BLOCK_SIZE bytes."""
    return _b32(_raw_cid(content))


class IPFSClient:
    """Uploads go to the Kubo RPC API at `api_url`, with `token` as the
    Authorization header of every request, or, when `intake_url` is set, are
    computed locally and delivered to the public intake once the DO request
    exists (`flush_pending`). Reads always use `api_url`."""

    def __init__(
        self, api_url: str, token: str = "", intake_url: str = "", network: str = "",
    ) -> None:
        self.api_url = api_url
        self.headers = {}
        if token:
            self.headers = {"authorization": token}
        self.intake_url = intake_url.rstrip("/")
        self.network = network
        # cid -> bytes awaiting delivery to the intake.
        self.pending = {}

    def _data_bytes(self, data):
        return data if isinstance(data, bytes) else str(data).encode("utf-8")

    def upload_to_ipfs(self, data: str, attempts: int = 3, delay: float = 5.0) -> Optional[str]:
        """Add one blob and return its CID, or None. An add the API does not
        answer within the timeout, or answers with a 5xx, is retried
        `attempts` times. A 401 or 403 raises at once: the API admits only a
        caller with a writer token, which repeating the add cannot supply.

        Through the intake the CID is computed here (unixfs_cid) and the bytes
        are delivered by flush_pending once the request names the CID."""
        content = self._data_bytes(data)
        if self.intake_url:
            cid = unixfs_cid(content)
            self.pending[cid] = content
            return cid

        add_url = f"{self.api_url}/add"
        for attempt in range(attempts):
            try:
                response = requests.post(add_url, params=RAW_BLOCK_PARAMS, files={"file": content},
                                         headers=self.headers, timeout=(10, 60))
            except requests.RequestException as e:
                print(f"IPFS upload attempt {attempt + 1}/{attempts} failed: {e}")
            else:
                if response.status_code == 200:
                    try:
                        return response.json()["Hash"]
                    except Exception:
                        return None
                if response.status_code in (401, 403):
                    raise RuntimeError(
                        f"{add_url} refused the add ({response.status_code}): this API's add "
                        "takes a writer token, passed as the second argument of "
                        "set_storage_ipfs(url, token) and sent as the Authorization header; "
                        "set_public_intake() delivers through the bootnode's payload intake "
                        "and needs no token.")
                print(f"Failed to upload to IPFS. Status code: {response.status_code}")
                if response.status_code < 500:
                    return None
            if attempt + 1 < attempts:
                time.sleep(delay)
        return None

    def flush_pending(self, do_request: int, attempts: int = 3, delay: float = 5.0) -> None:
        """Deliver every queued blob to the intake for `do_request`. A blob the
        intake confirms (200) leaves the queue; one it refuses (4xx) raises at
        once, since retrying the same bytes cannot change the answer, and the
        404 for a network the intake does not serve names the storage such a
        network needs; a connection failure or 5xx is retried `attempts`
        times. No-op without an intake."""
        if not self.intake_url or not self.pending:
            return
        for cid in list(self.pending):
            url = f"{self.intake_url}/payload/{self.network}/{do_request}/{cid}"
            last = None
            for attempt in range(attempts):
                try:
                    response = requests.post(url, data=self.pending[cid], timeout=120,
                                             headers={"Content-Type": "application/octet-stream"})
                except requests.RequestException as e:
                    last = f"{e}"
                else:
                    if response.status_code == 200:
                        del self.pending[cid]
                        break
                    if response.status_code == 404 and "unknown network" in response.text:
                        raise RuntimeError(
                            f"{self.intake_url} does not serve network {self.network} (the "
                            "intake serves the networks the bootnode's agent runs), so "
                            f"{cid} for request {do_request} stays undelivered: on this "
                            "network deliver through set_storage_ipfs(url, token), a Kubo "
                            "RPC API of your own or the public API with a writer token.")
                    if 400 <= response.status_code < 500 and response.status_code != 409:
                        raise RuntimeError(
                            f"intake refused {cid} for request {do_request}: "
                            f"{response.status_code} {response.text[:200]}")
                    last = f"{response.status_code} {response.text[:200]}"
                if attempt + 1 < attempts:
                    time.sleep(delay)
            else:
                raise RuntimeError(
                    f"intake did not accept {cid} for request {do_request} after "
                    f"{attempts} attempts: {last}")

    def get_file_content(self, ipfs_hash: str) -> Optional[str]:
        """Read one blob as UTF-8: the configured API first, the public
        gateway second, each request bounded by READ_TIMEOUT. None when
        neither answered with the content; the caller decides whether to ask
        again."""
        reads = (
            lambda: requests.post(f"{self.api_url}/cat?arg={ipfs_hash}", timeout=READ_TIMEOUT,
                                  headers=self.headers),
            lambda: requests.get(f"{PUBLIC_GATEWAY}/{ipfs_hash}", timeout=READ_TIMEOUT),
        )
        for read in reads:
            try:
                response = read()
            except requests.RequestException:
                continue
            if response.status_code == 200:
                return response.content.decode("utf-8")
        return None
