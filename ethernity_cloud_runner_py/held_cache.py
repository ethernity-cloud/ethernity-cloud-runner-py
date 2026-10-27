"""The runner's held cache: the artefacts the public intake does not take
(above its size limit, ipfs.INTAKE_MAX_BYTES), kept on disk until an IPFS
endpoint of the application's own uploads them and a transaction on chain
names them. Every artefact is a file named by its CID under the cache
directory (~/.ethernity-cloud/held, or ETHERNITY_CLOUD_HELD_DIR), with
index.json mapping the artefact key the runner derives from the plaintext and
the enclave key it was sealed for (EthernityCloudRunner._seal_artefact) to
the CID, the ciphertext's digest, the size and whether it was uploaded, so a
run repeated after the upload references the held ciphertext's CID instead
of sealing the plaintext again. A directory that cannot keep the bytes raises
HeldCacheError, so the data is never dropped silently."""
import json
import os
import time
from typing import Any, Dict, Iterator, List, Optional

BLOCK_SIZE = 262144


class HeldCacheError(RuntimeError):
    """The cache directory could not keep or give back an artefact."""


def default_directory() -> str:
    return os.environ.get("ETHERNITY_CLOUD_HELD_DIR") or os.path.join(os.path.expanduser("~"), ".ethernity-cloud", "held")


class HeldCache:
    def __init__(self, directory: Optional[str] = None) -> None:
        self.directory = directory or default_directory()

    def location(self) -> str:
        """Where the bytes are kept, for the message that names it."""
        return self.directory

    def path(self, cid: str) -> str:
        return os.path.join(self.directory, f"{cid}.bin")

    def _index_path(self) -> str:
        return os.path.join(self.directory, "index.json")

    def _read_index(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self._index_path()) as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise HeldCacheError(f"the held cache index {self._index_path()} cannot be read: {e}")

    def _write_index(self, index: Dict[str, Dict[str, Any]]) -> None:
        path = self._index_path()
        with open(f"{path}.tmp", "w") as fh:
            json.dump(index, fh)
        os.replace(f"{path}.tmp", path)

    def put(self, key: str, cid: str, content: bytes, digest: str) -> str:
        """Keep `content` as `cid`'s file, indexed under `key`; the file's path."""
        try:
            os.makedirs(self.directory, exist_ok=True)
            with open(self.path(cid), "wb") as fh:
                fh.write(content)
        except OSError as e:
            raise HeldCacheError(f"{self.directory} cannot keep {len(content)} bytes: {e}")
        index = self._read_index()
        index[key] = {"key": key, "cid": cid, "size": len(content), "digest": digest, "uploaded": False,
                      "held_at": time.time()}
        self._write_index(index)
        return self.path(cid)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._read_index().get(key)

    def by_cid(self, cid: str) -> Optional[Dict[str, Any]]:
        return next((entry for entry in self._read_index().values() if entry["cid"] == cid), None)

    def entries(self) -> List[Dict[str, Any]]:
        return list(self._read_index().values())

    def read(self, cid: str) -> Iterator[bytes]:
        """The held bytes of `cid`, in BLOCK_SIZE chunks."""
        try:
            with open(self.path(cid), "rb") as fh:
                while True:
                    chunk = fh.read(BLOCK_SIZE)
                    if not chunk:
                        return
                    yield chunk
        except OSError as e:
            raise HeldCacheError(f"{cid} is not held: {e}")

    def mark_uploaded(self, cid: str) -> None:
        index = self._read_index()
        for entry in index.values():
            if entry["cid"] == cid:
                entry["uploaded"] = True
        self._write_index(index)

    def release(self, cid: str) -> None:
        """Forget `cid`: its index entries and its file."""
        index = self._read_index()
        for key in [key for key, entry in index.items() if entry["cid"] == cid]:
            del index[key]
        self._write_index(index)
        try:
            os.remove(self.path(cid))
        except FileNotFoundError:
            pass
        except OSError as e:
            raise HeldCacheError(f"{cid} could not be removed: {e}")

    def clear(self) -> None:
        for entry in self.entries():
            self.release(entry["cid"])
