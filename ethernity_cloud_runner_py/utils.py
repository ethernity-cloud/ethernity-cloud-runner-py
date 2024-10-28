from datetime import datetime
import random
import time
from typing import Any
from eth_account import Account
from web3 import Web3
from eth_utils.address import to_checksum_address

from eth_utils.hexadecimal import decode_hex, encode_hex

from .crypto import sha256

# from eth_abi import decode_abi
from eth_utils import function_signature_to_4byte_selector


from eth_account import Account
from eth_account._utils.legacy_transactions import (
    serializable_unsigned_transaction_from_dict,
)
from eth_utils import to_hex, decode_hex


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


# def parse_transaction_bytes_ut(contract_abi: Any, bytes_input: bytes) -> Any:
#     contract = w3.eth.contract(abi=contract_abi)
#     decoded_data = contract.decode_function_input(bytes_input)
#     return decoded_data


# def parse_transaction_bytes_ut(contract_abi, bytes_input):
#     # Connect to a Web3 provider (e.g., Infura, local node)
#     w3 = Web3(
#         Web3.HTTPProvider("https://core.bloxberg.org")
#     )  # Replace with your provider

#     # Parse the transaction
#     parsed_transaction = w3.eth.account.decode_transaction(bytes_input)
#     parsed_transaction = w3.eth.account.recover_transaction(bytes_input)
#     # Create a contract interface
#     contract_interface = w3.eth.contract(abi=contract_abi)

#     # Find the function signature
#     function_selector = parsed_transaction.input[:10]
#     function_abi = next(
#         (
#             item
#             for item in contract_abi
#             if function_signature_to_4byte_selector(item["name"]) == function_selector
#         ),
#         None,
#     )

#     if function_abi is None:
#         raise ValueError("Function ABI not found for the given selector")

#     # Decode the transaction data
#     decoded_data = contract_interface.decode_function_input(parsed_transaction.input)

#     return {
#         "from": parsed_transaction["from"],
#         "result": decoded_data[1][1],  # Assuming the result is the second argument
#     }


def parse_transaction_bytes_ut(contract_abi, bytes_input):
    import rlp
    from rlp.sedes import big_endian_int, Binary, binary
    from eth_utils import keccak, to_checksum_address, decode_hex
    from eth_keys import keys
    from web3 import Web3

    # Define the signed transaction class
    class SignedTransaction(rlp.Serializable):
        fields = [
            ("nonce", big_endian_int),
            ("gasPrice", big_endian_int),
            ("gas", big_endian_int),
            ("to", Binary.fixed_length(20, allow_empty=True)),
            ("value", big_endian_int),
            ("data", binary),
            ("v", big_endian_int),
            ("r", big_endian_int),
            ("s", big_endian_int),
        ]

    # Define the unsigned transaction class
    class UnsignedTransaction(rlp.Serializable):
        fields = [
            ("nonce", big_endian_int),
            ("gasPrice", big_endian_int),
            ("gas", big_endian_int),
            ("to", Binary.fixed_length(20, allow_empty=True)),
            ("value", big_endian_int),
            ("data", binary),
        ]

    # Convert hex string to bytes if necessary
    if isinstance(bytes_input, str):
        bytes_input = bytes_input.strip()
        if bytes_input.startswith("0x"):
            bytes_input = decode_hex(bytes_input)
        else:
            bytes_input = bytes.fromhex(bytes_input)

    # Decode the transaction using RLP
    try:
        tx = rlp.decode(bytes_input, SignedTransaction)
    except Exception as e:
        print(f"Error decoding transaction: {e}")
        return None

    # Create an unsigned transaction instance
    unsigned_tx = UnsignedTransaction(
        nonce=tx.nonce,
        gasPrice=tx.gasPrice,
        gas=tx.gas,
        to=tx.to,
        value=tx.value,
        data=tx.data,
    )
    # Create a Web3 instance
    w3 = Web3(Web3.HTTPProvider("https://core.bloxberg.org"))
    # Compute the transaction hash (the message hash used for signing)
    tx_hash = keccak(rlp.encode(unsigned_tx))

    # Recover the sender's public key and address
    v = tx.v
    if v >= 35:
        # EIP-155
        chain_id = (v - 35) // 2
        v_standard = v - (chain_id * 2 + 35) + 27
    else:
        chain_id = None
        v_standard = v

    try:
        # Build the signature object
        # signature = keys.Signature(vrs=(v_standard, tx.r, tx.s))

        # Recover the public key
        # public_key = signature.recover_public_key_from_msg_hash(tx_hash)

        sender_address = w3.eth.account.recover_transaction(bytes_input)
    except Exception as e:
        print(f"Error recovering sender address: {e}")
        return None

    # Decode the function input data
    try:
        contract = w3.eth.contract(abi=contract_abi)
        decoded_function = contract.decode_function_input(tx.data)
        function_name = decoded_function[0].fn_name
        params = decoded_function[1]
    except Exception as e:
        print(f"Error decoding function input: {e}")
        return None

    # Prepare the result
    result = {
        "from": sender_address,
        "to": to_checksum_address(tx.to) if tx.to else None,
        "nonce": tx.nonce,
        "gasPrice": tx.gasPrice,
        "gas": tx.gas,
        "value": tx.value,
        "function_name": function_name,
        "params": params,
        "transaction_hash": "0x" + keccak(bytes_input).hex(),
        "result": params["_result"] if "_result" in params else None,
    }

    return result
