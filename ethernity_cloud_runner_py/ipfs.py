import base64
import hashlib
import time

import requests  # type: ignore

# Every blob the runner adds (challenge, code, input, session rows) is stored
# as a CIDv1 raw sha256 block: `cid-version=1&raw-leaves=true` makes the CID
# base32(0x01 0x55 0x12 0x20 || sha256(content)), so it can be computed from
# the bytes alone, without an IPFS node. The node pins results with the same
# recipe (mvp-pox-node utils.py cidv1_raw).
RAW_BLOCK_PARAMS = {"cid-version": "1", "raw-leaves": "true"}

# The bootnode's payload intake: a runner with no IPFS API of its own delivers
# each artefact to POST {intake}/payload/<network>/<doRequestId>/<cid> after
# the DO request is on chain; the intake accepts it only when that request
# names the CID and the bytes hash to it (mvp-pox-node ipfs_intake.py).
PUBLIC_INTAKE = "https://ipfs.ethernity.cloud"


def cidv1_raw(content: bytes) -> str:
    """The CID Kubo returns for `add` with RAW_BLOCK_PARAMS, from the bytes."""
    digest = hashlib.sha256(content).digest()
    raw = bytes([0x01, 0x55, 0x12, 0x20]) + digest
    return "b" + base64.b32encode(raw).decode("ascii").lower().rstrip("=")


class IPFSClient:
    """Uploads go to a configured Kubo RPC API, or, when `intake_url` is set,
    are computed locally and delivered to the public intake once the DO
    request exists (`flush_pending`). Reads always use `api_url`."""

    def __init__(
        self, api_url: str = "https://ipfs.ethernity.cloud/api/v0", token: str = "",
        intake_url: str = "", network: str = "",
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

    def upload_file(self, file_path: str) -> None:
        with open(file_path, "rb") as file:
            content = file.read()
        return self.upload_to_ipfs(content)

    def upload_to_ipfs(self, data: str) -> None:
        content = self._data_bytes(data)
        if self.intake_url:
            cid = cidv1_raw(content)
            self.pending[cid] = content
            return cid

        add_url = f"{self.api_url}/add"
        files = {"file": content}
        response = requests.post(add_url, params=RAW_BLOCK_PARAMS, files=files, headers=self.headers)

        if response.status_code == 200:
            try:
                response_data = response.json()
                ipfs_hash = response_data["Hash"]
                return ipfs_hash
            except Exception as e:
                return None
        else:
            print(f"Failed to upload to IPFS. Status code: {response.status_code}")
            return None

    def flush_pending(self, do_request: int, attempts: int = 3, delay: float = 5.0) -> None:
        """Deliver every queued blob to the intake for `do_request`. A blob the
        intake confirms (200) leaves the queue; one it refuses (4xx) raises at
        once, since retrying the same bytes cannot change the answer; a
        connection failure or 5xx is retried `attempts` times. No-op without an
        intake."""
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

    def download_file(
        self, ipfs_hash: str, download_path: str, attempt: int = 0
    ) -> None:
        gateway_url = f"https://ipfs.io/ipfs/{ipfs_hash}"
        response = requests.get(url=gateway_url, timeout=60, headers=self.headers)

        if response.status_code == 200:
            with open(download_path, "wb") as file:
                file.write(response.content)
            print(f"File downloaded successfully to {download_path}")
        else:
            print(
                f"Failed to download from IPFS. Attempt {attempt}. Status code: {response.status_code}. Response text: {response.text}.\n{'Trying again...' if attempt < 6 else ''}"
            )
            if attempt < 6:
                self.download_file(ipfs_hash, download_path, attempt + 1)

    def get_file_content(self, ipfs_hash: str) -> None:
        gateway_url = f"https://ipfs.io/ipfs/{ipfs_hash}"
        response = requests.get(url=gateway_url, timeout=30, headers=self.headers)

        if response.status_code == 200:
            # TODO: use a get encoding function to determine the encoding
            return response.content.decode("utf-8")

        url = self.api_url
        gateway_url = f"{url}/cat?arg={ipfs_hash}"
        response = requests.post(url=gateway_url, timeout=30, headers=self.headers)

        if response.status_code == 200:
            # TODO: use a get encoding function to determine the encoding
            return response.content.decode("utf-8")

        return None
