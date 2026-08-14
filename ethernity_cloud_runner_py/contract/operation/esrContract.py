"""Read-only client for the Enclave State Registry (ESR).

Enclaves publish a pointer to their encrypted state here, one entry per
(enclave, key), with a monotonic version.

## What a client can and cannot see

State is encrypted with a key derived from the ENCLAVE IDENTITY, so only that
enclave can decrypt it. This client therefore exposes METADATA only: the
version, when it last changed, and the pointer. That is deliberate -- state is
the payload's private working memory, and anything a dApp should see is returned
by a function the payload chooses to expose, rather than by making the whole
state readable.

Useful things you can still do with metadata: prove state advanced (the version
bumped), show when it last changed, or wait for a task's effect to land before
re-reading.
"""

import time
from typing import Any, Optional

from eth_utils.address import to_checksum_address
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from ...contract.abi.esrAbi import contract
from ...enums import ECNetwork


class ESRContract:
    def __init__(
        self,
        network_name="BLOXBERG",
        network_type="TESTNET",
        registry_address=None,
        request_kwargs=None,
    ):
        network_class = getattr(ECNetwork, network_name.upper())
        self.network_config = getattr(network_class, network_type.upper())

        self.provider = Web3(
            Web3.HTTPProvider(
                self.network_config.RPC_URL,
                request_kwargs=request_kwargs or {"timeout": 10},
            )
        )
        if self.network_config.MIDDLEWARE == "POA":
            self.provider.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        address = registry_address or contract["address_bloxberg"]
        self.contract = self.provider.eth.contract(
            address=to_checksum_address(address), abi=contract["abi"]
        )

    @staticmethod
    def key_hash(key: str) -> bytes:
        """keccak256 of the application key -- the bytes32 the contract keys on.

        Must match what the enclave computes for the same key, or reads land on
        a different slot and silently return "no state".
        """
        return Web3.keccak(text=key)

    @staticmethod
    def looks_like_cid(value: Any) -> bool:
        """True only for values shaped like an IPFS CID.

        The contract accepts any non-empty string as the pointer, so a buggy
        enclave can commit something that is not a CID (the live registry holds
        one such entry). Callers must not hand those to IPFS, where they can
        only error or retry-loop.

        CIDv0 is 46 chars starting "Qm"; CIDv1 is base32 starting "b".
        """
        cid = (value or "").strip() if isinstance(value, str) else ""
        if not cid or cid.startswith("0x"):
            return False
        if cid.startswith("Qm") and len(cid) == 46:
            return True
        if cid.startswith("b") and len(cid) >= 46 and cid.islower():
            return True
        return False

    def get_version(self, enclave_address: str, key: str) -> int:
        """Current version for (enclave, key); 0 when never committed."""
        return int(
            self.contract.functions.getVersion(
                to_checksum_address(enclave_address), self.key_hash(key)
            ).call()
        )

    def exists(self, enclave_address: str, key: str) -> bool:
        """True when this (enclave, key) has ever been committed."""
        return bool(
            self.contract.functions.exists(
                to_checksum_address(enclave_address), self.key_hash(key)
            ).call()
        )

    def get_nonce(self, enclave_address: str, key: str) -> int:
        """Last accepted idempotency nonce for (enclave, key); 0 when none.

        The nonce is PUBLIC on-chain data, recorded next to the version, so a
        web3 client can learn the latest accepted value with one free eth_call
        and pick the next one (any greater value; gaps are allowed) before
        submitting a state-writing task with an idempotency guard. Registries
        that predate the on-chain nonce field have no getNonce view -- this
        raises there, like calling any missing function would.
        """
        return int(
            self.contract.functions.getNonce(
                to_checksum_address(enclave_address), self.key_hash(key)
            ).call()
        )

    def get_state(self, enclave_address: str, key: str) -> dict:
        """Metadata for (enclave, key).

        Returns {cid, version, updated_at, valid}, where `valid` reports whether
        the stored pointer actually looks like a CID.
        """
        cid, version, updated_at = self.contract.functions.getState(
            to_checksum_address(enclave_address), self.key_hash(key)
        ).call()
        return {
            "cid": cid,
            "version": int(version),
            "updated_at": int(updated_at),
            "valid": self.looks_like_cid(cid),
        }

    def wait_for_version(
        self,
        enclave_address: str,
        key: str,
        after_version: int,
        timeout: float = 120,
        poll: float = 3,
    ) -> Optional[int]:
        """Block until the version for (enclave, key) exceeds `after_version`.

        Lets a caller wait for a task's state change to land before re-reading,
        instead of guessing at a delay. Returns the new version, or None on
        timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            version = self.get_version(enclave_address, key)
            if version > after_version:
                return version
            time.sleep(poll)
        return None
