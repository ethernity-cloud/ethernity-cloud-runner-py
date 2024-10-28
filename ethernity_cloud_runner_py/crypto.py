import base64
import binascii
import codecs
import hashlib
import json
import secrets
from base64 import a85decode, a85encode
from typing import Any

from Crypto.Cipher import AES
from Crypto.PublicKey import ECC

# from cryptography.hazmat.primitives.asymmetric import ec
from nacl.public import Box, PrivateKey, PublicKey
from pyasn1.codec.der import decoder
from tinyec import ec, registry

curve = registry.get_curve("secp384r1")


def compress_point(point: Any) -> str:
    return hex(point.x) + hex(point.y % 2)[2:]


def ecc_point_to_256_bit_key(point: Any) -> bytes:
    value = str(point.x) + str(point.y)
    sha = hashlib.sha256(value.encode())
    return sha.digest()


def encrypt_aes_gcm(msg: bytes, secret_key: bytes) -> tuple:
    aes_cipher = AES.new(secret_key, AES.MODE_GCM)
    cipher_text, auth_tag = aes_cipher.encrypt_and_digest(msg)
    return (cipher_text, aes_cipher.nonce, auth_tag)


def encrypt_ecc(msg: bytes, public_key: Any) -> tuple:
    cipher_text_private_key = secrets.randbelow(curve.field.n)
    shared_ecc_key = cipher_text_private_key * public_key
    secret_key = ecc_point_to_256_bit_key(shared_ecc_key)
    ciphertext, nonce, auth_tag = encrypt_aes_gcm(msg, secret_key)
    cipher_text_public_key = cipher_text_private_key * curve.g
    return (ciphertext, nonce, auth_tag, cipher_text_public_key)


def decrypt_ase_gcm(
    ciphertext: bytes, nonce: bytes, auth_tag: bytes, secret_key: bytes
) -> bytes:
    aes_cipher = AES.new(secret_key, AES.MODE_GCM, nonce)
    plaintext = aes_cipher.decrypt_and_verify(ciphertext, auth_tag)
    return plaintext


def decrypt_ecc(encrypted_msg: tuple, priv_key: int) -> bytes:
    (ciphertext, nonce, authTag, ciphertextPubKey) = encrypted_msg
    shared_ecc_key = priv_key * ciphertextPubKey
    secret_key = ecc_point_to_256_bit_key(shared_ecc_key)
    plaintext = decrypt_ase_gcm(ciphertext, nonce, authTag, secret_key)
    return plaintext


def decrypt_nacl(private_key: str, encrypted_data_hex: str):
    """Decryption function corresponding to encrypt_nacl.

    Args:
        private_key: hex-encoded private key of the recipient (32 bytes).
        encrypted_data_hex: hex string of the encrypted data.

    Returns:
        Decrypted data as bytes.
    """
    try:
        # Convert recipient's private key from hex to PrivateKey object
        recipient_private_key = PrivateKey.from_seed(bytes.fromhex(private_key))

        # Convert the encrypted data from hex to bytes
        encrypted_data = bytes.fromhex(encrypted_data_hex)

        # Extract the ephemeral public key (first 32 bytes)
        emph_public_key_bytes = encrypted_data[:32]
        ciphertext = encrypted_data[32:]

        # Create PublicKey object for the ephemeral public key
        emph_public_key = PublicKey(emph_public_key_bytes)

        # Create a Box for decryption using recipient's private key and ephemeral public key
        dec_box = Box(recipient_private_key, emph_public_key)

        # Decrypt the ciphertext
        decrypted_data = dec_box.decrypt(ciphertext)

        # Decode the data from Ascii85 encoding
        original_data = a85decode(decrypted_data)

        return {"success": True, "data": original_data.decode()}
    except Exception as e:
        print("Decryption error:", str(e))
        return {"success": False, "data": str(e)}


def ecc_read_key(public_key_file: str) -> Any:
    with open(public_key_file) as r:
        key = ECC.import_key(r.read())
        return key


