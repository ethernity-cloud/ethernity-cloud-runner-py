from enum import Enum
from enum import IntEnum

class ECStatus(Enum):
    ERROR: str = "Error"
    SUCCESS: str = "Success"
    RUNNING: str = "Running"


class ECEvent(Enum):
    INIT: str = "Task initialized"
    CREATED: str = "Task created"
    ORDER_PLACED: str = "Order placed"
    IN_PROGRESS: str = "In Progress"
    FINISHED: str = "Finished"


ECOrderTaskStatus = {
    0: "SUCCESS",
    1: "SYSTEM_ERROR",
    2: "KEY_ERROR",
    3: "SYNTAX_WARNING",
    4: "BASE_EXCEPTION",
    5: "PAYLOAD_NOT_DEFINED",
    6: "PAYLOAD_CHECKSUM_ERROR",
    7: "INPUT_CHECKSUM_ERROR",
}


class ECOrderTaskStatusCode(Enum):
    SUCCESS = "SUCCESS"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    KEY_ERROR = "KEY_ERROR"
    SYNTAX_WARNING = "SYNTAX_WARNING"
    BASE_EXCEPTION = "BASE_EXCEPTION"
    PAYLOAD_NOT_DEFINED = "PAYLOAD_NOT_DEFINED"
    PAYLOAD_CHECKSUM_ERROR = "PAYLOAD_CHECKSUM_ERROR"
    INPUT_CHECKSUM_ERROR = "INPUT_CHECKSUM_ERROR"


ECNetworkByChainId = {
    "BLOXBERG": {"TESTNET": 8995, "MAINNET": 8995},
    "POLYGON": {"TESTNET": 80001, "MAINNET": 137},
}

ECNetworkByChainIdDictionary = {8995: "bloxberg", 80001: "maticmum", 137: "matic"}


class ECNetwork:
    class BLOXBERG:
        TESTNET = "Bloxberg TESTNET"
        MAINNET = "Bloxberg MAINNET"

    class POLYGON:
        TESTNET = "Polygon TESTNET"
        MAINNET = "Polygon MAINNET"


class ECRunner:
    BLOXBERG = {
        "PYNITHY_RUNNER_TESTNET": "etny-pynithy-testnet",
        "NODENITHY_RUNNER_TESTNET": "etny-nodenithy-testnet",
        "PYNITHY_RUNNER_MAINNET": "etny-pynithy",
        "NODENITHY_RUNNER_MAINNET": "etny-nodenithy"
    }
    POLYGON = {
        "PYNITHY_RUNNER_TESTNET": "ecld-pynithy-mumbai",
        "NODENITHY_RUNNER_TESTNET": "ecld-nodenithy",
        "PYNITHY_RUNNER_MAINNET": "ecld-pynithy",
        "NODENITHY_RUNNER_MAINNET": "ecld-nodenithy"
    }
    
    def __getitem__(self, key):
        return getattr(self, key)


class ECAddress:
    class BLOXBERG:
        TESTNET_ADDRESS = "0x02882F03097fE8cD31afbdFbB5D72a498B41112c"
        MAINNET_ADDRESS = "0x549A6E06BB2084100148D50F51CF77a3436C3Ae7"

        class IMAGE_REGISTRY:
            class PYNITHY:
                TESTNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"
                MAINNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"

            class NODENITHY:
                TESTNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"
                MAINNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"

    class POLYGON:
        TESTNET_ADDRESS = "0xfb450e40f590F1B5A119a4B82E6F3579D6742a00"
        TESTNET_PROTOCOL_ADDRESS = "0x4274b1188ABCfa0d864aFdeD86bF9545B020dCDf"
        MAINNET_ADDRESS = "0xc6920888988cAcEeA7ACCA0c96f2D65b05eE22Ba"
        MAINNET_PROTOCOL_ADDRESS = "0x439945BE73fD86fcC172179021991E96Beff3Cc4"

        class IMAGE_REGISTRY:
            class PYNITHY:
                TESTNET_ADDRESS = "0xF7F4eEb3d9a64387F4AcEb6d521b948E6E2fB049"
                MAINNET_ADDRESS = "0x689f3806874d3c8A973f419a4eB24e6fBA7E830F"

            class NODENITHY:
                TESTNET_ADDRESS = "0xF7F4eEb3d9a64387F4AcEb6d521b948E6E2fB049"
                MAINNET_ADDRESS = "0x689f3806874d3c8A973f419a4eB24e6fBA7E830F"


class ECNetworkName(Enum):
    BLOXBERG = "bloxberg"
    MUMBAI = "maticmum"
    POLYGON = "matic"
    OTHER = "other"


ECNetworkNameDictionary = {
    ECAddress.BLOXBERG.MAINNET_ADDRESS: "bloxberg",
    ECAddress.BLOXBERG.TESTNET_ADDRESS: "bloxberg",
    ECAddress.POLYGON.TESTNET_ADDRESS: "maticmum",
    ECAddress.POLYGON.MAINNET_ADDRESS: "matic",
}

ECNetworkName1Dictionary = {
    ECAddress.BLOXBERG.MAINNET_ADDRESS: "BLOXBERG",
    ECAddress.BLOXBERG.TESTNET_ADDRESS: "BLOXBERG",
    ECAddress.POLYGON.TESTNET_ADDRESS: "MUMBAI",
    ECAddress.POLYGON.MAINNET_ADDRESS: "POLYGON",
}

ECNetworkRPCDictionary = {
    ECAddress.BLOXBERG.MAINNET_ADDRESS: "https://bloxberg.ethernity.cloud",
    ECAddress.BLOXBERG.TESTNET_ADDRESS: "https://bloxberg.ethernity.cloud",
    ECAddress.POLYGON.TESTNET_ADDRESS: "https://rpc-mumbai.matic.today",
    ECAddress.POLYGON.MAINNET_ADDRESS: "https://polygon-rpc.com",
}

ECNetworkEnvToEnum = {
    "bloxberg_mainnet": ECAddress.BLOXBERG.MAINNET_ADDRESS,
    "bloxberg_testnet": ECAddress.BLOXBERG.TESTNET_ADDRESS,
    "polygon_testnet": ECAddress.POLYGON.TESTNET_ADDRESS,
    "polygon_mainnet": ECAddress.POLYGON.MAINNET_ADDRESS,
}

ZERO_CHECKSUM = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ECError(Enum):
    PARSE_ERROR = "The result is not a valid v3 result"
    IPFS_DOWNLOAD_ERROR = "Unable to download results, will keep trying until the download is complete."

class ECLog(IntEnum):
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4