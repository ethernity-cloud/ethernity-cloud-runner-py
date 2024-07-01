import base64
import hashlib
import json
from typing import Any
from web3 import Web3
from tinyec import registry
from tinyec import ec
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from os import urandom

curve = registry.get_curve("secp384r1")


def compress_point(point: Any) -> str:
    return hex(point.x) + hex(point.y % 2)[2:]


def sha256(value: str, as_hex: bool = False) -> str | bytes:
    sha = hashlib.sha256(value.encode()).hexdigest()
    return sha if as_hex else sha.encode()


def encrypt_with_certificate(message: str, certificate: str) -> str:
    public_key = load_certificate(certificate)
    return encrypt(public_key, message)


def decrypt_with_private_key(
    encrypted_message: str, account: str
) -> dict[str, Any] | dict[str, bool]:
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


def encrypt(pub_key: str, message: str) -> str:
    public_key_point = bytes.fromhex(pub_key)
    encrypted_message = encrypt_ecc(message, public_key_point)
    return encrypted_data_to_base64_json(encrypted_message)


def load_certificate(certificate: str) -> str:
    cert = x509.load_pem_x509_certificate(certificate.encode(), default_backend())
    pub_key = cert.public_key()
    pub_key_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pub_key_bytes.hex()


def encrypt_ecc(message: str, public_key_point_bytes: bytes) -> dict[str, Any]:
    # Load the public key
    public_key_point = serialization.load_der_public_key(
        public_key_point_bytes, backend=default_backend()
    )

    # Ensure the public key is on the same curve as the private key
    if not isinstance(public_key_point.curve, ec.SECP384R1):  # type: ignore
        raise ValueError("Public key is not on the SECP384R1 curve")

    # Generate a private key
    private_key = ec.generate_private_key(ec.SECP384R1(), default_backend())

    # Compute the shared key
    shared_key = private_key.exchange(ec.ECDH(), public_key_point)  # type: ignore

    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=None,
        backend=default_backend(),
    ).derive(shared_key)

    # Generate a nonce for GCM mode
    nonce = urandom(12)  # 12 bytes is a common choice for GCM nonce

    # Initialize the cipher in GCM mode
    cipher = Cipher(
        algorithms.AES(derived_key), modes.GCM(nonce), backend=default_backend()
    )
    encryptor = cipher.encryptor()

    # Encrypt the message
    ciphertext = encryptor.update(message.encode()) + encryptor.finalize()

    return {
        "ciphertext": ciphertext,
        "secretKey": derived_key,
        "nonce": nonce,
        "authTag": encryptor.tag,  # The authentication tag generated during encryption
        "cipherTextPublicKey": private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    }


def encrypted_data_to_base64_json(encrypted_msg: dict) -> str:
    public_key = serialization.load_pem_public_key(
        encrypted_msg["cipherTextPublicKey"], backend=default_backend()
    )

    # Ensure the loaded key is an EC public key to access point attributes
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ValueError("The key is not an elliptic curve public key")

    # Extract the x and y coordinates of the public key
    public_numbers = public_key.public_numbers()
    x = public_numbers.x
    y = public_numbers.y

    json_obj = {
        "ciphertext": base64.b64encode(encrypted_msg["ciphertext"]).decode(),
        "nonce": base64.b64encode(encrypted_msg["nonce"]).decode(),
        "authTag": base64.b64encode(encrypted_msg["authTag"]).decode(),
        "x": x.to_bytes((x.bit_length() + 7) // 8, byteorder="big").hex(),
        "y": y.to_bytes((y.bit_length() + 7) // 8, byteorder="big").hex(),
    }
    return base64.b64encode(json.dumps(json_obj).encode()).decode()
