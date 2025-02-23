from typing import Any
import os
from eth_typing import Address
from eth_utils.address import to_checksum_address
from web3 import Web3
from web3.contract.contract import Contract
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import TxParams

from ...contract.abi.imageRegistryAbi import contract
from ...enums import ECNetwork

class ImageRegistryContract:
    def __init__(
        self,
        network_name = "BOXBERG", 
        network_type = "TESTNET",
        signer: Any = None,
    ):
        self.signer = signer
        
        
        # Access the network class (e.g., ECNetwork.BLOXBERG)
        network_class = getattr(ECNetwork, network_name.upper())
        
        # Access the network type class within the network class (e.g., ECNetwork.BLOXBERG.TESTNET)
        self.network_config = getattr(network_class, network_type.upper())

        self.provider = Web3(Web3.HTTPProvider(self.network_config.RPC_URL))

        if self.network_config.MIDDLEWARE == "POA":
            self.provider.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            
        self.contract = self.provider.eth.contract(
            address=to_checksum_address(
                self.network_config.IMAGE_REGISTRY_CONTRACT_ADDRESS
            ),
            abi=contract["abi"],
        )

    def get_signer(self) -> Any:
        return self.signer

    def get_contract(self) -> Contract:
        return self.contract

    def get_provider(self) -> Web3:
        return self.provider

    def get_enclave_details_v3(
        self, secureLockImage: str, secureLockVersion: str, trustedZoneImage: str = "", trustedZoneVersion: str = ""
    ) -> Any:
        try:
            if not trustedZoneImage or secureLockImage == trustedZoneImage:
                return self.contract.functions.getLatestTrustedZoneImageCertPublicKey(
                    secureLockImage, trustedZoneVersion
                ).call()
            else:
                trustedZonePublicKey = (
                    self.contract.functions.getLatestTrustedZoneImageCertPublicKey(
                        trustedZoneImage, trustedZoneVersion
                    ).call()[1]
                )
                imageDetails = self.contract.functions.getLatestImageVersionPublicKey(
                    secureLockImage, secureLockVersion
                ).call()
                return [imageDetails[0], trustedZonePublicKey, imageDetails[2]]
        except Exception as e:
            print(e)
            return None
