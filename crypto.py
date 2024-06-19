import base64
import hashlib
import json
from web3 import Web3
from eth_account.messages import encode_defunct
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.PublicKey import ECC
from tinyec import registry
from tinyec import ec
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

curve = registry.get_curve("secp384r1")


def compress_point(point):
    return hex(point.x) + hex(point.y % 2)[2:]


def sha256(value, as_hex=False):
    sha = hashlib.sha256(value.encode()).hexdigest()
    return sha if as_hex else sha.encode()


def encrypt_with_certificate(message, certificate):
    public_key = load_certificate(certificate)
    return encrypt(public_key, message)


def decrypt_with_private_key(encrypted_message, account):
    try:
        data = bytes.fromhex(encrypted_message)
        structured_data = {
            "version": "x25519-xsalsa20-poly1305",
            "ephemPublicKey": base64.b64encode(data[:32]).decode(),
            "nonce": base64.b64encode(data[32:56]).decode(),
            "ciphertext": base64.b64encode(data[56:]).decode(),
        }
        ct = f"0x{base64.b64encode(json.dumps(structured_data).encode()).decode()}"
        decrypted_message = Web3.eth.account.decrypt(ct, account)
        decoded_message = decrypted_message.decode("ascii")
        return {"success": True, "data": decoded_message}
    except Exception as e:
        print(e)
        return {"success": False}


def encrypt(pub_key, message):
    public_key_point = bytes.fromhex(pub_key)
    encrypted_message = encrypt_ecc(message, public_key_point)
    return encrypted_data_to_base64_json(encrypted_message)


def load_certificate(certificate):
    cert = x509.load_pem_x509_certificate(certificate.encode(), default_backend())
    pub_key = cert.public_key()
    pub_key_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pub_key_bytes.hex()


def encrypt_ecc(message, public_key_point):
    cipher_text_private_key = get_random_bytes(32)
    shared_ecc_key = public_key_point.point_mul(cipher_text_private_key)
    secret_key = ecc_point_to_256_bit_key(shared_ecc_key)
    encrypted = encrypt_msg(message, secret_key)
    cipher_text_public_key = curve.g * cipher_text_private_key
    return {
        "ciphertext": encrypted["ciphertext"],
        "secretKey": secret_key,
        "nonce": encrypted["iv"],
        "authTag": encrypted["authTag"],
        "cipherTextPublicKey": cipher_text_public_key,
    }


def encrypt_msg(msg, secret_key):
    if len(secret_key) != 32:
        raise ValueError("Secret key must be 32 bytes (256 bits) long")

    iv = get_random_bytes(16)
    cipher = AES.new(secret_key, AES.MODE_GCM, nonce=iv)
    ciphertext, tag = cipher.encrypt_and_digest(msg.encode())
    return {
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "iv": base64.b64encode(iv).decode(),
        "authTag": base64.b64encode(tag).decode(),
    }


def encrypted_data_to_base64_json(encrypted_msg):
    key = encrypted_msg["cipherTextPublicKey"]
    json_obj = {
        "ciphertext": encrypted_msg["ciphertext"],
        "nonce": encrypted_msg["nonce"],
        "authTag": encrypted_msg["authTag"],
        "x": key.point.get_x().to_bytes().hex(),
        "y": key.point.get_y().to_bytes().hex(),
    }
    return base64.b64encode(json.dumps(json_obj).encode()).decode()


def ecc_point_to_256_bit_key(point):
    value = f"{point.get_x().to_bytes().hex()}{point.get_y().to_bytes().hex()}"
    hash_buffer = hashlib.sha256(value.encode()).digest()
    return hash_buffer
