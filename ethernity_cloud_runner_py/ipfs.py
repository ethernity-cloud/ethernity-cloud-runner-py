import requests  # type: ignore


class IPFSClient:
    def __init__(
        self, api_url: str = "http://ipfs.ethernity.cloud:5001/api/v0", token: str = ""
    ) -> None:
        self.api_url = api_url
        self.headers = {}
        if token:
            self.headers = {"authorization": token}

    def upload_file(self, file_path: str) -> None:
        add_url = f"{self.api_url}/add"

        with open(file_path, "rb") as file:
            files = {"file": file}
            response = requests.post(add_url, files=files, headers=self.headers)

        if response.status_code == 200:
            try:
                response_data = response.json()
                ipfs_hash = response_data["Hash"]
                print(f"Successfully uploaded to IPFS. Hash: {ipfs_hash}")
                return ipfs_hash
            except Exception as e:
                print(f"Failed to upload to IPFS. Error: {e}")
                return None
        else:
            print(f"Failed to upload to IPFS. Status code: {response.status_code}")
            print(response.text)
            return None

    def upload_to_ipfs(self, data: str) -> None:
        add_url = f"{self.api_url}/add"
        files = {"file": data}
        response = requests.post(add_url, files=files, headers=self.headers)

        if response.status_code == 200:
            try:
                response_data = response.json()
                ipfs_hash = response_data["Hash"]
                print(f"Successfully uploaded to IPFS. Hash: {ipfs_hash}")
                return ipfs_hash
            except Exception as e:
                print(f"Failed to upload to IPFS. Error: {e}")
                return None
        else:
            print(f"Failed to upload to IPFS. Status code: {response.status_code}")
            print(response.text)
            return None

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

    def get_file_content(self, ipfs_hash: str, attempt: int = 0) -> None:
        url = self.api_url
        gateway_url = f"{url}/cat?arg={ipfs_hash}"
        response = requests.post(url=gateway_url, timeout=60, headers=self.headers)

        if response.status_code == 200:
            # TODO: use a get encoding function to determine the encoding
            return response.content.decode("utf-8")
        else:
            print(
                f"Failed to get content from IPFS. Attempt {attempt}. Status code: {response.status_code}. Response text: {response.text}.\n{'Trying again...' if attempt < 6 else ''}"
            )
            if attempt < 6:
                self.get_file_content(ipfs_hash, attempt + 1)

        return None


# Example usage
if __name__ == "__main__":
    file_path = "./input.txt"  # Replace with your file path
    download_path = "./downloaded_file.txt"  # Replace with your desired download path

    ipfs_client = IPFSClient()

    # Upload file to IPFS
    ipfs_hash = ipfs_client.upload_file(file_path)

    if ipfs_hash:
        # Download file from IPFS
        ipfs_client.download_file(ipfs_hash, download_path)
