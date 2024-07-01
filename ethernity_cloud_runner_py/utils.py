from datetime import datetime
import random
import time
from typing import Any
from eth_account import Account
from web3.auto import w3
from eth_utils.address import to_checksum_address

from eth_utils.hexadecimal import decode_hex, encode_hex
from .crypto import sha256


def delay(seconds: int) -> None:
    return time.sleep(seconds)


def get_retry_delay(retry_count: int, base_delay: int = 1) -> int:
    return base_delay * 2**retry_count


def format_date(dt: datetime = datetime.now()) -> str:
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def generate_random_hex_of_size(size: int) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(size))


def is_null_or_empty(value: str) -> bool:
    return value is None or value == ""


def generate_wallet(client_challenge: str, enclave_challenge: str) -> Any:
    try:
        encoded = client_challenge + enclave_challenge
        hash = sha256(sha256(encoded, True), True)
        wallet = Account.from_key(hash)
        return wallet.address
    except Exception as e:
        print(e)
        return False


# def generate_wallet(challenge_hash, enclave_challenge):
#     private_key_bytes = hashlib.sha256((challenge_hash + enclave_challenge).encode()).digest()
#     private_key = keys.PrivateKey(private_key_bytes)
#     return private_key.public_key.to_checksum_address()


def is_address(address: str) -> bool:
    try:
        checksum_address = to_checksum_address(address)
    except Exception as e:
        return False
    return True


def parse_transaction_bytes(contract_abi: Any, bytes_input: bytes) -> Any:
    contract = w3.eth.contract(abi=contract_abi)
    decoded_data = contract.decode_function_input(bytes_input)
    return decoded_data
