from datetime import datetime
import random
import hashlib
import time
from eth_account import Account
from web3 import Web3
from web3.auto import w3

from crypto import sha256


def delay(seconds):
    return time.sleep(seconds)


def get_retry_delay(retry_count, base_delay=1):
    return base_delay * 2**retry_count


def format_date(dt=None):
    if not dt:
        dt = datetime.now()
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def generate_random_hex_of_size(size):
    return "".join(random.choice("0123456789abcdef") for _ in range(size))


def is_null_or_empty(value):
    return value is None or value == ""


def generate_wallet(client_challenge, enclave_challenge):
    try:
        encoded = client_challenge + enclave_challenge
        hash = sha256(sha256(encoded, True), True)
        wallet = Account.from_key(hash)
        return wallet.address
    except Exception as e:
        print(e)
        return False


def is_address(address):
    try:
        checksum_address = Web3.to_checksum_address(address)
    except Exception as e:
        return False
    return True


def parse_transaction_bytes(contract_abi, bytes_input):
    contract = w3.eth.contract(abi=contract_abi)
    decoded_data = contract.decode_function_input(bytes_input)
    return decoded_data
