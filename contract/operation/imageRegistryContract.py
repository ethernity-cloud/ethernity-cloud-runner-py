from web3 import Web3
from enums import ECAddress, ECRunner
from contract.abi.imageRegistryAbi import contract
from eth_utils.address import to_checksum_address


class ImageRegistryContract:
    def __init__(
        self,
        network_address=ECAddress.BLOXBERG.TESTNET_ADDRESS,
        runner_type=ECRunner.BLOXBERG.NODENITHY_RUNNER,
    ):
        self.ethereum = Web3(Web3.HTTPProvider(network_address))
        self.provider = self.ethereum
        self.signer = self.provider.eth.default_account
        self.contract = None

        if network_address == ECAddress.BLOXBERG.TESTNET_ADDRESS:
            if runner_type == ECRunner.BLOXBERG.NODENITHY_RUNNER_TESTNET:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.NODENITHY.TESTNET_ADDRESS
                    ),
                    abi=contract["abi"],
                    signer=self.signer,
                )
                self.provider.eth.contract()
            elif runner_type == ECRunner.BLOXBERG.PYNITHY_RUNNER_TESTNET:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.PYNITHY.TESTNET_ADDRESS
                    ),
                    abi=contract["abi"],
                    signer=self.signer,  # Add this line to set the signer
                )
        elif network_address == ECAddress.BLOXBERG.MAINNET_ADDRESS:
            if runner_type == ECRunner.BLOXBERG.NODENITHY_RUNNER:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.NODENITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
            elif runner_type == ECRunner.BLOXBERG.PYNITHY_RUNNER:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.BLOXBERG.IMAGE_REGISTRY.PYNITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
        elif network_address == ECAddress.POLYGON.MAINNET_ADDRESS:
            if runner_type == ECRunner.POLYGON.NODENITHY_RUNNER:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.NODENITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
            elif runner_type == ECRunner.POLYGON.PYNITHY_RUNNER:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.PYNITHY.MAINNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
        elif network_address == ECAddress.POLYGON.TESTNET_ADDRESS:
            if runner_type == ECRunner.POLYGON.NODENITHY_RUNNER_TESTNET:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.NODENITHY.TESTNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )
            elif runner_type == ECRunner.POLYGON.PYNITHY_RUNNER_TESTNET:
                self.contract = self.provider.eth.contract(
                    address=to_checksum_address(
                        ECAddress.POLYGON.IMAGE_REGISTRY.PYNITHY.TESTNET_ADDRESS
                    ),
                    abi=contract["abi"],
                )

    def get_signer(self):
        return self.signer

    def get_contract(self):
        return self.contract

    def get_provider(self):
        return self.provider

    def get_enclave_details_v3(self, image_name, version):
        try:
            return self.contract.functions.getLatestTrustedZoneImageCertPublicKey(
                image_name, version
            ).call()
        except Exception as e:
            print(e)
            return None
