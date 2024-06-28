from datetime import datetime
import random
import hashlib
import time
from eth_account import Account
from web3 import Web3
from web3.auto import w3

# from eth_keys import keys
from eth_utils.hexadecimal import decode_hex, encode_hex
from .crypto import sha256


def delay(seconds):
    return time.sleep(seconds)


def get_retry_delay(retry_count, base_delay=1):
    return base_delay * 2**retry_count


def format_date(dt=None):
    if not dt:
        dt = datetime.now()
    return dt.strftime("%d/%m/%Y %H:%M:%S")


# def format_date():
#     from datetime import datetime
#     return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def generate_random_hex_of_size(size):
    return "".join(random.choice("0123456789abcdef") for _ in range(size))


# def generate_random_hex_of_size(size):
#     return ''.join(random.choices(string.hexdigits, k=size)).lower()


def is_null_or_empty(value: str) -> bool:
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


# def generate_wallet(challenge_hash, enclave_challenge):
#     private_key_bytes = hashlib.sha256((challenge_hash + enclave_challenge).encode()).digest()
#     private_key = keys.PrivateKey(private_key_bytes)
#     return private_key.public_key.to_checksum_address()


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


# def parse_transaction_bytes(abi, bytes):
#     from eth_abi import decode_abi
#     function_hash = bytes[:10]  # First 4 bytes (10 hex chars) of the data are the function selector
#     function_abi = next(item for item in abi if item['type'] == 'function' and item['signature'] == function_hash)
#     decoded_data = decode_abi([param['type'] for param in function_abi['inputs']], decode_hex(bytes[10:]))
#     return {function_abi['name']: decoded_data}