def encrypt(message: bytes, public_key_file: str) -> bytes:
    # with open(public_key_file) as f:
    ecc_public_cert = ECC.import_key(public_key_file)
    pub_key_ecc_point = ec.Point(
        curve,
        ecc_public_cert.pointQ.x.__int__(),
        ecc_public_cert.pointQ.y.__int__(),
    )
    encrypted_msg = encrypt_ecc(message, pub_key_ecc_point)
    return encrypted_data_to_base64_json(encrypted_msg)


def clean_private_key(private_key_data: bytes) -> bytes:
    private_key_data = private_key_data.replace(b"-----BEGIN PRIVATE KEY-----", b"")
    private_key_data = private_key_data.replace(b"-----END PRIVATE KEY-----", b"")
    private_key_data = codecs.decode(private_key_data, "base64")
    return private_key_data


def decrypt(private_key_file: str, encrypted_msg: tuple) -> bytes:
    # Reading and calculating Private Key from PEM
    with open(private_key_file) as f:
        private_key_data = str.encode(f.read())

    private_key_data = clean_private_key(private_key_data)
    # decode der with asn1 library
    # - get the octet string (field-2) containing the raw key
    asn1_object, _ = decoder.decode(private_key_data)
    raw_keys = asn1_object.getComponentByName("field-2").asOctets()
    # - get the octet string (field-1) containing the raw private key
    #   and the bit string (field-2) containing the uncompressed public key
    asn1_object, _ = decoder.decode(raw_keys)
    private_key = asn1_object.getComponentByName("field-1").asOctets()

    # Generating keypair for tinyEC
    priv_key_tec = int.from_bytes(private_key, byteorder="big")
    decrypted_msg = decrypt_ecc(encrypted_msg, priv_key_tec)
    print("\ndecrypted msg:", decrypted_msg)
    return decrypted_msg


def encrypted_data_to_base64_json(encrypted_msg: tuple) -> bytes:
    json_obj = {
        "ciphertext": binascii.hexlify(encrypted_msg[0]).decode(),
        "nonce": binascii.hexlify(encrypted_msg[1]).decode(),
        "authTag": binascii.hexlify(encrypted_msg[2]).decode(),
        "x": hex(encrypted_msg[3].x),
        "y": hex(encrypted_msg[3].y),
    }

    json_string = json.dumps(json_obj)
    binary_data = json_string.encode("utf-8")
    base64_data = base64.b64encode(binary_data)

    return base64_data


def encrypted_data_from_base64_json(base64_data: str) -> tuple:
    # decode the base64-encoded string back to a JSON string
    decoded_json_data = base64.b64decode(base64_data).decode("utf-8")

    json_load = json.loads(decoded_json_data)
    return (
        binascii.unhexlify(json_load["ciphertext"].encode()),
        binascii.unhexlify(json_load["nonce"].encode()),
        binascii.unhexlify(json_load["authTag"].encode()),
        ec.Point(curve, int(json_load["x"], 16), int(json_load["y"], 16)),
    )


def hex_to_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str[2:] if hex_str[:2] == "0x" else hex_str)


def encrypt_nacl(public_key: str, data: bytes) -> str:
    """Encryption function using NaCl box compatible with MetaMask
    For implementation used in MetaMask look into: https://github.com/MetaMask/eth-sig-util
    Args:
        public_key: public key of recipient (32 bytes)
        data: message data
    Returns:
        encrypted data
    """
    emph_key = PrivateKey.generate()
    enc_box = Box(emph_key, PublicKey(hex_to_bytes(public_key)))
    # Encryption must work with MetaMask decryption (requires valid utf-8)
    data = a85encode(data)
    ciphertext = enc_box.encrypt(data)
    result = bytes(emph_key.public_key) + ciphertext
    return result.hex()


# def compress_point(point: Any) -> str:
#     return hex(point.x) + hex(point.y % 2)[2:]


def sha256(value: str, as_hex: bool = False) -> bytes:
    sha = hashlib.sha256(value.encode()).hexdigest()
    return sha if as_hex else sha.encode()


# def encrypt_with_certificate(message: str, certificate: str) -> str:
#     public_key = load_certificate(certificate)
#     return encrypt(public_key, message)


