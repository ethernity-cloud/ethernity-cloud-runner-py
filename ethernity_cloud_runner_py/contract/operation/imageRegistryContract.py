from typing import Any
import os
from eth_typing import Address
from eth_utils.address import to_checksum_address
from web3 import Web3
from web3.contract.contract import Contract
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import TxParams

from ...contract.abi.imageRegistryAbi import contract
from ...enums import ECAddress, ECRunner, ECNetworkRPCDictionary


class ImageRegistryContract:
    def __init__(
        self,
        network_address: Address = ECAddress.BLOXBERG.TESTNET_ADDRESS,  # type: ignore
        runner_type: str = ECRunner.BLOXBERG["PYNITHY_RUNNER_TESTNET"],
        signer: Any = None,
    ):
        self.signer = signer
        self.provider = self.newProvider(ECNetworkRPCDictionary[network_address])
        if network_address == ECAddress.BLOXBERG.TESTNET_ADDRESS:
            if runner_type == ECRunner.BLOXBERG["NODENITHY_RUNNER_TESTNET"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.NODENITHY.TESTNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
                # self.provider.eth.contract()
            elif runner_type == ECRunner.BLOXBERG["PYNITHY_RUNNER_TESTNET"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.PYNITHY.TESTNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
        elif network_address == ECAddress.BLOXBERG.MAINNET_ADDRESS:
            if runner_type == ECRunner.BLOXBERG["NODENITHY_RUNNER_MAINNET"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.NODENITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
            elif runner_type == ECRunner.BLOXBERG["PYNITHY_RUNNER_MAINNET"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.PYNITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
        elif network_address == ECAddress.POLYGON.MAINNET_ADDRESS:
            if runner_type == ECRunner.POLYGON["NODENITHY_RUNNER_MAINNET"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.NODENITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
            elif runner_type == ECRunner.POLYGON["PYNITHY_RUNNER_MAINNET"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.PYNITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
        elif network_address == ECAddress.POLYGON.AMOY_ADDRESS:
            if runner_type == ECRunner.POLYGON["NODENITHY_RUNNER_AMOY"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.NODENITHY.AMOY_ADDRESS
                    ),
                    abi=contract["abi"],
                )
            elif runner_type == ECRunner.POLYGON["PYNITHY_RUNNER_AMOY"]:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.PYNITHY.AMOY_ADDRESS
                    ),
                    abi=contract["abi"],
                )

    def newProvider(self, url: str) -> Web3:
        _w3 = Web3(Web3.HTTPProvider(url))
        #_w3.enable_unstable_package_management_api()
        _w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return _w3

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
