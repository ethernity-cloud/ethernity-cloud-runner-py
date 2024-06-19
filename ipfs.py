from ipfshttpclient import connect
import time
from enum import Enum
from typing import Any


class ECError(Enum):
    IPFS_DOWNLOAD_ERROR = "IPFS_DOWNLOAD_ERROR"


class IPFSClient:
    def __init__(self, host: str, protocol: str, port: int, token: str):
        if "http" in host:
            self.ipfs = connect(host)
        elif token == "":
            self.ipfs = connect(f"{protocol}://{host}:{port}")
        else:
            self.ipfs = connect(
                f"{protocol}://{host}:{port}", headers={"authorization": token}
            )

    def upload_to_ipfs(self, code: str) -> Any:
        try:
            response = self.ipfs.add_str(code)
            return response
        except Exception as e:
            print(e)
            return None

    @staticmethod
    def get_retry_delay(retry_count: int, base_delay: int = 1) -> int:
        return base_delay * 2**retry_count

    def get_from_ipfs(self, hash: str, max_retries: int = 5) -> Any:
        res = ""
        retry_count = 0

        while retry_count < max_retries:
            try:
                file = self.ipfs.cat(hash)
                res += file.decode("utf-8")
                return res
            except Exception as error:
                print(error)
                retry_count += 1

                if retry_count < max_retries:
                    time.sleep(self.get_retry_delay(retry_count))
                    continue
                else:
                    raise Exception(ECError.IPFS_DOWNLOAD_ERROR)