# def decrypt_with_private_key(
#     encrypted_message: str, account: str
# ) -> dict[str, Any] | dict[str, bool]:
#     try:
#         data = bytes.fromhex(encrypted_message)
#         structured_data = {
#             "version": "x25519-xsalsa20-poly1305",
#             "ephemPublicKey": base64.b64encode(data[:32]).decode(),
#             "nonce": base64.b64encode(data[32:56]).decode(),
#             "ciphertext": base64.b64encode(data[56:]).decode(),
#         }
#         ct = f"0x{base64.b64encode(json.dumps(structured_data).encode()).decode()}"
#         decrypted_message = Web3.eth.account.decrypt(ct, account)
#         decoded_message = decrypted_message.decode("ascii")
#         return {"success": True, "data": decoded_message}
#     except Exception as e:
#         print(e)
#         return {"success": False}


# def encrypt(pub_key: str, message: str) -> str:
#     public_key_point = bytes.fromhex(pub_key)
#     encrypted_message = encrypt_ecc(message, public_key_point)
#     return encrypted_data_to_base64_json(encrypted_message)


# def load_certificate(certificate: str) -> str:
#     cert = x509.load_pem_x509_certificate(certificate.encode(), default_backend())
#     pub_key = cert.public_key()
#     pub_key_bytes = pub_key.public_bytes(
#         encoding=serialization.Encoding.DER,
#         format=serialization.PublicFormat.SubjectPublicKeyInfo,
#     )
#     return pub_key_bytes.hex()


# def encrypt_ecc(message: str, public_key_point_bytes: bytes) -> dict[str, Any]:
#     # Load the public key
#     public_key_point = serialization.load_der_public_key(
#         public_key_point_bytes, backend=default_backend()
#     )

#     # Ensure the public key is on the same curve as the private key
#     if not isinstance(public_key_point.curve, ec.SECP384R1):  # type: ignore
#         raise ValueError("Public key is not on the SECP384R1 curve")

#     # Generate a private key
#     private_key = ec.generate_private_key(ec.SECP384R1(), default_backend())

#     # Compute the shared key
#     shared_key = private_key.exchange(ec.ECDH(), public_key_point)  # type: ignore

#     derived_key = HKDF(
#         algorithm=hashes.SHA256(),
#         length=32,
#         salt=None,
#         info=None,
#         backend=default_backend(),
#     ).derive(shared_key)

#     # Generate a nonce for GCM mode
#     nonce = urandom(12)  # 12 bytes is a common choice for GCM nonce

#     # Initialize the cipher in GCM mode
#     cipher = Cipher(
#         algorithms.AES(derived_key), modes.GCM(nonce), backend=default_backend()
#     )
#     encryptor = cipher.encryptor()

#     # Encrypt the message
#     ciphertext = encryptor.update(message.encode()) + encryptor.finalize()

#     return {
#         "ciphertext": ciphertext,
#         "secretKey": derived_key,
#         "nonce": nonce,
#         "authTag": encryptor.tag,  # The authentication tag generated during encryption
#         "cipherTextPublicKey": private_key.public_key().public_bytes(
#             encoding=serialization.Encoding.PEM,
#             format=serialization.PublicFormat.SubjectPublicKeyInfo,
#         ),
#     }


# def encrypted_data_to_base64_json(encrypted_msg: dict) -> str:
#     public_key = serialization.load_pem_public_key(
#         encrypted_msg["cipherTextPublicKey"], backend=default_backend()
#     )

#     # Ensure the loaded key is an EC public key to access point attributes
#     if not isinstance(public_key, ec.EllipticCurvePublicKey):
#         raise ValueError("The key is not an elliptic curve public key")

#     # Extract the x and y coordinates of the public key
#     public_numbers = public_key.public_numbers()
#     x = public_numbers.x
#     y = public_numbers.y

#     json_obj = {
#         "ciphertext": base64.b64encode(encrypted_msg["ciphertext"]).decode(),
#         "nonce": base64.b64encode(encrypted_msg["nonce"]).decode(),
#         "authTag": base64.b64encode(encrypted_msg["authTag"]).decode(),
#         "x": x.to_bytes((x.bit_length() + 7) // 8, byteorder="big").hex(),
#         "y": y.to_bytes((y.bit_length() + 7) // 8, byteorder="big").hex(),
#     }
#     return base64.b64encode(json.dumps(json_obj).encode()).decode()
